#!/usr/bin/env python3
"""Generate host instruction surfaces from the live Agent OS docs."""

from __future__ import annotations

# ruff: noqa: E402
import json
import sys
from itertools import takewhile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from atelier.core.capabilities.default_definitions import (
    DefaultRole,
    HostProjection,
    ModeDoc,
    build_default_registry,
    load_mode_docs,
)
from atelier.core.capabilities.model_settings import (
    CANONICAL_COPILOT_AGENT_MODEL,
    normalize_model_for_host,
    resolve_explicit_host_model,
    resolve_host_model,
)
from atelier.core.capabilities.workspace_host_overrides import (
    rewrite_agent_model,
)
from atelier.core.environment import skill_visible

CODING_GUIDELINES_PATH = ROOT / "integrations/shared/coding-guidelines.md"
CORE_DISCIPLINE_PATH = ROOT / "integrations/shared/core-discipline.md"
CHANGE_DISCIPLINE_PATH = ROOT / "integrations/shared/change-discipline.md"
TOOL_DISCIPLINE_PATH = ROOT / "integrations/shared/tool-discipline.md"
AGENTS_GUIDE_PATH = ROOT / "integrations/AGENTS.atelier.md"

# Bare ``{{TOKEN}}`` placeholders a mode doc may embed; each expands to a shared
# "## <heading>" section sourced from one canonical partial. A mode opts in by
# including the token anywhere in its body.
SHARED_SECTIONS: dict[str, tuple[str, Path]] = {
    "{{CODING_GUIDELINES}}": ("Coding Guidelines", CODING_GUIDELINES_PATH),
    "{{CORE_DISCIPLINE}}": ("Core discipline", CORE_DISCIPLINE_PATH),
    "{{CHANGE_DISCIPLINE}}": ("Change discipline", CHANGE_DISCIPLINE_PATH),
    "{{TOOL_DISCIPLINE}}": ("Tool discipline", TOOL_DISCIPLINE_PATH),
}
HOST_SKILL_DIRS = {
    "claude": ROOT / "integrations" / "claude" / "plugin" / "skills",
    "codex": ROOT / "integrations" / "codex" / "plugin" / "skills",
    "antigravity": ROOT / "integrations" / "antigravity" / "skills",
}
# Hosts where role-level skills are the primary injection mechanism.
# Hosts with a native session-agent concept (Claude, Antigravity) use agents
# for mode-switching and don't need role skills — only non-role extras go there.
ROLE_SKILL_HOSTS: frozenset[str] = frozenset({"codex"})


def _strip_leading_title(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).rstrip()


def _markdown_body(path: Path) -> str:
    return _strip_leading_title(path.read_text(encoding="utf-8"))


def coding_guidelines_section() -> str:
    return "\n".join(["## Coding Guidelines", "", _markdown_body(CODING_GUIDELINES_PATH)])


_CLAUDE_TOOL_PREFIX = "mcp__atelier__"
_OPENCODE_TOOL_PREFIX = "atelier_"
_CODEX_TOOL_PREFIX = "atelier."


def agent_guide() -> str:
    return AGENTS_GUIDE_PATH.read_text(encoding="utf-8").strip()


def render_managed_context(existing: str) -> str:
    block_start = "<!-- ATELIER START -->"
    block_end = "<!-- ATELIER END -->"
    body = agent_guide()
    managed = "\n".join([block_start, body, block_end])
    existing = existing.rstrip()

    if existing.strip() == body:
        updated = managed
    elif block_start in existing:
        before, _, remainder = existing.partition(block_start)
        _, found_end, after = remainder.partition(block_end)
        if not found_end:
            raise ValueError(f"missing {block_end} in managed instruction file")
        updated = f"{before}{managed}{after}".rstrip()
    elif block_end in existing:
        raise ValueError(f"missing {block_start} in managed instruction file")
    elif existing:
        updated = f"{existing}\n\n---\n\n{managed}"
    else:
        updated = managed

    return updated + "\n"


