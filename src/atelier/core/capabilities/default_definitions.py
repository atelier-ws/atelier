from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
MODES_DIR = Path("docs/agent-os/modes")

HOST_ROLE_IDS = ("code", "explore", "review", "plan", "execute", "research", "solve")
SURFACED_ROLE_IDS = ("code", "explore", "execute", "plan", "research", "review", "solve")
DEFAULT_OWNED_MODEL = "claude-opus-4.8"


@dataclass(frozen=True)
class ModeDoc:
    name: str
    skill_description: str
    agent_description: str
    body: str
    source_path: Path


@dataclass(frozen=True)
class ToolPolicy:
    policy_id: str
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()
    denied_actions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "allowed_tools": list(self.allowed_tools),
            "denied_tools": list(self.denied_tools),
            "denied_actions": list(self.denied_actions),
        }


@dataclass(frozen=True)
class ReviewContract:
    require_first_hand_evidence: bool = True
    verdict_format: str = "json-block"
    default_verdict: str = "NEEDS_FIX"
    checklist_fields: tuple[str, ...] = ("verdict", "checklist", "missing")

    def to_dict(self) -> dict[str, Any]:
        return {
            "require_first_hand_evidence": self.require_first_hand_evidence,
            "verdict_format": self.verdict_format,
            "default_verdict": self.default_verdict,
            "checklist_fields": list(self.checklist_fields),
        }


@dataclass(frozen=True)
class HostProjection:
    surface: str
    host: str
    output_name: str
    frontmatter: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "host": self.host,
            "output_name": self.output_name,
            "frontmatter": [
                {"key": key, "value": list(value) if isinstance(value, tuple) else value}
                for key, value in self.frontmatter
            ],
        }


@dataclass(frozen=True)
class PromptDefinition:
    prompt_id: str
    body: str = ""
    source_path: Path | None = None

    def render(self, repo_root: Path | None = None) -> str:
        if self.body:
            return self.body
        if self.source_path is None:
            return ""
        source = _resolve_repo_root(repo_root) / self.source_path
        if not source.exists():
            return ""
        if source_path_looks_like_mode_doc(self.source_path):
            return parse_frontmatter(source.read_text(encoding="utf-8"))[1].rstrip() + "\n"
        return markdown_body(source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "body": self.body,
            "source_path": self.source_path.as_posix() if self.source_path is not None else None,
        }


@dataclass(frozen=True)
class DefaultRole:
    role_id: str
    name: str
    skill_description: str
    agent_description: str
    prompt_source: Path | None
    prompt_body: str
    tool_policy: ToolPolicy
    workflow_usage: tuple[str, ...]
    model_default: str
    effort_default: str
    max_turns: int
    max_tokens: int
    read_mode_hint: str
    host_projections: tuple[HostProjection, ...] = ()
    review_contract: ReviewContract | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "name": self.name,
            "skill_description": self.skill_description,
            "agent_description": self.agent_description,
            "prompt_source": self.prompt_source.as_posix() if self.prompt_source is not None else None,
            "prompt_body": self.prompt_body,
            "tool_policy": self.tool_policy.to_dict(),
            "workflow_usage": list(self.workflow_usage),
            "model_default": self.model_default,
            "effort_default": self.effort_default,
            "max_turns": self.max_turns,
            "max_tokens": self.max_tokens,
            "read_mode_hint": self.read_mode_hint,
            "host_projections": [projection.to_dict() for projection in self.host_projections],
            "review_contract": self.review_contract.to_dict() if self.review_contract is not None else None,
        }


@dataclass(frozen=True)
class DefaultWorkflowStep:
    step_id: str
    role_id: str
    phase_prompt_id: str
    effort: str
    read_mode_hint: str
    fork_from: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "role_id": self.role_id,
            "phase_prompt_id": self.phase_prompt_id,
            "effort": self.effort,
            "read_mode_hint": self.read_mode_hint,
            "fork_from": self.fork_from,
        }


