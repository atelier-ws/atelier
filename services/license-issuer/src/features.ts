export const PRO_FEATURES = [
  "code_search",
  "context_engine",
  "source_projection",
  "unlimited_repos",
  "session_recall",
  "cross_vendor_memory",
  "reasoning_library",
  "optimizer",
  "savings_dashboard",
  "context_compression",
  "prefix_cache",
  "scoped_context",
  "budget_optimizer",
  "model_routing",
  "cross_vendor_routing",
  "swarm",
];

const ENTERPRISE_FEATURES = ["large_repo", "shared_context", "governance"];

export function featuresForPlan(plan: string): string[] {
  return plan === "enterprise"
    ? [...PRO_FEATURES, ...ENTERPRISE_FEATURES]
    : PRO_FEATURES;
}
