import { FileCode, Server, BarChart3, FileDown, Crosshair, Shield } from "lucide-react";

const STATS = [
  { icon: FileCode, value: "18+", label: "Languages", detail: "Code intelligence & outlining" },
  { icon: Server, value: "10+", label: "Agent Hosts", detail: "MCP & SDK integrations" },
  { icon: BarChart3, value: "13", label: "Savings Mechanisms", detail: "Token & cost reduction" },
  { icon: FileDown, value: "85%", label: "Read Compression", detail: "On large source files" },
  { icon: Crosshair, value: "100×", label: "Symbol Lookup", detail: "Fewer tokens vs. text search" },
  { icon: Shield, value: "MIT", label: "License", detail: "Open source, free to use" },
];

export default function StatsSection() {
  return (
    <section className="border-t border-neutral-900 bg-neutral-950/30 px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-neutral-100 md:text-3xl">
            Built for Scale
          </h2>
          <p className="mt-3 text-sm text-neutral-400">
            Atelier's measurement-driven approach means every saving is observable.
          </p>
        </div>

        <div className="mt-12 grid gap-px overflow-hidden border border-neutral-800 bg-neutral-800 sm:grid-cols-2 lg:grid-cols-3">
          {STATS.map((stat) => {
            const Icon = stat.icon;
            return (
              <div
                key={stat.label}
                className="bg-[#0a0a0a] p-6 transition hover:bg-neutral-950/80"
              >
                <Icon size={20} className="text-neutral-700" />
                <div className="mt-3 text-3xl font-bold text-brand-300">
                  {stat.value}
                </div>
                <div className="mt-2 text-sm font-bold text-neutral-100">
                  {stat.label}
                </div>
                <div className="mt-1 text-xs text-neutral-500">
                  {stat.detail}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
