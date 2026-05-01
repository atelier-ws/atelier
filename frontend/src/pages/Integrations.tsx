import { useEffect, useState } from "react";
import { api, type MCPStatus, type HostAdapter } from "../api";

const HOSTS = [
  {
    id: "claude",
    label: "Claude Code",
    icon: "🧩",
    desc: "Full plugin: agents + skills + MCP",
  },
  {
    id: "codex",
    label: "Codex",
    icon: "📋",
    desc: "Skills + AGENTS.md + MCP config",
  },
  {
    id: "opencode",
    label: "opencode",
    icon: "🔌",
    desc: "opencode.jsonc MCP config",
  },
  {
    id: "copilot",
    label: "VS Code Copilot",
    icon: "💼",
    desc: "MCP config + custom instructions",
  },
  {
    id: "gemini",
    label: "Gemini CLI",
    icon: "📎",
    desc: ".gemini/settings.json MCP",
  },
];

export default function Integrations() {
  const [mcpTools, setMcpTools] = useState<MCPStatus[] | null>(null);
  const [skills, setSkills] = useState<any[] | null>(null);
  const [hosts, setHosts] = useState<HostAdapter[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<
    "agents" | "skills" | "mcp" | "hosts"
  >("agents");

  useEffect(() => {
    api
      .mcp_status()
      .then(setMcpTools)
      .catch((e) => setErr(String(e)));
    api
      .hosts()
      .then(setHosts)
      .catch(() => setHosts([]));
    api
      .skills()
      .then(setSkills)
      .catch((e) => console.error("Failed to load skills:", e));
  }, []);

  const installHost = (hostId: string) => {
    setInstalling(hostId);
    fetch(`/api/install/${hostId}`, { method: "POST" })
      .then(() => api.hosts().then(setHosts))
      .catch(console.error)
      .finally(() => setInstalling(null));
  };

  if (err) return <div className="text-red-400">Error: {err}</div>;

  return (
    <div className="space-y-6 text-sm">
      {/* Tab selector */}
      <div className="flex gap-1 border-b border-neutral-800">
        {(["agents", "skills", "mcp", "hosts"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-xs border-b-2 transition font-mono font-bold uppercase tracking-wide ${
              activeTab === tab
                ? "border-amber-400 text-amber-300"
                : "border-transparent text-neutral-400 hover:text-neutral-200"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Agents Tab */}
      {activeTab === "agents" && (
        <section>
          <p className="text-xs text-neutral-400 mb-3">
            4 agents shipped in Claude Code plugin. Each has its own system
            prompt, toolset, and rules.
          </p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <AgentCard
              id="code"
              icon="💜"
              color="purple"
              label="atelier:code"
              mode="Main coder"
              desc="MUST use reasoning loop on every task"
            />
            <AgentCard
              id="explore"
              icon="🔍"
              color="yellow"
              label="atelier:explore"
              mode="Read-only"
              desc="Investigation, never edits"
            />
            <AgentCard
              id="review"
              icon="✅"
              color="green"
              label="atelier:review"
              mode="Verifier"
              desc="Checks patches against blocks & rubrics"
            />
            <AgentCard
              id="repair"
              icon="🔧"
              color="orange"
              label="atelier:repair"
              mode="Repair"
              desc="Fix repeated failures with rescue"
            />
          </div>
        </section>
      )}

      {/* Skills Tab */}
      {activeTab === "skills" && (
        <section>
          <p className="text-xs text-neutral-400 mb-3">
            11 common skills available to all agent hosts. Click to expand and
            see full documentation.
          </p>
          <div className="grid grid-cols-1 gap-2">
            {skills && skills.length > 0 ? (
              skills.map((s) => (
                <SkillCard
                  key={s.name}
                  skill={{
                    name: s.name,
                    desc: s.description,
                    icon: "✓",
                    content: s.content,
                  }}
                />
              ))
            ) : (
              <div className="text-neutral-500 text-xs">Loading skills...</div>
            )}
          </div>
        </section>
      )}

      {/* MCP Tab */}
      {activeTab === "mcp" && (
        <section className="space-y-4">
          {/* Tools */}
          <div>
            <p className="text-xs text-neutral-400 mb-3">
              {mcpTools
                ? `${mcpTools.length} tools available`
                : "Loading tools..."}{" "}
              on stdio server:{" "}
              <code className="font-mono">uv run atelier-mcp</code>
            </p>
            <h3 className="text-[10px] uppercase tracking-widest text-neutral-500 mb-3">
              Available Tools
            </h3>
            {mcpTools && mcpTools.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {mcpTools.map((tool) => (
                  <div
                    key={tool.tool_name}
                    className={`border p-2 text-xs ${
                      tool.available
                        ? "border-emerald-900/50 bg-emerald-950/20"
                        : "border-neutral-800 bg-neutral-900/30"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-0.5">
                      <span
                        className={`w-1.5 h-1.5 ${
                          tool.available ? "bg-emerald-400" : "bg-neutral-600"
                        }`}
                      />
                      <span className="font-mono font-medium text-neutral-200">
                        {tool.tool_name}
                      </span>
                    </div>
                    {tool.description && (
                      <div className="text-neutral-500 leading-relaxed pl-3.5">
                        {tool.description}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-neutral-500 text-xs">
                {mcpTools === null ? "Loading..." : "No tools available"}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Hosts Tab */}
      {activeTab === "hosts" && (
        <section>
          <p className="text-xs text-neutral-400 mb-3">
            Each host gets native integration format. Installers are idempotent
            with backup-before-write.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {HOSTS.map((h) => {
              const status = hosts?.find((host) => host.name === h.id);
              return (
                <div
                  key={h.id}
                  className="border border-neutral-800  border border-neutral-800 p-3 bg-neutral-900/30 space-y-2"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{h.icon}</span>
                    <div className="flex-1">
                      <div className="text-sm font-bold text-neutral-300">
                        {h.label}
                      </div>
                      <div className="text-[10px] text-neutral-500">
                        {h.desc}
                      </div>
                    </div>
                    <StatusBadge status={status?.status || "not_installed"} />
                  </div>
                  <div className="flex items-center gap-2">
                    <code className="text-[10px] bg-neutral-900/20 px-1.5 py-0.5 text-neutral-400 flex-1 truncate">
                      make install-{h.id}
                    </code>
                    <button
                      onClick={() => installHost(h.id)}
                      disabled={installing === h.id}
                      className="text-[10px] px-2 py-1 font-mono font-bold uppercase tracking-tight transition disabled:opacity-50 bg-amber-900/30 text-amber-400 border border-amber-800 hover:bg-amber-900/50"
                    >
                      {installing === h.id ? "..." : "install"}
                    </button>
                  </div>
                  {status?.mcp_connected && (
                    <div className="text-[10px] text-emerald-400">
                      MCP connected
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div className="mt-4 pt-3 border-t border-neutral-800 flex gap-2 flex-wrap">
            <QuickAction label="Install All" cmd="make install-agent-clis" />
            <QuickAction label="Verify All" cmd="make verify-agent-clis" />
          </div>
        </section>
      )}
    </div>
  );
}

function AgentCard({ id, icon, color, label, mode, desc }: any) {
  const [expanded, setExpanded] = useState(false);
  const colorMap: Record<string, string> = {
    purple: "border-purple-900/50 bg-purple-950/20 text-purple-400",
    yellow: "border-yellow-900/50 bg-yellow-950/20 text-yellow-400",
    green: "border-emerald-900/50 bg-emerald-950/20 text-emerald-400",
    orange: "border-orange-900/50 bg-orange-950/20 text-orange-400",
  };
  return (
    <div
      className={`border  border border-neutral-800 p-3 ${colorMap[color] || colorMap.purple}`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left"
      >
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-lg">{icon}</span>
          <span className="text-sm font-bold">{label}</span>
          <span className="ml-auto text-[9px] opacity-60">{mode}</span>
        </div>
        <div className="text-[11px] opacity-80">{desc}</div>
        <div className="text-[9px] text-neutral-600 mt-0.5">
          {expanded ? "− Collapse" : "+ Expand rules"}
        </div>
      </button>
      {expanded && (
        <div className="mt-2 pt-2 border-t border-current/30 space-y-1">
          <div className="text-[9px] uppercase tracking-widest opacity-60">
            Rules
          </div>
          {getAgentRules(id).map((r, i) => (
            <div
              key={i}
              className="text-[11px] pl-2 border-l border-current/30"
            >
              {r}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function getAgentRules(id: string): string[] {
  const rules: Record<string, string[]> = {
    code: [
      "Retrieve context before drafting plan",
      "Validate plan — never skip when blocked",
      "Rescue repeated failures before retrying",
      "Run rubric gate on high-risk domains",
      "Record trace at completion",
    ],
    explore: [
      "Call get_reasoning_context for blocks",
      "Read-only: never edit files",
      "Return tight summary with citations",
      "Never call write tools",
    ],
    review: [
      "Call get_reasoning_context with task+files",
      "Identify overlapping dead-end blocks",
      "Call check_plan against implied plan",
      "Require rubric_gate on high-risk domains",
      "Verdict: pass|warn|blocked (never approve blocked)",
    ],
    repair: [
      "Inspect RunLedger first — never re-derive",
      "Form single hypothesis not in tried/rejected",
      "Ask for rescue after 2+ same errors",
      "Apply smallest patch, verify deterministically",
      "Stop after 2 failed attempts",
    ],
  };
  return rules[id] || [];
}

function SkillCard({
  skill,
  onLoadContent,
}: {
  skill: { name: string; desc: string; icon: string; content?: string };
  onLoadContent?: (name: string, content: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [content, setContent] = useState<string | null>(skill.content || null);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    if (content) {
      setExpanded(true);
      return;
    }
    setLoading(true);
    try {
      const response = await fetch(`/api/skills?name=${skill.name}`);
      const data = await response.json();
      const skillData = data.length > 0 ? data[0] : null;
      if (skillData) {
        setContent(skillData.content);
        setExpanded(true);
        if (onLoadContent) {
          onLoadContent(skill.name, skillData.content);
        }
      }
    } catch (e) {
      console.error("Failed to load skill:", e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="border border-neutral-800 p-2 bg-neutral-900/30 flex flex-col gap-2">
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
          {loading ? "..." : expanded ? "−" : "+"}
        </span>
      </button>
      {expanded && content && (
        <div className="mt-1 pt-2 border-t border-neutral-800">
          <pre className="text-neutral-400 whitespace-pre-wrap font-mono max-h-60 overflow-y-auto bg-neutral-950/50 p-2">
            {content}
          </pre>
        </div>
      )}
    </div>
  );
}


function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    installed: "bg-emerald-900/40 text-emerald-400",
    partial: "bg-amber-900/40 text-amber-400",
    not_installed: "bg-neutral-800 text-neutral-500",
  };
  return (
    <span
      className={`text-[9px] px-1.5 py-0.5 font-bold uppercase tracking-tight ${map[status] || map.not_installed}`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

function QuickAction({ label, cmd }: { label: string; cmd: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(cmd);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="flex items-center gap-1.5 border border-neutral-800 px-2.5 py-1.5 bg-neutral-900/30">
      <span className="text-[10px] text-neutral-300 font-mono font-medium">
        {label}:
      </span>
      <code className="text-[10px] text-neutral-400 font-mono">{cmd}</code>
      <button
        onClick={copy}
        className="text-[9px] text-neutral-500 hover:text-neutral-200 transition font-mono"
      >
        {copied ? "✓" : "copy"}
      </button>
    </div>
  );
}
