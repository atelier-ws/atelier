"""Unit tests for post-edit contract-literal discovery (edit_impact).

The feature surfaces the *other* files that still reference a quoted contract
literal (config key, wire field, kwarg name) an edit removed, so a rename or
deletion is finished at every parallel consumer -- not just the file handed to
the agent. These consumers have no call-graph edge to the edited site, so
symbol-level callers/callees never find them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atelier.core.capabilities.tool_supervision import edit_impact
from atelier.core.capabilities.tool_supervision.edit_impact import (
    _candidate_identifiers,
    _combine_matches,
    _is_structural_occurrence,
    contract_literal_impact,
    literal_replacements,
    removed_literals,
    sibling_symbol_impact,
)


def _astgrep_available() -> bool:
    try:
        from atelier.infra.code_intel.astgrep import AstGrepAdapter, AstGrepToolUnavailable

        try:
            AstGrepAdapter(Path(".")).search(pattern='"x"', language="python", limit=1)
        except AstGrepToolUnavailable:
            return False
        return True
    except Exception:  # noqa: BLE001
        return True  # importable but a transient error -> assume usable


_requires_astgrep = pytest.mark.skipif(not _astgrep_available(), reason="ast-grep binary unavailable")


# --------------------------------------------------------------------------- #
# literal_replacements / removed_literals -- pure string analysis             #
# --------------------------------------------------------------------------- #


def test_line_aligned_swap_is_detected_as_rename() -> None:
    edits = [{"old_string": "params['passwd'] = value", "new_string": "params['password'] = value"}]
    # Only the *removed* literal is keyed; it maps to its line-aligned replacement.
    assert literal_replacements(edits) == {"passwd": "password"}


def test_removed_without_clear_replacement_maps_to_none() -> None:
    # Multi-line edit where the literal is dropped, not swapped 1:1 on a line.
    edits = [{"old_string": "a = 'passwd'\nb = 1", "new_string": "b = 1\nc = 2"}]
    repl = literal_replacements(edits)
    assert repl.get("passwd") is None
    assert removed_literals(edits) == ["passwd"]


def test_additive_edit_removes_nothing() -> None:
    edits = [{"old_string": "x = 1", "new_string": "x = 1\ny = 'new_key'"}]
    assert literal_replacements(edits) == {}
    assert removed_literals(edits) == []


def test_noisy_and_short_literals_are_ignored() -> None:
    # '1'/'true' are noise; single-char 'q' is too short; all excluded.
    edits = [{"old_string": "a='1'; b='true'; c='q'", "new_string": "a='2'; b='false'; c='z'"}]
    assert literal_replacements(edits) == {}


def test_pure_move_within_edit_is_not_a_removal() -> None:
    # Literal present in both old and new (just relocated) is not "removed".
    edits = [{"old_string": "f('database', x)", "new_string": "g(x, 'database')"}]
    assert "database" not in literal_replacements(edits)


def test_non_string_descriptors_are_skipped() -> None:
    # Symbol/projection edits carry no old_string/new_string -> no literals.
    edits = [{"kind": "symbol", "name": "foo", "new_body": "def foo(): return 'passwd'"}]
    assert literal_replacements(edits) == {}


# --------------------------------------------------------------------------- #
# _is_structural_occurrence -- the text-fallback precision heuristic           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "line",
    [
        "settings['passwd'] = env",
        "value = cfg.get('passwd')",
        "{'passwd': 1}",
        "'passwd': value,",
    ],
)
def test_structural_occurrence_true_for_code_keys(line: str) -> None:
    assert _is_structural_occurrence(line, "passwd") is True


@pytest.mark.parametrize(
    "line",
    [
        "the 'passwd' field is legacy and unused",
        "note that 'passwd' was renamed",
    ],
)
def test_structural_occurrence_false_for_prose(line: str) -> None:
    assert _is_structural_occurrence(line, "passwd") is False


# --------------------------------------------------------------------------- #
# _combine_matches -- ast-grep authoritative for code, text adds non-code      #
# --------------------------------------------------------------------------- #


def test_combine_keeps_astgrep_code_and_adds_only_noncode_text() -> None:
    astgrep = [("db/client.py", 10, "settings['passwd']")]
    text = [
        ("db/client.py", 99, "# duplicate code-file hit from text -- drop"),
        ("conf/settings.ini", 4, "passwd = '...'"),
    ]
    combined = _combine_matches(astgrep, text)
    paths = {p for p, _, _ in combined}
    assert paths == {"db/client.py", "conf/settings.ini"}
    # The python hit comes from ast-grep (line 10), not the text layer (line 99).
    assert ("db/client.py", 10, "settings['passwd']") in combined
    assert ("db/client.py", 99, "# duplicate code-file hit from text -- drop") not in combined


def test_combine_uses_pure_text_when_astgrep_unavailable() -> None:
    text = [("db/client.py", 10, "settings['passwd']")]
    assert _combine_matches(None, text) == text


# --------------------------------------------------------------------------- #
# contract_literal_impact -- end to end                                       #
# --------------------------------------------------------------------------- #


def _write(root: Path, rel: str, body: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


@_requires_astgrep
def test_surfaces_parallel_consumer_and_excludes_touched_and_prose(tmp_path: Path) -> None:
    # django-14376 shape: a config key lives in two parallel code paths with no
    # call-graph edge; the edit fixes one, the other must be surfaced.
    _write(tmp_path, "db/base.py", "def get_connection_params(d):\n    return {'passwd': d['passwd']}\n")
    _write(tmp_path, "db/client.py", "def settings_to_args(d):\n    return ['--password', d['passwd']]\n")
    _write(tmp_path, "db/legacy.py", "# the 'passwd' key was the old name; do not flag this comment\nX = 1\n")

    edits = [{"old_string": "{'passwd': d['passwd']}", "new_string": "{'password': d['password']}"}]
    impact = contract_literal_impact(edits, engine=None, repo_root=tmp_path, touched_paths=["db/base.py"])

    assert impact is not None
    assert impact["status"] == "review_required"
    residuals = {r["removed"]: r for r in impact["remaining_contract_consumers"]}
    assert "passwd" in residuals
    assert residuals["passwd"]["replacement"] == "password"
    hit_paths = {m["path"] for m in residuals["passwd"]["matches"]}
    assert "db/client.py" in hit_paths  # parallel consumer surfaced
    assert "db/base.py" not in hit_paths  # touched file excluded
    assert "db/legacy.py" not in hit_paths  # comment/prose not a string node


@_requires_astgrep
def test_none_when_literal_occurs_nowhere_else(tmp_path: Path) -> None:
    _write(tmp_path, "only.py", "X = {'solo_key': 1}\n")
    edits = [{"old_string": "{'solo_key': 1}", "new_string": "{'renamed_key': 1}"}]
    impact = contract_literal_impact(edits, engine=None, repo_root=tmp_path, touched_paths=["only.py"])
    assert impact is None


class _FakeMatch:
    def __init__(self, file_path: str, line: int, text: str) -> None:
        self.file_path = file_path
        self.line = line
        self.text = text


class _FakeEngine:
    """Minimal _TextSearcher: returns canned hits keyed by the quoted query."""

    def __init__(self, by_query: dict[str, list[_FakeMatch]]) -> None:
        self._by_query = by_query

    def search_text(self, query: str, *, path: str = ".", limit: int = 50, ignore_case: bool = False) -> list:
        return self._by_query.get(query, [])


def test_text_fallback_recall_when_astgrep_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the ast-grep layer off; the language-agnostic text layer must still
    # surface a structural hit and drop prose.
    monkeypatch.setattr(edit_impact, "_astgrep_detect", lambda *a, **k: None)
    engine = _FakeEngine(
        {
            "'passwd'": [
                _FakeMatch("conf/db.cfg", 3, "value = config['passwd']"),
                _FakeMatch("docs/notes.md", 7, "the 'passwd' option is legacy"),  # prose -> dropped
            ]
        }
    )
    edits = [{"old_string": "d['passwd']", "new_string": "d['password']"}]
    impact = contract_literal_impact(edits, engine=engine, repo_root=tmp_path, touched_paths=["db/base.py"])
    assert impact is not None
    matches = impact["remaining_contract_consumers"][0]["matches"]
    paths = {m["path"] for m in matches}
    assert "conf/db.cfg" in paths
    assert "docs/notes.md" not in paths


# --------------------------------------------------------------------------- #
# sibling_symbol_impact -- distinctive-identifier-cluster discovery            #
# --------------------------------------------------------------------------- #


def test_candidate_identifiers_filters_noise() -> None:
    text = "def build(self, formatter):\n    return formatter.format_ticks(self.locator)\n"
    out = set(_candidate_identifiers(text, limit=20))
    assert {"formatter", "format_ticks", "locator"} <= out
    assert "self" not in out and "def" not in out


class _RepoEngine:
    """Minimal _TextSearcher that greps real .py files under a root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def search_text(self, query: str, *, path: str = ".", limit: int = 50, ignore_case: bool = False) -> list:
        hits: list[_FakeMatch] = []
        for p in sorted(self.root.rglob("*.py")):
            rel = str(p.relative_to(self.root))
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if query in line:
                    hits.append(_FakeMatch(rel, i, line))
                    if len(hits) >= limit:
                        return hits
        return hits


