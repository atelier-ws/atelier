from __future__ import annotations

from pathlib import Path

from atelier.core.capabilities.tool_supervision.bash_exec import classify_command


def test_inline_write_blocked_without_allowlist() -> None:
    decision = classify_command("python3 -c \"open('/tmp/x.json', 'w')\"")
    assert decision.action == "block"
    assert decision.category == "file-write"


def test_inline_write_to_allowed_root_permitted(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    decision = classify_command(
        f"python3 -c \"open('{target}', 'w')\"",
        allowed_write_roots=[tmp_path],
    )
    assert decision.action != "block"


def test_inline_write_outside_allowed_root_blocked(tmp_path: Path) -> None:
    outside = Path("/tmp/atelier-not-allowed-xyz/settings.json")
    decision = classify_command(
        f"python3 -c \"open('{outside}', 'w')\"",
        allowed_write_roots=[tmp_path],
    )
    assert decision.action == "block"


def test_variable_path_blocked_even_with_allowlist(tmp_path: Path) -> None:
    command = f"python3 - <<'PY'\np = '{tmp_path}/x'\nopen(p, 'w')\nPY"
    decision = classify_command(command, allowed_write_roots=[tmp_path])
    assert decision.action == "block"


def test_write_text_receiver_blocked(tmp_path: Path) -> None:
    target = tmp_path / "x.txt"
    decision = classify_command(
        f"python3 -c \"import pathlib; pathlib.Path('{target}').write_text('x')\"",
        allowed_write_roots=[tmp_path],
    )
    assert decision.action == "block"


def test_cat_redirect_to_allowed_root_permitted(tmp_path: Path) -> None:
    decision = classify_command(f"cat > {tmp_path / 'f.txt'}", allowed_write_roots=[tmp_path])
    assert decision.action != "block"


def test_permitted_write_still_blocks_chained_rm(tmp_path: Path) -> None:
    decision = classify_command(
        f"cat > {tmp_path / 'f.txt'} && rm -rf /tmp/atelier-some-dir",
        allowed_write_roots=[tmp_path],
    )
    assert decision.action == "block"
    assert decision.category == "destructive"


def test_relative_target_resolves_against_first_allowed_root(tmp_path: Path) -> None:
    # With the workspace root included as the first allowed root, a relative
    # target resolves against it and is permitted.
    decision = classify_command(
        "python3 -c \"open('sub/out.txt', 'w')\"",
        allowed_write_roots=[tmp_path],
    )
    assert decision.action != "block"
