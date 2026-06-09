import { Sparkles, Repeat, ShieldCheck, Route } from "lucide-react";

const CATEGORIES = [
  {
    icon: Repeat,
    title: "Context Reuse",
    description: "Reuse procedures across sessions so agents don't rediscover the same patterns. Every cache hit is a cold read avoided.",
    savings: "Avoids 1–3 rounds of exploration per repeat task",
    badge: "−3 rounds",
  },
  {
    icon: Sparkles,
    title: "Smarter Tool Use",
    description: "Outline-mode reads, cached searches, batch edits with rollback, and token-budgeted results — fewer redundant tool calls.",
    savings: "Read compression up to 85% on large files",
    badge: "−85% tokens",
  },
  {
    icon: ShieldCheck,
    title: "Failure Prevention",
    description: "Detect thrashing loops, rescue from known error patterns, and surface fixes before the agent burns context budget.",
    savings: "Eliminates duplicate debugging cycles",
    badge: "−retries",
  },
  {
    icon: Route,
    title: "Model Optimization",
    description: "Route each task to the right model — cheap for lookups, capable for complex work — across every major vendor.",
    savings: "Simple work to cheap models, hard work to capable ones",
    badge: "−cost",
  },
];

export default function SavingsStack() {
  return (
    <section id="savings" className="relative border-t border-neutral-900 px-6 py-24">
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-20" />
      <div className="relative z-10 mx-auto max-w-5xl">
        <div className="text-center">
          <div className="text-[10px] font-bold uppercase tracking-[0.25em] text-amber-400/70">
            Cost Savings
          </div>
          <h2 className="mt-3 text-2xl font-bold text-neutral-100 md:text-3xl">
            How Atelier Saves LLM Cost
          </h2>
          <p className="mt-3 text-sm text-neutral-400">
            Atelier reduces token spend at every layer of the agent loop — context loading, tool calls, model selection, and recovery.
          </p>
        </div>

        <div className="mt-12 grid gap-4 md:grid-cols-2">
          {CATEGORIES.map((cat) => {
            const Icon = cat.icon;
            return (
              <div
                key={cat.title}
                className="group border border-neutral-800 bg-neutral-950/40 p-6 transition hover:border-neutral-600"
              >
                <div className="flex items-start gap-4">
                  <Icon size={24} className="mt-0.5 shrink-0 text-brand-400" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-sm font-bold text-neutral-100">
                        {cat.title}
                      </h3>
                      <span className="shrink-0 rounded border border-emerald-400/30 bg-emerald-400/5 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-400/90">
                        {cat.badge}
                      </span>
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-neutral-400">
                      {cat.description}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-8 border border-neutral-800 bg-neutral-950/40 p-5 text-center">
          <p className="text-xs leading-relaxed text-neutral-500">
            All savings are recorded into the run ledger and visible in the CLI, MCP, and dashboard.
            <br />
            <a
              href="https://atelier.beseam.com/docs"
              className="text-brand-300 no-underline transition hover:text-brand-200"
            >
              See the full savings breakdown in the docs →
            </a>
          </p>
        </div>
      </div>
    </section>
  );
}