@dataclass(frozen=True)
class DefaultWorkflow:
    workflow_id: str
    stem_prompt_id: str
    steps: tuple[DefaultWorkflowStep, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "stem_prompt_id": self.stem_prompt_id,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True)
class BenchmarkProfile:
    profile_id: str
    role_id: str
    workflow_id: str
    retry_limit: int
    command_rules: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "role_id": self.role_id,
            "workflow_id": self.workflow_id,
            "retry_limit": self.retry_limit,
            "command_rules": list(self.command_rules),
        }


@dataclass(frozen=True)
class McpTemplate:
    template_id: str
    host: str
    command: str
    args: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "host": self.host,
            "command": self.command,
            "args": list(self.args),
        }


@dataclass(frozen=True)
class DefaultRegistry:
    roles: dict[str, DefaultRole]
    prompts: dict[str, PromptDefinition]
    workflows: dict[str, DefaultWorkflow]
    benchmark_profiles: dict[str, BenchmarkProfile]
    mcp_templates: dict[str, McpTemplate]

    def surfaced_role_ids(self, surface: str) -> tuple[str, ...]:
        return tuple(
            role_id
            for role_id, role in self.roles.items()
            if any(projection.surface == surface for projection in role.host_projections)
        )

    def projection(self, role_id: str, surface: str) -> HostProjection:
        role = self.roles[role_id]
        for projection in role.host_projections:
            if projection.surface == surface:
                return projection
        raise KeyError(f"missing projection: {role_id}:{surface}")

    def render_prompt(self, role_id: str, repo_root: Path | None = None) -> str:
        role = self.roles[role_id]
        if role.prompt_body:
            return role.prompt_body
        if role.prompt_source is None:
            return ""
        source = _resolve_repo_root(repo_root) / role.prompt_source
        if not source.exists():
            return ""
        return parse_frontmatter(source.read_text(encoding="utf-8"))[1].rstrip() + "\n"

    def render_named_prompt(self, prompt_id: str, repo_root: Path | None = None) -> str:
        return self.prompts[prompt_id].render(repo_root)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "roles": {role_id: role.to_dict() for role_id, role in self.roles.items()},
            "prompts": {prompt_id: prompt.to_dict() for prompt_id, prompt in self.prompts.items()},
            "workflows": {workflow_id: workflow.to_dict() for workflow_id, workflow in self.workflows.items()},
            "benchmark_profiles": {
                profile_id: profile.to_dict() for profile_id, profile in self.benchmark_profiles.items()
            },
            "mcp_templates": {template_id: template.to_dict() for template_id, template in self.mcp_templates.items()},
        }


def _resolve_repo_root(repo_root: Path | None) -> Path:
    return REPO_ROOT if repo_root is None else repo_root


def source_path_looks_like_mode_doc(path: Path) -> bool:
    return path.parts[:3] == ("docs", "agent-os", "modes")