_SCALES = (
    "def build_legend(axis):\n"
    "    axis.set_view_interval(0, 1)\n"
    "    locator = axis.major.locator\n"
    "    locs = locator()\n"
    "    formatter = axis.major.formatter\n"
    "    labels = formatter.format_ticks(locs)\n"
    "    return locs, labels\n"
)
_UTILS = (
    "def locator_to_legend_entries(locator, limits):\n"
    "    raw = locator.tick_values(limits)\n"
    "    formatter = make_scalar_formatter()\n"
    "    return [formatter.format_ticks(x) for x in raw]\n"
)


def test_sibling_surfaced_via_shared_rare_symbols(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/scales.py",
        _SCALES.replace("    locs = locator()", "    locs = locator()\n    formatter.set_useoffset(False)"),
    )
    _write(tmp_path, "pkg/utils.py", _UTILS)
    _write(tmp_path, "pkg/unrelated.py", "def total(rows):\n    return sum(rows)\n")
    edits = [
        {
            "file_path": "pkg/scales.py",
            "old_string": "    locs = locator()",
            "new_string": "    formatter.set_useoffset(False)",
        }
    ]
    impact = sibling_symbol_impact(
        edits, engine=_RepoEngine(tmp_path), repo_root=tmp_path, touched_paths=["pkg/scales.py"]
    )
    assert impact is not None
    assert impact["status"] == "review_required"
    paths = {s["path"] for s in impact["sibling_implementations"]}
    assert "pkg/utils.py" in paths  # shares formatter/locator/format_ticks
    assert "pkg/scales.py" not in paths  # edited file excluded
    assert "pkg/unrelated.py" not in paths  # shares nothing distinctive


