import { groupTurns } from "./helpers";

describe("groupTurns", () => {
  it("does not collapse consecutive file_edit turns that touch different files", () => {
    const turns = [
      {
        kind: "file_edit",
        at: "2026-01-01T00:00:00Z",
        summary: "Edited a.ts",
        tool_name: "edit",
        path: "src/a.ts",
        diff: "diff-a",
      },
      {
        kind: "file_edit",
        at: "2026-01-01T00:00:01Z",
        summary: "Edited b.ts",
        tool_name: "edit",
        path: "src/b.ts",
        diff: "diff-b",
      },
    ];

    const grouped = groupTurns(turns);

    expect(grouped).toHaveLength(2);
    expect(grouped[0].path).toBe("src/a.ts");
    expect(grouped[0].diff).toBe("diff-a");
    expect(grouped[1].path).toBe("src/b.ts");
    expect(grouped[1].diff).toBe("diff-b");
  });

  it("still collapses consecutive same-tool edits on the same file", () => {
    const turns = [
      {
        kind: "file_edit",
        at: "2026-01-01T00:00:00Z",
        summary: "Edited a.ts",
        tool_name: "edit",
        path: "src/a.ts",
      },
      {
        kind: "file_edit",
        at: "2026-01-01T00:00:01Z",
        summary: "Edited a.ts again",
        tool_name: "edit",
        path: "src/a.ts",
      },
    ];

    const grouped = groupTurns(turns);

    expect(grouped).toHaveLength(1);
    expect(grouped[0].count).toBe(2);
  });

  it("still collapses consecutive same-tool turns that have no path field", () => {
    const turns = [
      {
        kind: "tool_call",
        at: "2026-01-01T00:00:00Z",
        summary: "Called read",
        tool_name: "read",
      },
      {
        kind: "tool_call",
        at: "2026-01-01T00:00:01Z",
        summary: "Called read again",
        tool_name: "read",
      },
    ];

    const grouped = groupTurns(turns);

    expect(grouped).toHaveLength(1);
    expect(grouped[0].count).toBe(2);
  });
});
