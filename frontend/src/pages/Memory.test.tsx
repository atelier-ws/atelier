import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Memory from "./Memory";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Memory page", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing on empty data", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/traces"))
          return Promise.resolve(jsonResponse([]));
        if (url.includes("/api/v1/memory/blocks"))
          return Promise.resolve(jsonResponse([]));
        if (url.includes("/api/v1/memory/recall")) {
          return Promise.resolve(
            jsonResponse({ passages: [], recall_id: "rec-1" }),
          );
        }
        return Promise.resolve(new Response("not found", { status: 404 }));
      });

    render(<Memory />);

    expect(await screen.findByText("Memory")).toBeInTheDocument();
    expect(
      await screen.findByText("No pinned blocks for this agent."),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalled();
  });

  it("sends expected_version and shows conflict UI on 409", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);

        if (url.includes("/api/traces")) {
          return Promise.resolve(
            jsonResponse([
              {
                id: "trace-1",
                run_id: "run-1",
                agent: "atelier:code",
                task: "task",
                status: "success",
                files_touched: [],
                tools_called: [],
                commands_run: [],
                errors_seen: [],
                repeated_failures: [],
                validation_results: [],
                created_at: new Date().toISOString(),
              },
            ]),
          );
        }

        if (
          url.includes("/api/v1/memory/blocks") &&
          (!init || init.method === undefined)
        ) {
          return Promise.resolve(
            jsonResponse([
              {
                id: "mem-1",
                agent_id: "atelier:code",
                label: "working-style",
                value: "old value",
                limit_chars: 8000,
                description: "",
                read_only: false,
                metadata: {},
                pinned: true,
                version: 3,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ]),
          );
        }

        if (url.includes("/api/v1/memory/blocks") && init?.method === "POST") {
          return Promise.resolve(
            new Response("version conflict", { status: 409 }),
          );
        }

        return Promise.resolve(new Response("not found", { status: 404 }));
      });

    render(<Memory />);

    expect(
      await screen.findAllByRole("button", {
        name: "Edit memory block working-style",
      }),
    ).toHaveLength(2);
    await user.click(
      screen.getAllByRole("button", {
        name: "Edit memory block working-style",
      })[0],
    );

    const textarea = screen.getByRole("textbox", {
      name: "Edit memory block value",
    });
    await user.clear(textarea);
    await user.type(textarea, "new value");

    await user.click(
      screen.getByRole("button", { name: "Save memory block edit" }),
    );

    await waitFor(() => {
      expect(screen.getByText(/Version conflict detected/)).toBeInTheDocument();
    });

    const postCall = fetchMock.mock.calls.find((entry) => {
      const [url, init] = entry as [RequestInfo | URL, RequestInit | undefined];
      return (
        String(url).includes("/api/v1/memory/blocks") && init?.method === "POST"
      );
    });
    expect(postCall).toBeDefined();
    const body = JSON.parse(String(postCall?.[1]?.body));
    expect(body.expected_version).toBe(3);
  });
});
