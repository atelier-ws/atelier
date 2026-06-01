import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Swarm from "./Swarm";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Swarm page", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders swarm run detail, logs, and stop action", async () => {
    let stopped = false;
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);

        if (url.includes("/api/v1/swarm/runs/swarm-123/logs")) {
          return Promise.resolve(
            jsonResponse({
              run_id: "swarm-123",
              child_id: "wave-01-run-01",
              stderr: false,
              tail: 80,
              content: "child heartbeat",
            })
          );
        }

        if (url.includes("/api/v1/swarm/runs/swarm-123/stop")) {
          stopped = true;
          expect(init?.method).toBe("POST");
          return Promise.resolve(
            jsonResponse({
              run_id: "swarm-123",
              status: "stopped",
              mode: "continuous",
              runner_name: "claude",
              runner_model: "sonnet",
              base_ref: "HEAD",
              current_wave: 1,
              max_runs: 4,
              runs: 4,
              accepted_child_ids: ["wave-01-run-02"],
              waves: [],
              children: [],
              accepted_commits: [],
            })
          );
        }

        if (url.includes("/api/v1/swarm/runs/swarm-123")) {
          return Promise.resolve(
            jsonResponse({
              run: {
                run_id: "swarm-123",
                status: stopped ? "stopped" : "running",
                mode: "continuous",
                runner_name: "claude",
                runner_model: "sonnet",
                base_ref: "HEAD",
                base_snapshot_ref: "base-snapshot",
                integration_base_ref: "accepted-head",
                current_wave: 1,
                max_runs: 4,
                runs: 4,
                planning_mode: "bounded",
                stop_reason: stopped ? "Stopped by user." : null,
                accepted_child_ids: ["wave-01-run-02"],
                primary_winner_child_id: "wave-01-run-02",
                created_at: "2026-01-01T00:00:00Z",
                updated_at: "2026-01-01T00:05:00Z",
                waves: [],
                children: [
                  {
                    child_id: "wave-01-run-01",
                    label: "candidate-1",
                    wave_index: 1,
                    status: stopped ? "stopped" : "running",
                    worktree_path: "/tmp/swarm/worktree",
                    current_activity: "Running validation",
                    last_output_at: "2026-01-01T00:04:00Z",
                  },
                ],
                accepted_commits: [
                  {
                    order: 1,
                    child_id: "wave-01-run-02",
                    commit_ref: "abc1234",
                    patch_path: "/tmp/swarm/candidate.patch",
                    artifacts: [
                      {
                        kind: "wave-manifest",
                        label: "Wave 1 manifest",
                        path: "/tmp/swarm/wave-01-manifest.json",
                        exists: true,
                      },
                    ],
                  },
                ],
              },
              export: {
                run_id: "swarm-123",
                status: stopped ? "stopped" : "running",
                mode: "continuous",
                runner_name: "claude",
                runner_model: "sonnet",
                base_ref: "HEAD",
                base_snapshot_ref: "base-snapshot",
                integration_base_ref: "accepted-head",
                artifact_root: "/tmp/swarm/artifacts",
                base_snapshot_artifact: {
                  kind: "base-snapshot",
                  label: "Base snapshot",
                  path: "/tmp/swarm/artifacts/base-snapshot.json",
                  exists: true,
                },
                accepted_child_ids: ["wave-01-run-02"],
                accepted_commits: [
                  {
                    order: 1,
                    child_id: "wave-01-run-02",
                    commit_ref: "abc1234",
                    patch_path: "/tmp/swarm/candidate.patch",
                    artifacts: [
                      {
                        kind: "wave-manifest",
                        label: "Wave 1 manifest",
                        path: "/tmp/swarm/wave-01-manifest.json",
                        exists: true,
                      },
                    ],
                  },
                ],
                waves: [
                  {
                    wave_index: 1,
                    status: "success",
                    max_runs: 4,
                    planned_runs: 2,
                    planning_mode: "bounded",
                    primary_winner_child_id: "wave-01-run-02",
                    accepted_child_ids: ["wave-01-run-02"],
                    rejected_child_ids: ["wave-01-run-01"],
                    manifest_artifact: {
                      kind: "wave-manifest",
                      label: "Wave 1 manifest",
                      path: "/tmp/swarm/wave-01-manifest.json",
                      exists: true,
                    },
                  },
                ],
                artifacts: [
                  {
                    kind: "wave-manifest",
                    label: "Wave 1 manifest",
                    path: "/tmp/swarm/wave-01-manifest.json",
                    exists: true,
                  },
                ],
                transplant_commands: ["git cherry-pick abc1234"],
              },
              apply: {
                run_id: "swarm-123",
                wave_index: null,
                child_id: null,
                base_snapshot_ref: "base-snapshot",
                integration_base_ref: "accepted-head",
                selected_commits: [
                  {
                    order: 1,
                    child_id: "wave-01-run-02",
                    commit_ref: "abc1234",
                    patch_path: "/tmp/swarm/candidate.patch",
                    artifacts: [],
                  },
                ],
                commands: ["git cherry-pick abc1234"],
                artifacts: [],
              },
            })
          );
        }

        if (url.endsWith("/api/v1/swarm/runs")) {
          return Promise.resolve(
            jsonResponse([
              {
                run_id: "swarm-123",
                status: stopped ? "stopped" : "running",
                mode: "continuous",
                runner_name: "claude",
                runner_model: "sonnet",
                current_wave: 1,
                max_runs: 4,
                planned_runs: 2,
                planning_mode: "bounded",
                accepted_child_ids: ["wave-01-run-02"],
                primary_winner_child_id: "wave-01-run-02",
                failed_children: [],
                running_children: stopped
                  ? []
                  : [
                      {
                        child_id: "wave-01-run-01",
                        activity: "Running validation",
                        last_output_at: "2026-01-01T00:04:00Z",
                      },
                    ],
                created_at: "2026-01-01T00:00:00Z",
                updated_at: "2026-01-01T00:05:00Z",
              },
            ])
          );
        }

        return Promise.resolve(new Response("not found", { status: 404 }));
      });

    render(
      <MemoryRouter>
        <Swarm />
      </MemoryRouter>
    );

    expect(await screen.findByText("Adaptive swarm control plane")).toBeInTheDocument();
    expect(await screen.findByText("swarm-123")).toBeInTheDocument();
    expect(await screen.findByText("Running validation")).toBeInTheDocument();
    expect(await screen.findByText("git cherry-pick abc1234")).toBeInTheDocument();
    expect(await screen.findByText("child heartbeat")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /stop run/i }));

    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/swarm/runs/swarm-123/stop?cleanup=false"),
        expect.objectContaining({ method: "POST" })
      )
    );
    expect(await screen.findAllByText("stopped")).not.toHaveLength(0);
  });
});