def _copilot_native_tools(role_id: str) -> list[str]:
    base = [
        "atelier/*",
        "search/codebase",
        "web/fetch",
        "findTestFiles",
        "web/githubRepo",
        "read/problems",
        "read/getTaskOutput",
        "search",
        "searchResults",
        "read/terminalLastCommand",
        "read/terminalSelection",
        "search/usages",
        "vscode/vscodeAPI",
    ]
    if role_id in {"code", "execute", "solve", "auto", "bare"}:
        base[1:1] = [
            "changes",
            "edit/editFiles",
            "execute/getTerminalOutput",
            "execute/runInTerminal",
            "execute/createAndRunTask",
            "execute/runTask",
            "execute/runTests",
            "execute/testFailure",
        ]
    return base


def render_copilot_agent(role: DefaultRole, mode_doc: ModeDoc, projection: HostProjection) -> str:
    tools = "\n".join(f'    "{tool}",' for tool in _copilot_native_tools(role.role_id))
    return (
        "\n".join(
            [
                "---",
                f'description: "{role.agent_description}"',
                f"model: {CANONICAL_COPILOT_AGENT_MODEL}",
                "tools:",
                "  [",
                tools,
                "  ]",
                "---",
                "",
                f"# atelier:{role.role_id}",
                "",
                f"You are operating as *atelier:{role.role_id}*.",
                "",
                render_mode_body(mode_doc),
            ]
        ).rstrip()
        + "\n"
    )


def render_cursor_coding_rules() -> str:
    return (
        "\n".join(
            [
                "---",
                "description: Behavioral guidelines to reduce common LLM coding mistakes."
                " Use when writing, reviewing, or refactoring code to avoid overcomplication,"
                " make surgical changes, surface assumptions, and define verifiable success criteria.",
                "alwaysApply: true",
                "---",
                "",
                coding_guidelines_section().strip(),
            ]
        ).rstrip()
        + "\n"
    )


def render_cursor_role_rule(role: DefaultRole, mode_doc: ModeDoc) -> str:
    return (
        "\n".join(
            [
                "---",
                f"description: Atelier {role.role_id} mode reference for Cursor.",
                "---",
                "",
                render_mode_body(mode_doc),
            ]
        ).rstrip()
        + "\n"
    )


def _already_active_guard(skill_name: str) -> str:
    """One-line blockquote that tells the model the skill is already loaded."""
    return f'> **Active** — do not call `Skill("atelier:{skill_name}")` again.'


def _inject_active_guard(content: str, skill_name: str) -> str:
    """Insert the already-active guard after the YAML frontmatter block."""
    guard = _already_active_guard(skill_name)
    lines = content.splitlines(keepends=True)
    in_fm = False
    end_idx: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
            else:
                end_idx = i
                break
    if end_idx is None:
        return guard + "\n\n" + content
    before = "".join(lines[: end_idx + 1])
    after_lines = lines[end_idx + 1 :]
    # Strip only the contiguous leading blank lines that follow the frontmatter close.
    skip = sum(1 for _ in takewhile(lambda ln: not ln.strip(), after_lines))
    after = "".join(after_lines[skip:])
    return before + "\n" + guard + "\n\n" + after


def render_shared_skill(role: DefaultRole, mode_doc: ModeDoc) -> str:
    body = _replace_inline_tool_names(render_mode_body(mode_doc), _CODEX_TOOL_PREFIX)
    return (
        "\n".join(
            [
                "---",
                f"name: {role.role_id}",
                f"description: {role.skill_description}",
                "---",
                "",
                _already_active_guard(role.role_id),
                "",
                body,
            ]
        ).rstrip()
        + "\n"
    )


def render_mode_body(mode_doc: ModeDoc) -> str:
    body = _strip_leading_title(mode_doc.body)
    for token, (_heading, source_path) in SHARED_SECTIONS.items():
        if token in body:
            body = body.replace(token, _markdown_body(source_path))
    return body


