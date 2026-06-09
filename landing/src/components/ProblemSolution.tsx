import { AlertTriangle, Zap } from "lucide-react";

export default function ProblemSolution() {
  return (
    <section className="border-t border-neutral-900 px-6 py-24">
      <div className="mx-auto max-w-5xl">
        <div className="grid gap-12 md:grid-cols-2 md:gap-16">
          {/* Problem */}
          <div className="relative border-l-2 border-red-400/30 pl-6">
            <div className="absolute -left-3 top-0 flex h-6 w-6 items-center justify-center rounded-full border border-red-400/30 bg-[#0a0a0a]">
              <AlertTriangle size={14} className="text-red-400/80" />
            </div>
            <div className="text-[10px] font-bold uppercase tracking-[0.25em] text-red-400/80">
              The Problem
            </div>
            <h2 className="mt-3 text-xl font-bold text-neutral-100 md:text-2xl">
              Every agent starts from scratch
            </h2>
            <ul className="mt-6 space-y-4">
              {[
                "Agents rediscover the same procedures on every task — no shared memory between sessions.",
                "Failure patterns repeat across agents and teams, burning context budget on the same debugging cycles.",
                "Model costs compound from redundant reads, repeated searches, and thrashing loops that quietly drain budget.",
                "Each agent host (Claude Code, Codex, Copilot, Gemini) has its own tooling and context format — no portable runtime.",
              ].map((text) => (
                <li key={text} className="flex gap-3 text-sm leading-relaxed text-neutral-400">
                  <span className="mt-0.5 shrink-0 text-red-400/60">✗</span>
                  <span>{text}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Solution */}
          <div className="relative border-l-2 border-emerald-400/30 pl-6">
            <div className="absolute -left-3 top-0 flex h-6 w-6 items-center justify-center rounded-full border border-emerald-400/30 bg-[#0a0a0a]">
              <Zap size={14} className="text-emerald-400/80" />
            </div>
            <div className="text-[10px] font-bold uppercase tracking-[0.25em] text-emerald-400/80">
              The Solution
            </div>
            <h2 className="mt-3 text-xl font-bold text-neutral-100 md:text-2xl">
                    Atelier changes the equation
            </h2>
            <ul className="mt-6 space-y-4">
              {[
                "Reusable procedures from past sessions give agents context hits instead of cold reads — every shared procedure is one less round of exploration.",
                "Failure Rescue surfaces targeted procedures the moment a known error pattern reappears — no retry loops.",
                "Outline-mode reads, cached searches, and batch edits compress token usage by up to 85% on large files.",
                "One MCP runtime works across every major agent host with cross-vendor model routing and cost tracking built in.",
              ].map((text) => (
                <li key={text} className="flex gap-3 text-sm leading-relaxed text-neutral-400">
                  <span className="mt-0.5 shrink-0 text-emerald-400/80">✓</span>
                  <span>{text}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
