import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Workflow from "./Workflow";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Workflow page", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the current workflow snapshot and applies pause/stop snapshot actions", async () => {
    const actionBodies: unknown[] = [];
    let detail = {
      workspace_root: "/workspace/project",
      summary: {
        run_id: "wf-123",
        workflow_id: "owned-execute-review-loop",
        status: "awaiting_review",
        current_step: "execute",
        session_phase: "review",
        step_count: 2,
        completed_steps: 1,
        paused_step_id: "execute",
        failed_step_id: "",
        pause_reason: "",
        stop_reason: "",
        review_decision: "pending",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:05:00Z",
      },
      workflow: {
        workflow_id: "owned-execute-review-loop",
        steps: [
          { step_id: "plan", kind: "agent" },
          { step_id: "execute", kind: "agent" },
        ],
      },
      route: { mode: "native" },
      current_task: {
        workflow_id: "owned-execute-review-loop",
        run_id: "wf-123",
        step_id: "execute",
      },
      plan_review: {
        decision: "pending",
        paused_step_id: "execute",
        workflow_id: "owned-execute-review-loop",
      },
      task_outputs: {
        plan: {
          step_id: "plan",
          kind: "agent",
          status: "done",
          output: "plan ready",
          output_json: {},
          execution_receipt: { mode: "native" },
          duration_seconds: 1.2,
          cost_usd: 0,
          error: "",
        },
      },
      step_order: ["plan", "execute"],
      available_actions: {
        can_pause: true,
        can_resume: true,
        can_stop: true,
        resume_requires_host_call: true,
        pause_is_snapshot_only: true,
        stop_is_snapshot_only: true,
      },
      control_payloads: {
        status: { op: "status", run_id: "wf-123" },
        pause: { op: "pause", run_id: "wf-123" },
        stop: { op: "stop", run_id: "wf-123" },
        resume_approve: {
          op: "resume",
          run_id: "wf-123",
          plan_review: { decision: "approve" },
        },
      },
      notes: {
        snapshot_kind: "workspace-current",
        live_control: false,
        summary:
          "Workflow state is a workspace-local persisted snapshot, not a historical run ledger.",
      },
    };

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/workflow/current") && !init?.method) {
        return Promise.resolve(jsonResponse(detail));
      }
      if (url.endsWith("/api/v1/workflow/current/pause")) {
        actionBodies.push(JSON.parse(String(init?.body)));
        detail = {
          ...detail,
          summary: {
            ...detail.summary,
            status: "paused",
            pause_reason: "waiting on approval",
          },
        };
        return Promise.resolve(jsonResponse(detail));
      }
      if (url.endsWith("/api/v1/workflow/current/stop")) {
        actionBodies.push(JSON.parse(String(init?.body)));
        detail = {
          ...detail,
          summary: {
            ...detail.summary,
            status: "stopped",
            stop_reason: "cancelled from ui",
          },
        };
        return Promise.resolve(jsonResponse(detail));
      }
      return Promise.resolve(new Response("not found", { status: 404 }));
    });

    render(
      <MemoryRouter>
        <Workflow />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "Workflow" })).toBeInTheDocument();
    expect(
      screen.getAllByText(/owned-execute-review-loop/i)[0]
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy approve resume/i })).toBeInTheDocument();

    await userEvent.type(
      screen.getByPlaceholderText(/optional reason/i),
      "waiting on approval"
    );
    await userEvent.click(screen.getByRole("button", { name: /pause snapshot/i }));

    await waitFor(() =>
      expect(screen.getAllByText(/^paused$/i)[0]).toBeInTheDocument()
    );

    await userEvent.clear(screen.getByPlaceholderText(/optional reason/i));
    await userEvent.type(
      screen.getByPlaceholderText(/optional reason/i),
      "cancelled from ui"
    );
    await userEvent.click(screen.getByRole("button", { name: /stop snapshot/i }));

    await waitFor(() =>
      expect(screen.getAllByText(/^stopped$/i)[0]).toBeInTheDocument()
    );
    expect(actionBodies).toEqual([
      { reason: "waiting on approval" },
      { reason: "cancelled from ui" },
    ]);
  });
});
