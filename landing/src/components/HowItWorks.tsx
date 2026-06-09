import { Terminal, Cpu, BarChart3, ArrowRight } from "lucide-react";

const STEPS = [
  {
    icon: Terminal,
    title: "1. Install in One Command",
    description:
      "Run the installer to set up the CLI, MCP server, and background services. Works standalone — no HTTP server required.",
  },
  {
    icon: Cpu,
    title: "2. Connect Your Agent Host",
    description:
      "Configure through MCP for Claude Code, Codex, Copilot, opencode, Cursor, Antigravity, Hermes, or use the SDK for LangChain, OpenAI, Gemini.",
  },
  {
    icon: BarChart3,
    title: "3. Measure & Save",
    description:
      "Atelier automatically records context reuse, cost savings, loop detection, and failure rescues. Dashboard shows every dollar and token saved.",
  },
];

export default function HowItWorks() {
  return (
    <section className="border-t border-neutral-900 px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-neutral-100 md:text-3xl">
            How It Works
          </h2>
          <p className="mt-3 text-sm text-neutral-400">
            Plugs into any agent host through MCP or SDK. Runs locally, no cloud dependency.
          </p>
        </div>

        {/* Steps */}
        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {STEPS.map((step) => {
            const Icon = step.icon;
            return (
              <div
                key={step.title}
                className="border border-neutral-800 bg-neutral-950/40 p-6"
              >
                <Icon size={28} className="text-brand-400" />
                <h3 className="mt-4 text-sm font-bold text-neutral-100">
                  {step.title}
                </h3>
                <p className="mt-2 text-xs leading-relaxed text-neutral-400">
                  {step.description}
                </p>
              </div>
            );
          })}
        </div>

        {/* Link to docs */}
        <div className="mt-10 text-center">
          <a
            href="https://atelier.beseam.com/docs"
            className="inline-flex items-center gap-1.5 text-xs uppercase tracking-widest text-brand-300 no-underline transition hover:text-brand-200"
          >
            See the full architecture in the docs
            <ArrowRight size={14} />
          </a>
        </div>
      </div>
    </section>
  );
}
