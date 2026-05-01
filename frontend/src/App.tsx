import { NavLink, Route, Routes, Navigate } from "react-router-dom";
import Overview from "./pages/Overview";
import Traces from "./pages/Traces";
import Failures from "./pages/Failures";
import Environments from "./pages/Environments";
import Blocks from "./pages/Blocks";
import Savings from "./pages/Savings";
import Rubrics from "./pages/Rubrics";
import Integrations from "./pages/Integrations";
import Agents from "./pages/Agents";
import Plans from "./pages/Plans";

const BRAND = "#ff6041";

const tabs = [
  {
    to: "/overview",
    label: "Overview",
    icon: "🏠",
    description: "Stats & features",
  },
  {
    to: "/blocks",
    label: "Blocks",
    icon: "🧠",
    description: "Reusable procedures",
  },
  {
    to: "/traces",
    label: "Traces",
    icon: "📇",
    description: "Execution artifacts",
  },
  {
    to: "/rubrics",
    label: "Rubrics",
    icon: "📏",
    description: "Domain verification gates",
  },
  {
    to: "/agents",
    label: "Agents",
    icon: "🤖",
    description: "Agent definitions & modes",
  },
  {
    to: "/savings",
    label: "Savings",
    icon: "💰",
    description: "Cost & tokens",
  },
  {
    to: "/failures",
    label: "Failures",
    icon: "🚨",
    description: "Error clusters",
  },
  {
    to: "/environments",
    label: "Env",
    icon: "🌐",
    description: "Domain configs",
  },
  {
    to: "/integrations",
    label: "Integrations",
    icon: "🧩",
    description: "MCP & host adapters",
  },
];

export default function App() {
  return (
    <div
      className="min-h-full flex flex-col bg-neutral-950 text-neutral-200"
      style={{
        fontFamily:
          "'Hack Nerd Font Mono', 'Hack Nerd Font', 'Droid Sans Mono', monospace",
        background: "linear-gradient(180deg, #0a0a0a 0%, #0f0f0f 100%)",
      }}
    >
      {/* Header: modern terminal prompt style */}
      <header className="border-b border-neutral-800 px-6 py-4 bg-gradient-to-r from-neutral-950 to-neutral-900/50">
        <div className="flex items-center gap-3">
          <span className="text-2xl">⚙️</span>
          <div>
            <h1
              className="text-lg font-bold tracking-wide"
              style={{ color: BRAND }}
            >
              ❯ ATELIER
            </h1>
            <p className="text-xs text-neutral-500 font-mono tracking-wide">
              beseam reasoning runtime
            </p>
          </div>
        </div>
      </header>

      {/* Navigation: modern tab-style with sleek separator */}
      <nav className="flex gap-0 px-6 py-3 border-b border-neutral-800 bg-neutral-950/50 overflow-x-auto">
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              `px-4 py-2 text-xs transition flex items-center gap-1.5 whitespace-nowrap font-bold border-b-2 ${
                isActive
                  ? "text-white bg-neutral-900/30"
                  : "border-b-transparent text-neutral-500 hover:text-neutral-300"
              }`
            }
            style={({ isActive }) =>
              isActive 
                ? { borderBottomColor: BRAND, color: BRAND }
                : {}
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
          <Route path="/blocks" element={<Blocks />} />
          <Route path="/traces" element={<Traces />} />
          <Route path="/rubrics" element={<Rubrics />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/savings" element={<Savings />} />
          <Route path="/plans" element={<Plans />} />
          <Route path="/failures" element={<Failures />} />
          <Route path="/environments" element={<Environments />} />
          <Route path="/integrations" element={<Integrations />} />
        </Routes>
      </main>
    </div>
  );
}
