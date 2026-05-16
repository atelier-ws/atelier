import { useEffect, useState } from "react";
import { api, type HostAdapter, type MCPStatus, type Skill } from "../api";
import { getTelemetryConfig, type TelemetryConfig } from "../lib/insightsApi";
import {
  Alert,
  Card,
  Chip,
  DisclosureCard,
  EmptyState,
  FieldLabel,
} from "../components/WorkbenchUI";

// ---------------------------------------------------------------------------
// Hosts section
// ---------------------------------------------------------------------------

function HostIcon({ id }: { id: string }) {
  const SRC_MAP: Record<string, string> = {
    claude: "/logos/hosts/claude.svg",
    codex: "/logos/hosts/codex.svg",
    opencode: "/logos/hosts/opencode.png",
    copilot: "/logos/hosts/copilot.svg",
    gemini: "/logos/hosts/gemini.svg",
  };

  const ALT_MAP: Record<string, string> = {
    claude: "Anthropic Claude",
    codex: "OpenAI Codex",
    opencode: "OpenCode",
    copilot: "GitHub Copilot",
    gemini: "Google Gemini",
  };

  const src = SRC_MAP[id];
  if (!src) return <span className="text-xl">◌</span>;

  return (
    <span className="inline-flex h-7 w-7 items-center justify-center  bg-white p-1 overflow-hidden">
      <img
        src={src}
        alt={ALT_MAP[id] ?? id}
        className="h-full w-full object-contain"
        loading="lazy"
      />
    </span>
  );
}

const HOSTS = [
  {
    id: "claude",
    label: "Claude Code",
    desc: "Full plugin: agents + skills + MCP + hooks",
  },
  {
    id: "codex",
    label: "Codex",
    desc: "MCP config + Codex savings/update hooks",
  },
  {
    id: "opencode",
    label: "OpenCode",
    desc: "OpenCode config + shared telemetry",
  },
  {
    id: "copilot",
    label: "Copilot",
    desc: "MCP config + custom instructions + shared telemetry",
  },
  {
    id: "gemini",
    label: "Gemini CLI",
    desc: ".gemini/settings.json MCP + shared telemetry",
  },
];

