const HOSTS = [
  { name: "Claude Code", logo: "/logos/hosts/claude.svg", desc: "MCP + skills + agents + plugin hooks" },
  { name: "Codex CLI", logo: "/logos/hosts/codex.svg", desc: "MCP + AGENTS.md + hooks" },
  { name: "Copilot", logo: "/logos/hosts/copilot.svg", desc: "MCP + instructions" },
  { name: "opencode", logo: "/logos/hosts/opencode.svg", desc: "MCP + Agent" },
  { name: "Cursor IDE", logo: "/logos/hosts/cursor.svg", desc: "MCP" },
  { name: "Antigravity", logo: "/logos/hosts/antigravity.svg", desc: "MCP" },
  { name: "Hermes Agent", logo: "/logos/hosts/hermes-agent.svg", desc: "MCP" },
  { name: "Gemini ADK", logo: "/logos/hosts/gemini.svg", desc: "SDK middleware" },
  { name: "LangChain", logo: "/logos/hosts/langchain.svg", desc: "SDK middleware" },
  { name: "OpenAI SDK", logo: "/logos/hosts/openai.svg", desc: "SDK middleware" },
];

export default function HostsList() {
  return (
    <section id="hosts" className="relative border-t border-neutral-900 px-6 py-24">
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-20" />
      <div className="relative z-10 mx-auto max-w-5xl">
        <div className="text-center">
          <div className="text-[10px] font-bold uppercase tracking-[0.25em] text-neutral-500">
            Integrations
          </div>
          <h2 className="mt-3 text-2xl font-bold text-neutral-100 md:text-3xl">
            Works with Every Major Agent Host
          </h2>
          <p className="mt-3 text-sm text-neutral-400">
            Atelier integrates through MCP, SDK middleware, and instruction files.
            One runtime, every host.
          </p>
        </div>

        <div className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {HOSTS.map((host) => (
            <div
              key={host.name}
              className="group flex items-center gap-4 border border-neutral-800 bg-neutral-950/40 p-4 transition hover:border-neutral-600"
            >
              {host.logo ? (
                <div className="flex h-10 w-10 shrink-0 items-center justify-center border border-neutral-700 bg-white/5 p-1.5">
                  <img
                    src={host.logo}
                    alt={`${host.name} logo`}
                    className="h-full w-full object-contain"
                    loading="lazy"
                  />
                </div>
              ) : (
                <div className="flex h-10 w-10 shrink-0 items-center justify-center border border-neutral-700 bg-neutral-900/60 text-xs font-bold uppercase tracking-wider text-neutral-400">
                  {host.name.slice(0, 2)}
                </div>
              )}
              <div>
                <div className="text-sm font-bold text-neutral-100">
                  {host.name}
                </div>
                <div className="mt-0.5 text-[10px] uppercase tracking-widest text-neutral-600">
                  {host.desc}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-8 text-center">
          <a
            href="https://atelier.beseam.com/docs/hosts/all-agent-clis"
            className="inline-flex items-center gap-1.5 text-xs uppercase tracking-widest text-brand-300 no-underline transition hover:text-brand-200"
          >
            View full host documentation →
          </a>
        </div>
      </div>
    </section>
  );
}