def _format_frontmatter_value(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_frontmatter(items: list[tuple[str, Any]]) -> str:
    lines = ["---"]
    for key, value in items:
        lines.append(f"{key}: {_format_frontmatter_value(value)}")
    lines.append("---")
    return "\n".join(lines)


def _inject_description(frontmatter: tuple[tuple[str, Any], ...], description: str) -> list[tuple[str, Any]]:
    rendered: list[tuple[str, Any]] = []
    for key, value in frontmatter:
        rendered.append((key, description if key == "description" and value == "" else value))
    return rendered


def render_claude_agent(role: DefaultRole, mode_doc: ModeDoc, projection: HostProjection) -> str:
    frontmatter = _inject_description(projection.frontmatter, role.agent_description)
    body = _replace_inline_tool_names(render_mode_body(mode_doc), _CLAUDE_TOOL_PREFIX)
    return "\n".join([render_frontmatter(frontmatter), "", body]).rstrip() + "\n"


def render_simple_agent(role: DefaultRole, mode_doc: ModeDoc, projection: HostProjection) -> str:
    identity_block = ["You are operating as *atelier:code*.", ""] if role.role_id == "code" else []
    return (
        "\n".join(
            [
                render_frontmatter(_inject_description(projection.frontmatter, role.agent_description)),
                "",
                *identity_block,
                render_mode_body(mode_doc),
            ]
        ).rstrip()
        + "\n"
    )


# Bare tool names referenced as inline code (`` `read` ``) in shared mode-doc
# sources.  When rendering for a host that prefixes tool names we replace the
# inline backtick span with the prefixed form (e.g. `` `read` `` → `` `atelier_read` ``).
_INLINE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "codemod",
        "code_search",
        "edit",
        "glob",
        "grep",
        "memory",
        "read",
        "search",
        "bash",
        "sql",
        "web_fetch",
    }
)


import re as _re


def _replace_inline_tool_names(body: str, prefix: str) -> str:
    """Replace backtick-quoted bare tool names with ``<prefix><tool>``.

    Only affects tool names in ``_INLINE_TOOL_NAMES`` that appear as inline
    code spans (`` `grep` `` → `` `atelier_grep` ``).  Ignores tool names
    already prefixed and names outside backticks.
    """

    def _replacer(m: _re.Match) -> str:
        name = m.group(1)
        if name in _INLINE_TOOL_NAMES:
            return f"`{prefix}{name}`"
        return m.group(0)

    return _re.sub(r"`(\w+)`", _replacer, body)


# Copilot exposes Atelier tools via the ``atelier/*`` allowlist entry.
_COPILOT_TOOL_PREFIX = "atelier/"


def render_agent(
    role: DefaultRole,
    mode_doc: ModeDoc,
    projection: HostProjection,
    *,
    tool_prefix: str = _CLAUDE_TOOL_PREFIX,
    host_label: str = "Atelier",
) -> str:
    """Host agent renderer with configurable tool name prefix.

    Different MCP hosts expose Atelier tools under different name prefixes.
    This renderer expands shared sections and rewrites bare tool names to the
    host's prefix so agents know the exact tool names to call.

    Parameters
    ----------
    tool_prefix : str
        Prefix Atelier MCP tools are registered under by the host, e.g.
        ``atelier_`` (OpenCode), ``mcp__atelier__`` (Claude Code stdio).
    host_label : str
        Human-readable host name for the generated prose.
    """
    p = tool_prefix
    identity_block = ["You are operating as *atelier:code*.", ""] if role.role_id == "code" else []
    body = _replace_inline_tool_names(render_mode_body(mode_doc), p)
    return (
        "\n".join(
            [
                render_frontmatter(_inject_description(projection.frontmatter, role.agent_description)),
                "",
                *identity_block,
                body,
            ]
        ).rstrip()
        + "\n"
    )


def _extra_shared_skill_paths(repo_root: Path, generated_role_ids: set[str]) -> dict[str, Path]:
    skills_root = repo_root / "integrations" / "skills"
    extras: dict[str, Path] = {}
    if not skills_root.exists():
        return extras
    for skill_dir in sorted(skills_root.iterdir()):
        skill_path = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_path.is_file():
            continue
        if skill_dir.name in generated_role_ids:
            continue
        if not skill_visible(skill_dir.name):
            continue
        extras[skill_dir.name] = skill_path
    return extras


