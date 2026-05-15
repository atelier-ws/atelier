import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import Traces from "./Traces";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Traces page", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("searches all sessions in place and shows surrounding match snippets", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);

        if (url.includes("/api/traces")) {
          const hasQuery = url.includes("query=timeout");
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  id: hasQuery ? "trace-timeout" : "trace-base",
                  session_id: hasQuery ? "run-timeout" : "run-base",
                  agent: "copilot",
                  host: "copilot",
                  domain: "coding",
                  task:
                    hasQuery ? "Search shell timeout" : "Baseline session",
                  status: "failed",
                  files_touched: [],
                  tools_called: [],
                  commands_run: [],
                  errors_seen: [],
                  repeated_failures: [],
                  validation_results: [],
                  created_at: "2026-05-12T00:00:00Z",
                  snippets: hasQuery
                    ? [
                        "Commands: tail deploy.log ... [[timeout]] while waiting",
                      ]
                    : [],
                },
              ],
              metrics: {
                stats: {
                  total: hasQuery ? 1 : 2,
                  success: 1,
                  failed: 1,
                  partial: 0,
                },
                hosts: ["copilot"],
                domains: ["coding"],
              },
            })
          );
        }

        return Promise.resolve(new Response("not found", { status: 404 }));
      });

    render(
      <MemoryRouter initialEntries={["/sessions"]}>
        <Routes>
          <Route path="/sessions" element={<Traces />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Baseline session")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /^copilot$/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).includes("host=copilot")
        )
      ).toBe(true);
    });

    await user.type(
      screen.getByPlaceholderText(
        /Search tasks, reasoning, tools, commands, files, validations, and summaries/i
      ),
      "timeout"
    );

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).includes("query=timeout")
        )
      ).toBe(true);
    });

    expect(await screen.findByText("Search shell timeout")).toBeInTheDocument();
    expect(screen.getByText(/run-timeout/i)).toBeInTheDocument();
    expect(screen.getByText(/Commands:/i)).toBeInTheDocument();
  });

  it("hides stale or unrelated highlighted snippets for the current search", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (input: RequestInfo | URL) => {
        const url = String(input);

        if (url.includes("/api/traces")) {
          const params = new URL(url, "http://localhost").searchParams;
          const query = params.get("query");
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  id: query ? "trace-sidecar" : "trace-base",
                  session_id: query ? "run-sidecar" : "run-base",
                  agent: "codex",
                  host: "codex",
                  domain: "coding",
                  task: query ? "Investigate sidecar session" : "Base session",
                  status: "success",
                  files_touched: [],
                  tools_called: [],
                  commands_run: [],
                  errors_seen: [],
                  repeated_failures: [],
                  validation_results: [],
                  created_at: "2026-05-12T00:00:00Z",
                  snippets: query
                    ? [
                        "Tools: [[shopify]] sync service skills",
                        "Commands: inspect [[sidecar]] process logs",
                      ]
                    : [],
                },
              ],
              metrics: {
                stats: {
                  total: 1,
                  success: 1,
                  failed: 0,
                  partial: 0,
                },
                hosts: ["codex"],
                domains: ["coding"],
              },
            })
          );
        }

        return Promise.resolve(new Response("not found", { status: 404 }));
      }
    );

    render(
      <MemoryRouter initialEntries={["/sessions"]}>
        <Routes>
          <Route path="/sessions" element={<Traces />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Base session")).toBeInTheDocument();
    });

    await user.type(
      screen.getByPlaceholderText(
        /Search tasks, reasoning, tools, commands, files, validations, and summaries/i
      ),
      "sidecar"
    );

    expect(
      await screen.findByText("Investigate sidecar session")
    ).toBeInTheDocument();
    expect(screen.getByText(/inspect/i)).toBeInTheDocument();
    expect(screen.queryByText(/shopify/i)).not.toBeInTheDocument();
  });
});
