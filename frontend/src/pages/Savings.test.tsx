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

    expect(await screen.findByText("51.9%")).toBeInTheDocument();
    expect(await screen.findByText("Per-lever savings")).toBeInTheDocument();
    expect(await screen.findByText("Ast Truncation")).toBeInTheDocument();
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
