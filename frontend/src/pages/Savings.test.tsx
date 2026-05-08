import { render, screen } from "@testing-library/react";
import Savings from "./Savings";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Savings page", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders KPI, lever breakdown, and trend chart", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/v1/savings/summary")) {
          return Promise.resolve(
            jsonResponse({
              window_days: 14,
              total_naive_tokens: 412000,
              total_actual_tokens: 198000,
              reduction_pct: 51.9,
              per_lever: {
                ast_truncation: 27000,
                search_read: 21000,
                batch_edit: 14500,
              },
              live_calls_saved: 7,
              live_saved_usd: 0.1234,
              top_sources: [
                {
                  lever: "search_read",
                  tool_name: "search",
                  calls_saved: 4,
                  tokens_saved: 21000,
                  cost_saved_usd: 0.0833,
                  time_saved_ms: 100000,
                },
              ],
              latest_benchmark: {
                run_id: "bench-ui",
                model: "test-model",
                n_prompts: 2,
                total_tokens_baseline: 1000,
                total_tokens_atelier: 600,
                tokens_saved: 400,
                reduction_pct: 40.0,
                total_cost_baseline_usd: 0.02,
                total_cost_atelier_usd: 0.012,
                cost_saved_usd: 0.008,
                total_time_baseline_ms: 2000,
                total_time_atelier_ms: 1500,
                time_saved_ms: 500,
                baseline_success_rate: 1,
                atelier_success_rate: 1,
              },
              by_day: Array.from({ length: 14 }, (_, i) => ({
                day: `2026-04-${String(i + 10).padStart(2, "0")}`,
                naive: 30000 - i * 400,
                actual: 15000 - i * 180,
              })),
            }),
          );
        }
        return Promise.resolve(new Response("not found", { status: 404 }));
      },
    );

    render(<Savings />);

    expect(await screen.findAllByText("51.9%")).toHaveLength(2);
    expect(await screen.findByText("Per-lever savings")).toBeInTheDocument();
    expect(await screen.findByText("Top savings sources")).toBeInTheDocument();
    expect(
      await screen.findByText("Latest paired benchmark"),
    ).toBeInTheDocument();
    expect(await screen.findByText("Ast Truncation")).toBeInTheDocument();
    expect(await screen.findAllByText("Search Read")).not.toHaveLength(0);
    expect(
      await screen.findByLabelText("14-day token savings trend"),
    ).toBeInTheDocument();
  });

  it("renders coaching empty state when there is no telemetry", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/v1/savings/summary")) {
          return Promise.resolve(
            jsonResponse({
              window_days: 14,
              total_naive_tokens: 0,
              total_actual_tokens: 0,
              reduction_pct: 0,
              per_lever: {},
              by_day: Array.from({ length: 14 }, (_, i) => ({
                day: `2026-04-${String(i + 10).padStart(2, "0")}`,
                naive: 0,
                actual: 0,
              })),
            }),
          );
        }
        return Promise.resolve(new Response("not found", { status: 404 }));
      },
    );

    render(<Savings />);

    expect(
      await screen.findByText("No savings telemetry yet"),
    ).toBeInTheDocument();
    expect(await screen.findByText("atelier-mcp")).toBeInTheDocument();
  });
});
