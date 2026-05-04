import { useEffect, useState } from "react";
import { api, type HostAdapter } from "../api";

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

export default function Host() {
  const [hosts, setHosts] = useState<HostAdapter[] | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);

  useEffect(() => {
    api
      .hosts()
      .then(setHosts)
      .catch(() => setHosts([]));
  }, []);

  const installHost = (hostId: string) => {
    setInstalling(hostId);
    fetch(`/api/install/${hostId}`, { method: "POST" })
      .then(() => api.hosts().then(setHosts))
      .catch(console.error)
      .finally(() => setInstalling(null));
  };

  return (
    <div className="space-y-6">
      {/* Feature Info */}
      <div>
        <button onClick={() => setInfoOpen(!infoOpen)} className="text-[10px] text-neutral-600 hover:text-neutral-400 font-mono flex items-center gap-1 py-1">
          <span>{infoOpen ? "▼" : "▶"}</span> about
        </button>
        {infoOpen && <section className="border border-neutral-800 bg-neutral-900/50 p-5">
        <div className="flex items-start gap-4">
          <div className="text-3xl flex-shrink-0">🖥️</div>
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-2">
              <h2 className="font-mono font-bold text-neutral-200 text-lg">
                Host Adapters
              </h2>
              <span className="text-[10px] px-2 py-0.5 font-mono font-bold uppercase tracking-wide bg-emerald-900/30 text-emerald-300">
                stable
              </span>
            </div>
            <p className="font-mono text-[11px] text-neutral-500 mb-3">
              Agent-Native Integration
            </p>
            <p className="text-xs text-neutral-300 leading-relaxed mb-3">
              Native integration for all major coding agents. Each host gets its native format — Claude Code plugin, Codex skills, opencode config, Copilot MCP, and Gemini CLI support.
            </p>
            <div className="text-xs text-emerald-300/90 space-y-1">
              <p>✓ Zero-code agent integration via MCP standard</p>
              <p>✓ All major coding agents supported</p>
              <p>✓ Each agent gets its native integration format</p>
            </div>
          </div>
        </div>
      </section>}
      </div>

      <div className="space-y-6 text-sm">
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
                  className="border border-neutral-800 p-3 bg-neutral-900/30 space-y-2"
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
      </div>
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
