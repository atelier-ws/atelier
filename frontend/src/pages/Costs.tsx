import type { ElementType } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { BarChart3, FileText, TrendingUp, Zap } from "lucide-react";
import { ToggleGroup } from "../components/WorkbenchUI";
import Analytics from "./Analytics";
import Savings from "./Savings";
import Optimizations from "./Optimizations";
import Reports from "./Reports";

type Section = "spend" | "savings" | "advisor" | "reports";

const SECTIONS: { id: Section; label: string; icon: ElementType }[] = [
  { id: "spend", label: "Spend", icon: BarChart3 },
  { id: "savings", label: "Savings", icon: TrendingUp },
  { id: "advisor", label: "Advisor", icon: Zap },
  { id: "reports", label: "Reports", icon: FileText },
];

export default function Costs() {
  const { section } = useParams<{ section?: string }>();
  const navigate = useNavigate();
  const active = (section as Section) || "spend";

  const setSection = (s: Section) => navigate(`/costs/${s}`, { replace: true });

  return (
    <div className="space-y-6 p-6">
      <ToggleGroup
        variant="underline"
        size="sm"
        options={SECTIONS.map((s) => ({
          value: s.id,
          label: (
            <span className="flex items-center gap-1.5">
              <s.icon size={14} />
              <span>{s.label}</span>
            </span>
          ),
        }))}
        value={active}
        onChange={(value) => setSection(value as Section)}
      />

      {active === "spend" && <Analytics />}
      {active === "savings" && <Savings />}
      {active === "advisor" && <Optimizations />}
      {active === "reports" && <Reports />}
    </div>
  );
}