def markdown_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).rstrip() + "\n"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("mode doc is missing frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("mode doc frontmatter is not terminated")
    meta: dict[str, str] = {}
    for raw_line in text[4:end].splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {raw_line}")
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    body = text[end + len("\n---\n") :].lstrip()
    return meta, body


def load_mode_docs(repo_root: Path | None = None) -> dict[str, ModeDoc]:
    root = _resolve_repo_root(repo_root)
    docs: dict[str, ModeDoc] = {}
    for path in sorted((root / MODES_DIR).glob("*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        name = meta["mode"]
        docs[name] = ModeDoc(
            name=name,
            skill_description=meta["skill_description"],
            agent_description=meta["agent_description"],
            body=body.rstrip() + "\n",
            source_path=path.relative_to(root),
        )
    return docs


def _projection(surface: str, host: str, output_name: str, items: Iterable[tuple[str, Any]]) -> HostProjection:
    return HostProjection(surface=surface, host=host, output_name=output_name, frontmatter=tuple(items))


def _role_projections() -> dict[str, tuple[HostProjection, ...]]:
    projections: dict[str, tuple[HostProjection, ...]] = {}
    for role_id in SURFACED_ROLE_IDS:
        opencode_name = "atelier" if role_id == "code" else role_id
        antigravity_name = "atelier-code" if role_id == "code" else f"atelier-{role_id}"
        projections[role_id] = (
            HostProjection(surface="shared_skill", host="shared", output_name=role_id),
            _projection("claude_agent", "claude", role_id, CLAUDE_STABLE_FRONTMATTER[role_id]),
            _projection("claude_agent_dev", "claude", f"{role_id}.dev", CLAUDE_DEV_FRONTMATTER[role_id]),
            _projection("opencode_agent", "opencode", opencode_name, OPENCODE_FRONTMATTER[role_id]),
            _projection(
                "antigravity_agent",
                "antigravity",
                antigravity_name,
                ANTIGRAVITY_FRONTMATTER[role_id],
            ),
        )
    return projections


def _tool_policies() -> dict[str, ToolPolicy]:
    return {
        "code": ToolPolicy(policy_id="code", allowed_tools=("*",)),
        "general": ToolPolicy(policy_id="general", allowed_tools=("*",)),
        "explore": ToolPolicy(
            policy_id="explore",
            allowed_tools=("read", "grep", "search", "symbols", "node", "usages", "explore"),
            denied_actions=("edit", "write", "delete"),
        ),
        "plan": ToolPolicy(
            policy_id="plan",
            allowed_tools=(
                "read",
                "grep",
                "search",
                "symbols",
                "node",
                "usages",
                "callers",
                "callees",
                "impact",
                "explore",
                "web_fetch",
            ),
            denied_actions=("edit", "write", "delete"),
        ),
        "execute": ToolPolicy(policy_id="execute", allowed_tools=("*",)),
        "review": ToolPolicy(
            policy_id="review",
            allowed_tools=(
                "read",
                "grep",
                "search",
                "node",
                "usages",
                "callers",
                "impact",
                "verify",
            ),
            denied_actions=("edit", "write", "delete"),
        ),
        "research": ToolPolicy(
            policy_id="research",
            allowed_tools=("web_fetch", "web_search", "read", "search"),
            denied_actions=("edit", "write", "delete"),
        ),
        "solve": ToolPolicy(policy_id="solve", allowed_tools=("*",), denied_actions=("agent-spawn",)),
    }


def _fallback_mode_metadata() -> dict[str, tuple[str, str]]:
    return {
        "code": (
            "Switch to main Atelier coding mode. Uses Atelier MCP tools for file I/O, search, edits, and shell work. Applies the shared coding guidelines and validates changes before concluding.",
            "Main coding agent. Edits, refactors, fixes bugs, and ships features with the Atelier task loop.",
        ),
        "explore": (
            "Switch to read-only explorer mode. Locate files, symbols, and patterns. Never edit, create, or delete files.",
            "Read-only codebase explorer. Finds files, symbols, and patterns. Never edits.",
        ),
        "review": (
            "Switch to adversarial review mode. Apply the verification ladder, read the code directly, and never edit source files.",
            "Adversarial code reviewer. Applies the verification ladder and rubric discipline. Never edits source files.",
        ),
        "plan": (
            "Switch to planning mode. Explore enough to produce a concrete implementation plan, but do not edit files.",
            "Dedicated planner. Turns grounded context into a concrete, reviewable implementation plan. Never edits.",
        ),
        "execute": (
            "Switch to execution mode. Apply an accepted plan or task with the smallest verified code change.",
            "Dedicated executor. Makes focused edits, self-verifies, and stops for review.",
        ),
        "research": (
            "Switch to research mode. Fetch external docs and return a cited memo without editing files.",
            "External researcher. Fetches web pages, GitHub repos, and package docs. Never edits. Produces a structured memo with citations.",
        ),
        "solve": (
            "Switch to benchmark solve mode. Produce task artifacts early, iterate against checks, and keep the workspace clean.",
            "Dedicated benchmark solver. Solves isolated terminal tasks with artifact-first execution and harness-feedback retry discipline.",
        ),
    }


def _role_descriptions(mode_name: str, mode_docs: Mapping[str, ModeDoc]) -> tuple[str, str]:
    if mode_name in mode_docs:
        mode = mode_docs[mode_name]
        return mode.skill_description, mode.agent_description
    return _fallback_mode_metadata()[mode_name]


def _prompt_definitions() -> dict[str, PromptDefinition]:
    return {
        "owned-stem-system": PromptDefinition(
            prompt_id="owned-stem-system",
            body=(
                "You are operating inside Atelier's owned execution runtime. Keep the prompt prefix stable "
                "across phases, preserve trustworthy evidence, and treat the current phase prompt as the "
                "authoritative pivot for goals, tools, and output."
            ),
        ),
        "owned-explore-phase": PromptDefinition(
            prompt_id="owned-explore-phase",
            body=(
                "=== PIVOT: YOU ARE NOW IN THE EXPLORE PHASE ===\n"
                "Set aside implementation assumptions. Map the smallest set of files, symbols, constraints, "
                "and acceptance checks needed to ground the task. Prefer minified or selective reads."
            ),
        ),
        "owned-plan-phase": PromptDefinition(
            prompt_id="owned-plan-phase",
            body=(
                "=== PIVOT: YOU ARE NOW IN THE PLAN PHASE ===\n"
                "Set aside exploration habits that do not improve the plan. Produce the smallest executable "
                "plan with file order, risks, and the narrowest proving checks."
            ),
        ),
        "owned-execute-phase": PromptDefinition(
            prompt_id="owned-execute-phase",
            body=(
                "=== PIVOT: YOU ARE NOW IN THE EXECUTE PHASE ===\n"
                "Set aside prior-phase debate. Make the smallest verified change, prefer exact reads for edit "
                "targets, and leave behind only task-relevant artifacts."
            ),
        ),
        "owned-review-phase": PromptDefinition(
            prompt_id="owned-review-phase",
            body=(
                "=== PIVOT: YOU ARE NOW IN THE REVIEW PHASE ===\n"
                "Set aside implementer optimism. Gather first-hand evidence only, do not edit, and emit exactly "
                "one JSON verdict block with keys verdict, checklist, and missing. If evidence is ambiguous, use "
                "NEEDS_FIX."
            ),
        ),
        "owned-refine-phase": PromptDefinition(
            prompt_id="owned-refine-phase",
            body=(
                "=== PIVOT: YOU ARE NOW IN THE REFINE PHASE ===\n"
                "Set aside prior completion claims. Apply only the fixes justified by review evidence, rerun the "
                "narrow proof, and keep the conversation history forked from the plan phase."
            ),
        ),
        "solver-retry": PromptDefinition(
            prompt_id="solver-retry",
            body=(
                "=== PIVOT: YOU ARE NOW IN THE SOLVER RETRY PHASE ===\n"
                "Start from the prior attempt's forked context. Read harness feedback first, avoid blind command "
                "repetition, and change scope, input, or approach before retrying."
            ),
        ),
    }


def _default_workflows() -> dict[str, DefaultWorkflow]:
    return {
        "owned-execute-review-loop": DefaultWorkflow(
            workflow_id="owned-execute-review-loop",
            stem_prompt_id="owned-stem-system",
            steps=(
                DefaultWorkflowStep(
                    step_id="explore",
                    role_id="explore",
                    phase_prompt_id="owned-explore-phase",
                    effort="adaptive",
                    read_mode_hint="minified",
                ),
                DefaultWorkflowStep(
                    step_id="plan",
                    role_id="plan",
                    phase_prompt_id="owned-plan-phase",
                    effort="medium",
                    read_mode_hint="minified",
                    fork_from="explore",
                ),
                DefaultWorkflowStep(
                    step_id="execute",
                    role_id="execute",
                    phase_prompt_id="owned-execute-phase",
                    effort="high",
                    read_mode_hint="exact",
                    fork_from="plan",
                ),
                DefaultWorkflowStep(
                    step_id="review",
                    role_id="review",
                    phase_prompt_id="owned-review-phase",
                    effort="medium",
                    read_mode_hint="exact",
                    fork_from="plan",
                ),
                DefaultWorkflowStep(
                    step_id="refine",
                    role_id="execute",
                    phase_prompt_id="owned-refine-phase",
                    effort="medium",
                    read_mode_hint="exact",
                    fork_from="plan",
                ),
            ),
        ),
        "owned-benchmark-solver": DefaultWorkflow(
            workflow_id="owned-benchmark-solver",
            stem_prompt_id="owned-stem-system",
            steps=(
                DefaultWorkflowStep(
                    step_id="explore",
                    role_id="explore",
                    phase_prompt_id="owned-explore-phase",
                    effort="adaptive",
                    read_mode_hint="minified",
                ),
                DefaultWorkflowStep(
                    step_id="plan",
                    role_id="plan",
                    phase_prompt_id="owned-plan-phase",
                    effort="medium",
                    read_mode_hint="minified",
                    fork_from="explore",
                ),
                DefaultWorkflowStep(
                    step_id="execute",
                    role_id="solve",
                    phase_prompt_id="owned-execute-phase",
                    effort="high",
                    read_mode_hint="exact",
                    fork_from="plan",
                ),
                DefaultWorkflowStep(
                    step_id="review",
                    role_id="review",
                    phase_prompt_id="owned-review-phase",
                    effort="medium",
                    read_mode_hint="exact",
                    fork_from="plan",
                ),
                DefaultWorkflowStep(
                    step_id="retry",
                    role_id="solve",
                    phase_prompt_id="solver-retry",
                    effort="high",
                    read_mode_hint="exact",
                    fork_from="review",
                ),
            ),
        ),
    }


def _benchmark_profiles() -> dict[str, BenchmarkProfile]:
    return {
        "terminalbench-owned-solver": BenchmarkProfile(
            profile_id="terminalbench-owned-solver",
            role_id="solve",
            workflow_id="owned-benchmark-solver",
            retry_limit=2,
            command_rules=(
                "Install dependencies only when the task or failing check requires them.",
                "Do not hide stderr on install, build, or probe commands.",
                "Never mutate the benchmark harness directory unless the task explicitly names it.",
                "Use a generator script for large artifacts instead of pasting them inline.",
                "Remove scratch files, logs, binaries, and caches before stopping unless the task requests them.",
                "Commit to an artifact early, run the closest check, and iterate against the delta.",
                "Do not repeat a failed command verbatim; change the input, scope, timeout, or approach first.",
            ),
        )
    }


def _mcp_templates() -> dict[str, McpTemplate]:
    return {
        "claude-default": McpTemplate(
            template_id="claude-default",
            host="claude",
            command="atelier-mcp",
            args=("--host", "claude"),
        ),
        "codex-default": McpTemplate(
            template_id="codex-default",
            host="codex",
            command="atelier-mcp",
            args=("--host", "codex"),
        ),
        "antigravity-default": McpTemplate(
            template_id="antigravity-default",
            host="antigravity",
            command="atelier-mcp",
            args=("--host", "antigravity"),
        ),
    }


def build_default_registry(repo_root: Path | None = None) -> DefaultRegistry:
    mode_docs = load_mode_docs(repo_root)
    projections = _role_projections()
    policies = _tool_policies()
    roles: dict[str, DefaultRole] = {}

    for role_id in HOST_ROLE_IDS:
        skill_description, agent_description = _role_descriptions(role_id, mode_docs)
        roles[role_id] = DefaultRole(
            role_id=role_id,
            name=role_id.replace("-", " ").title(),
            skill_description=skill_description,
            agent_description=agent_description,
            prompt_source=Path("docs/agent-os/modes") / f"{role_id}.md",
            prompt_body="",
            tool_policy=policies[role_id],
            workflow_usage=_workflow_usage(role_id),
            model_default=DEFAULT_OWNED_MODEL,
            effort_default=_role_effort(role_id),
            max_turns=_role_turn_limit(role_id),
            max_tokens=_role_token_limit(role_id),
            read_mode_hint=_role_read_hint(role_id),
            host_projections=projections.get(role_id, ()),
            review_contract=ReviewContract() if role_id == "review" else None,
        )

    roles["general"] = DefaultRole(
        role_id="general",
        name="General",
        skill_description="Runtime-only general role for owned workflows that need a full-access assistant without host projection.",
        agent_description="Runtime-only general Atelier role. Uses the owned stem prompt and full tool access without generating host-facing artifacts.",
        prompt_source=None,
        prompt_body=(
            "General owned-runtime role. Use it when a workflow step does not fit the specialized code, "
            "explore, plan, review, research, or solve roles but still needs Atelier's execution discipline."
        ),
        tool_policy=policies["general"],
        workflow_usage=("owned-execute-review-loop", "owned-benchmark-solver"),
        model_default=DEFAULT_OWNED_MODEL,
        effort_default="medium",
        max_turns=8,
        max_tokens=32000,
        read_mode_hint="exact",
        host_projections=(),
    )

    return DefaultRegistry(
        roles=roles,
        prompts=_prompt_definitions(),
        workflows=_default_workflows(),
        benchmark_profiles=_benchmark_profiles(),
        mcp_templates=_mcp_templates(),
    )


def _workflow_usage(role_id: str) -> tuple[str, ...]:
    usage = {
        "code": ("owned-execute-review-loop",),
        "explore": ("owned-execute-review-loop", "owned-benchmark-solver"),
        "review": ("owned-execute-review-loop", "owned-benchmark-solver"),
        "plan": ("owned-execute-review-loop", "owned-benchmark-solver"),
        "execute": ("owned-execute-review-loop",),
        "research": (),
        "solve": ("owned-benchmark-solver",),
    }
    return usage[role_id]


def _role_effort(role_id: str) -> str:
    return {
        "code": "high",
        "general": "medium",
        "explore": "adaptive",
        "plan": "medium",
        "execute": "high",
        "review": "medium",
        "research": "medium",
        "solve": "high",
    }[role_id]


def _role_turn_limit(role_id: str) -> int:
    return {
        "code": 10,
        "general": 8,
        "explore": 6,
        "plan": 6,
        "execute": 8,
        "review": 6,
        "research": 6,
        "solve": 8,
    }[role_id]


def _role_token_limit(role_id: str) -> int:
    return {
        "code": 48000,
        "general": 32000,
        "explore": 24000,
        "plan": 24000,
        "execute": 40000,
        "review": 24000,
        "research": 24000,
        "solve": 40000,
    }[role_id]


def _role_read_hint(role_id: str) -> str:
    return {
        "code": "exact",
        "general": "exact",
        "explore": "minified",
        "plan": "minified",
        "execute": "exact",
        "review": "exact",
        "research": "minified",
        "solve": "exact",
    }[role_id]


CLAUDE_STABLE_FRONTMATTER: dict[str, tuple[tuple[str, Any], ...]] = {
    "code": (("name", "code"), ("description", ""), ("tools", ["*"]), ("color", "purple")),
    "explore": (
        ("name", "explore"),
        ("description", ""),
        (
            "tools",
            [
                "Read",
                "Grep",
                "Glob",
                "mcp__atelier__context",
                "mcp__atelier__search",
                "mcp__atelier__read",
                "mcp__atelier__grep",
                "mcp__atelier__node",
                "mcp__atelier__symbols",
                "mcp__atelier__usages",
                "mcp__atelier__explore",
                "mcp__atelier__memory",
            ],
        ),
        ("disallowedTools", ["Edit", "Write", "MultiEdit", "NotebookEdit", "Agent"]),
        ("color", "blue"),
    ),
    "review": (
        ("name", "review"),
        ("description", ""),
        (
            "tools",
            [
                "Read",
                "Grep",
                "Glob",
                "mcp__atelier__context",
                "mcp__atelier__read",
                "mcp__atelier__search",
                "mcp__atelier__node",
                "mcp__atelier__usages",
                "mcp__atelier__callers",
                "mcp__atelier__impact",
                "mcp__atelier__verify",
                "mcp__atelier__trace",
                "mcp__atelier__memory",
            ],
        ),
        ("color", "yellow"),
    ),
    "plan": (
        ("name", "plan"),
        ("description", ""),
        (
            "tools",
            [
                "Read",
                "Grep",
                "Glob",
                "WebFetch",
                "mcp__atelier__context",
                "mcp__atelier__search",
                "mcp__atelier__read",
                "mcp__atelier__grep",
                "mcp__atelier__node",
                "mcp__atelier__symbols",
                "mcp__atelier__usages",
                "mcp__atelier__callers",
                "mcp__atelier__callees",
                "mcp__atelier__impact",
                "mcp__atelier__explore",
                "mcp__atelier__memory",
            ],
        ),
        (
            "disallowedTools",
            ["Edit", "Write", "MultiEdit", "NotebookEdit", "mcp__atelier__edit", "Agent"],
        ),
        ("color", "cyan"),
    ),
    "execute": (("name", "execute"), ("description", ""), ("tools", ["*"]), ("color", "purple")),
    "research": (
        ("name", "research"),
        ("description", ""),
        (
            "tools",
            [
                "WebFetch",
                "WebSearch",
                "mcp__atelier__context",
                "mcp__atelier__search",
                "mcp__atelier__read",
                "mcp__atelier__memory",
            ],
        ),
        ("color", "green"),
    ),
    "solve": (
        ("name", "solve"),
        ("description", ""),
        ("tools", ["*"]),
        ("disallowedTools", ["Agent"]),
        ("color", "orange"),
    ),
}

CLAUDE_DEV_FRONTMATTER: dict[str, tuple[tuple[str, Any], ...]] = {
    "code": (
        ("name", "code"),
        ("description", ""),
        ("tools", ["*"]),
        ("disallowedTools", ["Read", "Edit", "Write", "Grep", "Glob", "NotebookEdit"]),
        ("color", "purple"),
    ),
    "explore": (
        ("name", "explore"),
        ("description", ""),
        ("color", "cyan"),
        (
            "tools",
            [
                "Read",
                "Grep",
                "Glob",
                "WebFetch",
                "mcp__atelier__context",
                "mcp__atelier__search",
                "mcp__atelier__read",
                "mcp__atelier__grep",
                "mcp__atelier__node",
                "mcp__atelier__symbols",
                "mcp__atelier__usages",
                "mcp__atelier__explore",
                "mcp__atelier__memory",
            ],
        ),
        (
            "disallowedTools",
            ["Edit", "Write", "MultiEdit", "NotebookEdit", "mcp__atelier__edit", "Agent"],
        ),
    ),
    "review": (
        ("name", "review"),
        ("description", ""),
        (
            "tools",
            [
                "Read",
                "Grep",
                "Glob",
                "mcp__atelier__context",
                "mcp__atelier__read",
                "mcp__atelier__search",
                "mcp__atelier__node",
                "mcp__atelier__usages",
                "mcp__atelier__callers",
                "mcp__atelier__impact",
                "mcp__atelier__verify",
                "mcp__atelier__trace",
                "mcp__atelier__memory",
            ],
        ),
        ("color", "yellow"),
    ),
    "plan": (
        ("name", "plan"),
        ("description", ""),
        ("color", "cyan"),
        (
            "tools",
            [
                "Read",
                "Grep",
                "Glob",
                "WebFetch",
                "mcp__atelier__context",
                "mcp__atelier__search",
                "mcp__atelier__read",
                "mcp__atelier__grep",
                "mcp__atelier__node",
                "mcp__atelier__symbols",
                "mcp__atelier__usages",
                "mcp__atelier__callers",
                "mcp__atelier__callees",
                "mcp__atelier__impact",
                "mcp__atelier__explore",
                "mcp__atelier__memory",
            ],
        ),
        (
            "disallowedTools",
            ["Edit", "Write", "MultiEdit", "NotebookEdit", "mcp__atelier__edit", "Agent"],
        ),
    ),
    "execute": (
        ("name", "execute"),
        ("description", ""),
        ("tools", ["*"]),
        ("disallowedTools", ["Read", "Edit", "Write", "Grep", "Glob", "NotebookEdit"]),
        ("color", "purple"),
    ),
    "research": (
        ("name", "research"),
        ("description", ""),
        (
            "tools",
            [
                "WebFetch",
                "WebSearch",
                "mcp__atelier__context",
                "mcp__atelier__search",
                "mcp__atelier__read",
                "mcp__atelier__memory",
            ],
        ),
        ("color", "green"),
    ),
    "solve": (
        ("name", "solve"),
        ("description", ""),
        ("tools", ["*"]),
        ("disallowedTools", ["Agent"]),
        ("color", "orange"),
    ),
}

OPENCODE_FRONTMATTER: dict[str, tuple[tuple[str, Any], ...]] = {
    "code": (
        ("description", "Atelier - main coding agent for the Agent Reasoning Runtime"),
        ("mode", "primary"),
    ),
    "explore": (
        (
            "description",
            "Read-only codebase explorer. Finds files, symbols, and patterns. Never edits.",
        ),
    ),
    "review": (
        (
            "description",
            "Adversarial code reviewer. Applies the verification ladder. Never edits source files.",
        ),
    ),
    "plan": (
        (
            "description",
            "Dedicated planner. Turns grounded context into a concrete, reviewable implementation plan. Never edits.",
        ),
    ),
    "execute": (
        (
            "description",
            "Dedicated executor. Makes focused edits, self-verifies, and stops for review.",
        ),
    ),
    "research": (
        (
            "description",
            "External researcher. Fetches web pages, GitHub repos, and package docs. Never edits. Produces a structured memo with citations.",
        ),
    ),
    "solve": (
        (
            "description",
            "Dedicated benchmark solver. Solves isolated terminal tasks with artifact-first execution and harness-feedback retry discipline.",
        ),
    ),
}

ANTIGRAVITY_FRONTMATTER: dict[str, tuple[tuple[str, Any], ...]] = {
    "code": (
        (
            "description",
            "Main Atelier coding agent. Uses Atelier MCP tools for all file I/O, search, edits, and shell work.",
        ),
    ),
    "explore": (
        (
            "description",
            "Read-only codebase explorer. Finds files, symbols, and patterns. Never edits.",
        ),
    ),
    "review": (
        (
            "description",
            "Adversarial code reviewer. Applies the verification ladder. Never edits source files.",
        ),
    ),
    "plan": (
        (
            "description",
            "Dedicated planner. Turns grounded context into a concrete, reviewable implementation plan. Never edits.",
        ),
    ),
    "execute": (
        (
            "description",
            "Dedicated executor. Makes focused edits, self-verifies, and stops for review.",
        ),
    ),
    "research": (
        (
            "description",
            "External researcher. Fetches web pages, GitHub repos, and package docs. Never edits. Produces a structured memo with citations.",
        ),
    ),
    "solve": (
        (
            "description",
            "Dedicated benchmark solver. Solves isolated terminal tasks with artifact-first execution and harness-feedback retry discipline.",
        ),
    ),
}


__all__ = [
    "ANTIGRAVITY_FRONTMATTER",
    "CLAUDE_DEV_FRONTMATTER",
    "CLAUDE_STABLE_FRONTMATTER",
    "DEFAULT_OWNED_MODEL",
    "HOST_ROLE_IDS",
    "OPENCODE_FRONTMATTER",
    "REPO_ROOT",
    "SURFACED_ROLE_IDS",
    "BenchmarkProfile",
    "DefaultRegistry",
    "DefaultRole",
    "DefaultWorkflow",
    "DefaultWorkflowStep",
    "HostProjection",
    "McpTemplate",
    "ModeDoc",
    "PromptDefinition",
    "ReviewContract",
    "ToolPolicy",
    "build_default_registry",
    "load_mode_docs",
    "markdown_body",
    "parse_frontmatter",
    "source_path_looks_like_mode_doc",
]