function HostsSection() {
  const [hosts, setHosts] = useState<HostAdapter[]>([]);

  useEffect(() => {
    api
      .hosts()
      .then(setHosts)
      .catch(() => setHosts([]));
  }, []);

  return (
    <section className="space-y-3">
      <h2 className="text-xs uppercase tracking-widest text-neutral-500 font-mono">
        Hosts
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {HOSTS.map((hostMeta) => {
          const status = hosts.find((host) => host.host_id === hostMeta.id);
          return (
            <Card key={hostMeta.id} className="bg-neutral-950/80 p-4">
              <div className="flex items-start gap-3">
                <span className="shrink-0">
                  <HostIcon id={hostMeta.id} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="text-base font-semibold text-neutral-100">
                      {hostMeta.label}
                    </div>
                    <Chip
                      tone={status?.status === "active" ? "emerald" : "neutral"}
                    >
                      {status?.status ?? "not detected"}
                    </Chip>
                  </div>
                  <p className="mt-1 text-sm text-neutral-400">
                    {hostMeta.desc}
                  </p>
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Agents section
// ---------------------------------------------------------------------------

interface AgentDef {
  id: string;
  label: string;
  icon: string;
  color: string;
  description: string;
  tools: string[];
  mode: string;
  file: string;
  rules: string[];
}

const AGENTS: AgentDef[] = [
  {
    id: "code",
    label: "atelier:code",
    icon: "💜",
    color: "purple",
    description:
      "Main coding agent. Edits, refactors, fixes bugs, and ships features. MUST use the Atelier reasoning loop on every task.",
    tools: ["* (all tools)"],
    mode: "Context → Implement → Trace",
    file: "integrations/claude/plugin/agents/code.md",
    rules: [
      "Gather Context before starting (retrieve procedures and facts)",
      "Implement task following knowledge; call rescue on repeated failures",
      "Record Trace at completion with observable summary only",
    ],
  },
  {
    id: "explore",
    label: "atelier:explore",
    icon: "🔍",
    color: "cyan",
    description:
      "Read-only repo exploration. Retrieves ReasonBlocks, reads files, runs grep/search. Never edits, never runs migrations, never executes destructive commands.",
    tools: ["Read", "Grep", "Glob", "WebFetch", "context"],
    mode: "Context → Read-only investigation",
    file: "integrations/claude/plugin/agents/explore.md",
    rules: [
      "Call context to fetch matched ReasonBlocks and rules",
      "Read files, run grep/glob searches — never edit",
      "Return tight summary with ReasonBlock IDs and file/line citations",
    ],
  },
  {
    id: "review",
    label: "atelier:review",
    icon: "✅",
    color: "green",
    description:
      "Verifier agent. Reviews finished or in-progress patches against Atelier ReasonBlocks and rubrics. Blocks known dead ends. Uses context and verify but never edits code.",
    tools: ["Read", "Grep", "Glob", "context", "verify"],
    mode: "Verify patch → context → rubric_gate → verdict",
    file: "integrations/claude/plugin/agents/review.md",
    rules: [
      "Call context with task and changed files",
      "Identify ReasonBlocks whose dead_ends overlap with the patch",
      "For high-risk domains, call verify and require status != blocked",
      "Produce verdict: pass | warn | blocked (never approve blocked)",
    ],
  },
  {
    id: "repair",
    label: "atelier:repair",
    icon: "🔧",
    color: "red",
    description:
      "Repair specialist. Activated when a test/command/tool keeps failing the same way. Loads context, asks for rescue, applies smallest patch, and records postmortem trace.",
    tools: ["* (all tools)"],
    mode: "Context → Rescue → Patch → Verify → Postmortem",
    file: "integrations/claude/plugin/agents/repair.md",
    rules: [
      "Retrieve Context to understand current constraints",
      "Ask for rescue with task, error, files, recent_actions",
      "Apply smallest patch, verify deterministically, stop after 2 failed attempts",
      "Record postmortem Trace on completion",
    ],
  },
];

function AgentsSection() {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <section className="space-y-3">
      <h2 className="text-xs uppercase tracking-widest text-neutral-500 font-mono">
        Agents
      </h2>
      <div className="grid gap-2 sm:grid-cols-2">
        {AGENTS.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            expanded={expandedId === agent.id}
            onToggle={() =>
              setExpandedId(expandedId === agent.id ? null : agent.id)
            }
          />
        ))}
      </div>
    </section>
  );
}

const AGENT_BG: Record<string, string> = {
  purple: "bg-purple-700",
  cyan: "bg-cyan-700",
  green: "bg-green-700",
  red: "bg-red-700",
};

function AgentCard({
  agent,
  expanded,
  onToggle,
}: {
  agent: AgentDef;
  expanded: boolean;
  onToggle: () => void;
}) {
  const bg = AGENT_BG[agent.color] ?? "bg-neutral-800/40";
  return (
    <DisclosureCard
      open={expanded}
      onToggle={onToggle}
      contentClassName="space-y-4"
      header={
        <div className="flex min-w-0 items-start gap-4">
          <div className="mt-0.5 shrink-0 text-2xl">{agent.icon}</div>
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex flex-wrap items-center gap-3">
              <span
                className={`${bg} font-mono text-xs px-2 py-1 transition-transform inline-flex items-center gap-2 ${
                  expanded ? "rotate-0" : ""
                }`}
              >
                <span
                  className={`transition-transform ${expanded ? "rotate-90" : ""}`}
                >
                  ❯
                </span>
                <span className="font-bold text-neutral-200 text-sm">
                  {agent.label}
                </span>
              </span>
            </div>
            <p className="text-xs text-neutral-400">{agent.description}</p>
          </div>
        </div>
      }
    >
      {/* Tools */}
      <div>
        <FieldLabel className="mb-2">❯ tools</FieldLabel>
        <div className="flex flex-wrap gap-1">
          {agent.tools.map((t) => (
            <Chip
              key={t}
              tone="neutral"
              className="normal-case tracking-normal"
            >
              {t}
            </Chip>
          ))}
        </div>
      </div>

      {/* Rules */}
      <div>
        <FieldLabel className="mb-2">❯ rules</FieldLabel>
        <ul className="space-y-1">
          {agent.rules.map((r, i) => (
            <li key={i} className="text-xs text-neutral-300 leading-relaxed">
              {r}
            </li>
          ))}
        </ul>
      </div>

      {/* Mode */}
      <div>
        <FieldLabel className="mb-2">❯ mode</FieldLabel>
        <code className="text-[10px] bg-neutral-950 px-2 py-1 text-neutral-300 font-mono border border-neutral-700 block">
          {agent.mode}
        </code>
      </div>

      {/* Source */}
      <div className="pt-2 border-t border-neutral-800">
        <FieldLabel className="mb-2">Source</FieldLabel>
        <code className="text-[10px] bg-neutral-950 px-2 py-1 text-neutral-500 font-mono border border-neutral-700 block break-all">
          {agent.file}
        </code>
      </div>
    </DisclosureCard>
  );
}

// ---------------------------------------------------------------------------
// Skills section
// ---------------------------------------------------------------------------

function SkillsSection() {
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [config, setConfig] = useState<TelemetryConfig | null>(null);
  const [expandedSkill, setExpandedSkill] = useState<string | null>(null);

  const hiddenSkillCount = config === null ? 0 : config.dev_mode ? 0 : 4;
  const visibleSkills = skills ?? [];
  const totalSkillCount =
    skills === null ? null : visibleSkills.length + hiddenSkillCount;

  useEffect(() => {
    api
      .skills()
      .then(setSkills)
      .catch((e) => console.error("Failed to load skills:", e));

    getTelemetryConfig()
      .then(setConfig)
      .catch(() => undefined);
  }, []);

  return (
    <section className="space-y-3">
      <h2 className="text-xs uppercase tracking-widest text-neutral-500 font-mono">
        Skills
      </h2>
      <p className="text-xs text-neutral-400 mb-3">
        {totalSkillCount === null
          ? "Loading skill catalog..."
          : `${totalSkillCount} common skills in the repo. Click to expand and see full documentation for the ones available in this mode.`}
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        {visibleSkills.length > 0 ? (
          visibleSkills.map((s) => (
            <SkillCard
              key={s.name}
              skill={{
                name: s.name,
                desc: s.description,
                icon: "✓",
              }}
              isExpanded={expandedSkill === s.name}
              onToggle={() =>
                setExpandedSkill(expandedSkill === s.name ? null : s.name)
              }
            />
          ))
        ) : (
          <EmptyState title="Loading skills..." className="p-4 sm:col-span-2" />
        )}
        {hiddenSkillCount > 0 && (
          <Card className="border-dashed bg-neutral-950/40 px-4 py-3 sm:col-span-2">
            <p className="text-[11px] font-mono text-neutral-500">
              {hiddenSkillCount} dev-only skills hidden. Enable dev mode with{" "}
              <code>ATELIER_DEV_MODE=1</code> to install and inspect them.
            </p>
          </Card>
        )}
      </div>
    </section>
  );
}

function SkillCard({
  skill,
  isExpanded,
  onToggle,
}: {
  skill: { name: string; desc: string; icon: string };
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    if (isExpanded) {
      onToggle();
      return;
    }
    if (content) {
      onToggle();
      return;
    }
    setLoading(true);
    try {
      const skillData = await api.skill(skill.name);
      if (skillData) {
        setContent(skillData.content);
        onToggle();
      }
    } catch (e) {
      console.error("Failed to load skill:", e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="flex flex-col gap-2 bg-neutral-900/30 p-2">
      <button
        onClick={toggle}
        className="flex items-start gap-2 w-full text-left"
      >
        <span className="mt-0.5">{skill.icon}</span>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-mono font-medium text-neutral-200 truncate">
            {skill.name}
          </div>
          <div className="text-[10px] text-neutral-500 leading-tight">
            {skill.desc}
          </div>
        </div>
        <span className="text-neutral-600">
          {loading ? "..." : isExpanded ? "−" : "+"}
        </span>
      </button>
      {isExpanded && content && (
        <div className="mt-1 pt-2 border-t border-neutral-800">
          <pre className="text-neutral-400 whitespace-pre-wrap font-mono max-h-60 overflow-y-auto bg-neutral-950/50 p-2 text-[10px]">
            {content}
          </pre>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Tools section
// ---------------------------------------------------------------------------

const NS_MAP: Record<string, string> = {
  reasoning: "brain",
  lint: "brain",
  route: "brain",
  rescue: "brain",
  verify: "brain",
  read: "code",
  edit: "code",
  search: "code",
  sql: "code",
  code_index: "code",
  code_search: "code",
  code_symbol: "code",
  code_outline: "code",
  code_context: "code",
  code_impact: "code",
  shell: "shell",
  trace: "capture",
  memory: "storage",
  compact: "infra",
};

const NS_META: Record<string, { icon: string; label: string; color: string }> =
  {
    brain: {
      icon: "🧠",
      label: "brain",
      color: "text-purple-400 border-purple-900/50 bg-purple-950/10",
    },
    code: {
      icon: "⌘",
      label: "code",
      color: "text-cyan-300 border-cyan-900/50 bg-cyan-950/10",
    },
    shell: {
      icon: ">_",
      label: "shell",
      color: "text-orange-300 border-orange-900/50 bg-orange-950/10",
    },
    capture: {
      icon: "📇",
      label: "capture",
      color: "text-amber-400 border-amber-900/50 bg-amber-950/10",
    },
    storage: {
      icon: "🗄️",
      label: "storage",
      color: "text-emerald-400 border-emerald-900/50 bg-emerald-950/10",
    },
    infra: {
      icon: "⚙️",
      label: "infra",
      color: "text-sky-400 border-sky-900/50 bg-sky-950/10",
    },
  };

function canonicalName(name: string): string {
  return name.startsWith("atelier_") ? name.slice("atelier_".length) : name;
}

function getNamespace(name: string): string {
  return NS_MAP[name] ?? "other";
}

function descriptionIndicatesDev(description?: string): boolean {
  return !!description && description.startsWith("[DEV]");
}

function isDevTool(tool: MCPStatus): boolean {
  return tool.is_dev === true || descriptionIndicatesDev(tool.description);
}

function ToolsSection() {
  const [mcpTools, setMcpTools] = useState<MCPStatus[] | null>(null);
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .mcp_status()
      .then(setMcpTools)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <Alert tone="danger" description={err} />;

  return (
    <section className="space-y-3">
      <h2 className="text-xs uppercase tracking-widest text-neutral-500 font-mono">
        Tools
      </h2>
      {!mcpTools && <EmptyState title="Loading tools…" className="p-4" />}
      {mcpTools &&
        (() => {
          const seen = new Set<string>();
          const deduped: MCPStatus[] = [];
          for (const t of mcpTools) {
            const canonical = canonicalName(t.tool_name);
            if (!seen.has(canonical)) {
              seen.add(canonical);
              deduped.push({ ...t, tool_name: canonical });
            }
          }

          const groups: Record<string, MCPStatus[]> = {};
          for (const t of deduped) {
            const ns = getNamespace(t.tool_name);
            if (!groups[ns]) groups[ns] = [];
            groups[ns].push(t);
          }

          const nsOrder = [
            "brain",
            "code",
            "shell",
            "capture",
            "storage",
            "infra",
            "other",
          ];

          return (
            <div className="grid gap-5 sm:grid-cols-2">
              <p className="text-[10px] font-mono text-neutral-600 sm:col-span-2">
                {deduped.length} tools on stdio server: <code>atelier-mcp</code>
              </p>
              {nsOrder
                .filter((ns) => groups[ns]?.length)
                .map((ns) => {
                  const meta = NS_META[ns] ?? {
                    icon: "•",
                    label: ns,
                    color:
                      "text-neutral-400 border-neutral-800 bg-neutral-900/30",
                  };
                  const tools = groups[ns];
                  return (
                    <div key={ns}>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm">{meta.icon}</span>
                        <span className="text-[10px] uppercase tracking-widest font-mono text-neutral-500">
                          {meta.label}
                        </span>
                        <span className="text-[10px] text-neutral-700 font-mono">
                          ({tools.length})
                        </span>
                      </div>
                      <div className="space-y-px">
                        {tools.map((tool) => {
                          const isExpanded = expandedTool === tool.tool_name;
                          const desc = tool.description;
                          const isDev = isDevTool(tool);
                          const cleanDescription = descriptionIndicatesDev(desc)
                            ? desc!.slice("[DEV]".length).trim()
                            : desc;

                          return (
                            <div
                              key={tool.tool_name}
                              className={`border cursor-pointer transition-colors ${meta.color} ${isExpanded ? "border-b-0" : ""}`}
                              onClick={() =>
                                setExpandedTool(
                                  isExpanded ? null : tool.tool_name
                                )
                              }
                            >
                              <div className="flex items-center gap-3 px-4 py-2.5">
                                <span
                                  className={`w-1.5 h-1.5 flex-shrink-0 ${tool.available ? "bg-emerald-400" : "bg-neutral-600"}`}
                                />
                                <span className="font-mono font-semibold text-neutral-200 text-xs flex-1">
                                  {tool.tool_name}
                                </span>
                                {isDev && (
                                  <span className="text-[8px] font-bold text-amber-500/60 border border-amber-500/30 px-1 py-0.5 mr-2">
                                    DEV
                                  </span>
                                )}
                                {isDev && tool.mode === "passive" && (
                                  <span className="text-[8px] font-bold text-neutral-500 border border-neutral-700 px-1 py-0.5 mr-2">
                                    PASSIVE
                                  </span>
                                )}
                                <span className="text-[10px] text-neutral-600">
                                  {isExpanded ? "▲" : "▼"}
                                </span>
                              </div>
                              {isExpanded && (
                                <div className="px-4 pb-3 pt-1 border-t border-neutral-800/50">
                                  {cleanDescription ? (
                                    <p className="text-xs text-neutral-300 leading-relaxed">
                                      {cleanDescription}
                                    </p>
                                  ) : (
                                    <p className="text-xs text-neutral-600 italic">
                                      No description available.
                                    </p>
                                  )}
                                  <div className="mt-2 flex items-center gap-3">
                                    <span
                                      className={`text-[10px] font-mono px-2 py-0.5 ${tool.available ? "bg-emerald-900/30 text-emerald-300" : "bg-neutral-800 text-neutral-500"}`}
                                    >
                                      {tool.mode === "passive"
                                        ? "passive capture"
                                        : tool.available
                                          ? "available"
                                          : "unavailable"}
                                    </span>
                                    <code className="text-[10px] font-mono text-neutral-600">
                                      {tool.tool_name}
                                    </code>
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
            </div>
          );
        })()}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main System page: Host → Agents → Skills → Tools
// ---------------------------------------------------------------------------

export default function System() {
  return (
    <div className="space-y-10 text-sm">
      <HostsSection />
      <AgentsSection />
      <SkillsSection />
      <ToolsSection />
    </div>
  );
}