def test_sibling_none_when_few_shared(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/scales.py", _SCALES)
    _write(tmp_path, "pkg/other.py", "def render(formatter):\n    return formatter.draw()\n")
    edits = [
        {
            "file_path": "pkg/scales.py",
            "old_string": "    return locs, labels",
            "new_string": "    return list(locs), list(labels)",
        }
    ]
    impact = sibling_symbol_impact(
        edits, engine=_RepoEngine(tmp_path), repo_root=tmp_path, touched_paths=["pkg/scales.py"]
    )
    assert impact is None


def test_sibling_common_symbol_excluded_by_rarity(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/scales.py", _SCALES)
    _write(tmp_path, "pkg/utils.py", _UTILS)
    for n in range(6):
        _write(tmp_path, f"pkg/w{n}.py", "def w(formatter):\n    return formatter\n")
    edits = [
        {
            "file_path": "pkg/scales.py",
            "old_string": "    return locs, labels",
            "new_string": "    return list(locs), labels",
        }
    ]
    impact = sibling_symbol_impact(
        edits, engine=_RepoEngine(tmp_path), repo_root=tmp_path, touched_paths=["pkg/scales.py"], max_files_per_symbol=3
    )
    assert impact is None  # formatter now too common; locator+format_ticks alone = 2 < 3