def build_mode_outputs(root: Path | None = None) -> dict[Path, str]:
    repo_root = ROOT if root is None else root
    registry = build_default_registry(repo_root)
    mode_docs = load_mode_docs(repo_root)
    outputs: dict[Path, str] = {}
    generated_role_ids = set(registry.surfaced_role_ids("shared_skill"))

    for role_id in sorted(generated_role_ids):
        role = registry.roles[role_id]
        mode_doc = mode_docs[role_id]

        stable_projection = registry.projection(role_id, "claude_agent")
        stable_path = (
            repo_root / "integrations" / "claude" / "plugin" / "agents" / f"{stable_projection.output_name}.md"
        )
        outputs[stable_path] = rewrite_agent_model(
            render_claude_agent(role, mode_doc, stable_projection),
            normalize_model_for_host(
                "claude", resolve_explicit_host_model("claude", role_id, workspace_root=repo_root)
            ),
        )

        antigravity_projection = registry.projection(role_id, "antigravity_agent")
        antigravity_path = (
            repo_root
            / "integrations"
            / "antigravity"
            / "plugin"
            / "agents"
            / f"{antigravity_projection.output_name}.md"
        )
        outputs[antigravity_path] = render_simple_agent(role, mode_doc, antigravity_projection)

        opencode_projection = registry.projection(role_id, "opencode_agent")
        opencode_path = repo_root / "integrations" / "opencode" / "agents" / f"{opencode_projection.output_name}.md"
        outputs[opencode_path] = render_agent(
            role, mode_doc, opencode_projection, tool_prefix=_OPENCODE_TOOL_PREFIX, host_label="OpenCode"
        )

        copilot_projection = registry.projection(role_id, "copilot_agent")
        copilot_path = repo_root / "integrations" / "copilot" / "agents" / f"{copilot_projection.output_name}.agent.md"
        outputs[copilot_path] = render_copilot_agent(role, mode_doc, copilot_projection)

        cursor_path = repo_root / "integrations" / "cursor" / "rules" / f"atelier.{role_id}.mdc"
        outputs[cursor_path] = render_cursor_role_rule(role, mode_doc)

        shared_skill = render_shared_skill(role, mode_doc)
        for host, host_dir in HOST_SKILL_DIRS.items():
            if host in ROLE_SKILL_HOSTS:
                outputs[host_dir / role_id / "SKILL.md"] = shared_skill

    for skill_name, skill_path in _extra_shared_skill_paths(repo_root, generated_role_ids).items():
        content = _inject_active_guard(skill_path.read_text(encoding="utf-8"), skill_name)
        for host_dir in HOST_SKILL_DIRS.values():
            host_skill_path = host_dir / skill_name / "SKILL.md"
            outputs[host_skill_path] = content

    for output_path, content in outputs.items():
        if "{{" in content:
            raise ValueError(f"unexpanded template token in generated surface: {output_path}")
    return outputs


def build_outputs() -> dict[Path, str]:
    registry = build_default_registry(ROOT)
    mode_outputs = build_mode_outputs(ROOT)
    agents_path = ROOT / "AGENTS.md"
    copilot_path = ROOT / ".github/copilot-instructions.md"
    existing_agents = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    existing_copilot = copilot_path.read_text(encoding="utf-8") if copilot_path.exists() else ""
    outputs = {
        agents_path: render_managed_context(existing_agents),
        copilot_path: render_managed_context(existing_copilot),
        ROOT / "integrations/copilot/COPILOT_INSTRUCTIONS.atelier.md": agent_guide() + "\n",
        ROOT / "integrations/cursor/rules/coding-guidelines.mdc": render_cursor_coding_rules(),
    }
    for role_id in registry.surfaced_role_ids("copilot_agent"):
        projection = registry.projection(role_id, "copilot_agent")
        integration_path = ROOT / "integrations" / "copilot" / "agents" / f"{projection.output_name}.agent.md"
        outputs[ROOT / ".github" / "agents" / f"{projection.output_name}.agent.md"] = rewrite_agent_model(
            mode_outputs[integration_path],
            resolve_host_model("copilot", role_id, workspace_root=ROOT, fallback=CANONICAL_COPILOT_AGENT_MODEL),
        )
    outputs.update(mode_outputs)
    return outputs


def write_output(path: Path, expected: str) -> None:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if current == expected:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(expected, encoding="utf-8")


def main() -> int:
    for path, content in build_outputs().items():
        write_output(path, content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
