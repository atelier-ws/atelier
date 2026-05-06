import { NavLink, Route, Routes, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import Overview from "./pages/Overview";
import Traces from "./pages/Traces";
import Learnings from "./pages/Learnings";
import Savings from "./pages/Savings";
import Host from "./pages/Host";
import Agents from "./pages/Agents";
import Tools from "./pages/Tools";
import Memory from "./pages/Memory";
import Insights from "./pages/Insights";
import {
  acknowledgeTelemetry,
  getTelemetryConfig,
  type TelemetryConfig,
} from "./lib/insightsApi";

const tabs = [
  {
    to: "/overview",
    label: "Overview",
    icon: "🏠",
    description: "Stats & features",
  },
  {
    to: "/trace",
    label: "Trace",
    icon: "📇",
    description: "Execution artifacts",
  },
  {
    to: "/learnings",
    label: "Learnings",
    icon: "🧠",
    description: "Blocks, plans, failures, domain laws",
  },
  {
    to: "/savings",
    label: "Savings",
    icon: "💰",
    description: "Cost & tokens",
  },
  {
    to: "/insights",
    label: "Insights",
    icon: "📊",
    description: "Product telemetry",
  },
  {
    to: "/memory",
    label: "Memory",
    icon: "💾",
    description: "Core blocks and archival recall",
  },
  {
    to: "/agents",
    label: "Agents",
    icon: "🤖",
    description: "Agent definitions, skills & modes",
  },
  {
    to: "/tools",
    label: "Tools",
    icon: "🔌",
    description: "MCP tools & capabilities",
  },
  {
    to: "/host",
    label: "Host",
    icon: "🖥️",
    description: "Host adapters & MCP configs",
  },
];

function TelemetryDisclosure() {
  const [config, setConfig] = useState<TelemetryConfig | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    getTelemetryConfig()
      .then(setConfig)
      .catch(() => undefined);
  }, []);

  if (!config || config.acknowledged || dismissed) return null;

  return (
    <div className="border-b border-amber-900/60 bg-amber-950/30 px-6 py-3 text-sm text-amber-100">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          Atelier collects anonymous usage telemetry to improve the product.
          Disable any time with{" "}
          <code className="bg-black/30 px-1">atelier telemetry off</code> or
          <code className="ml-1 bg-black/30 px-1">ATELIER_TELEMETRY=0</code>.
        </div>
        <button
          type="button"
          className="border border-amber-500/60 px-3 py-1 font-mono text-xs uppercase tracking-widest text-amber-100 hover:bg-amber-500/10"
          onClick={() => {
            setDismissed(true);
            acknowledgeTelemetry().catch(() => undefined);
          }}
        >
          Got it
        </button>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <div className="min-h-full flex flex-col bg-neutral-950 text-neutral-200 font-mono bg-gradient-to-b from-[#0a0a0a] to-[#0f0f0f]">
      {/* Header: modern terminal prompt style */}
      <header className="border-b border-neutral-800 px-6 py-4 bg-gradient-to-r from-neutral-950 to-neutral-900/50">
        <div className="flex items-center gap-3">
          <span className="text-2xl">⚙️</span>
          <div>
            <h1 className="text-lg font-bold tracking-wide text-[#ff6041]">
              ❯ ATELIER
            </h1>
            <p className="text-xs text-neutral-500 font-mono tracking-wide">
              Agent Reasoning Runtime
            </p>
          </div>
        </div>
      </header>

      <TelemetryDisclosure />

      {/* Navigation: modern tab-style with sleek separator */}
      <nav className="flex gap-0 px-6 py-3 border-b border-neutral-800 bg-neutral-950/50 overflow-x-auto">
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              `px-4 py-2 text-xs transition flex items-center gap-1.5 whitespace-nowrap font-bold border-b-2 ${
                isActive
                  ? "bg-neutral-900/30 border-b-[#ff6041] text-[#ff6041]"
                  : "border-b-transparent text-neutral-500 hover:text-neutral-300"
              }`
            }
            title={t.description}
          >
            <span>{t.icon}</span>
            <span>{t.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Main content - full width with terminal aesthetic */}
      <main className="flex-1 px-6 py-6 overflow-auto bg-gradient-to-br from-neutral-950 to-neutral-950/80">
        <Routes>
          <Route path="/" element={<Navigate to="/overview" replace />} />
          <Route path="/overview" element={<Overview />} />
          <Route path="/trace" element={<Traces />} />
          <Route path="/traces" element={<Navigate to="/trace" replace />} />
          <Route path="/learnings" element={<Learnings />} />
          <Route path="/learnings/:section" element={<Learnings />} />
          <Route path="/savings" element={<Savings />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/memory" element={<Memory />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/tools" element={<Tools />} />
          <Route path="/host" element={<Host />} />
        </Routes>
      </main>
    </div>
  );
}
