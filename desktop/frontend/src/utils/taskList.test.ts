import { describe, expect, it } from "vitest";
import type { TaskRecord } from "../types";
import { mergeTaskList, upsertTask } from "./taskList";

function task(id: string, createdAt: string): TaskRecord {
  return { id, project_id: "project", module: "speech", status: "queued", progress: 0, message: "", created_at: createdAt, updated_at: createdAt, result_id: null, error: null, remove_after_stop: false };
}

describe("upsertTask", () => {
  it("replaces an existing task instead of duplicating it", () => {
    const first = task("a", "2026-08-14T10:00:00");
    const updated = { ...first, status: "running" as const, progress: 0.5 };
    expect(upsertTask([first], updated)).toEqual([updated]);
  });

  it("keeps newest tasks first", () => {
    expect(upsertTask([task("old", "2026-08-14T10:00:00")], task("new", "2026-08-14T10:01:00")).map((item) => item.id)).toEqual(["new", "old"]);
  });

  it("does not let an older active response overwrite a completed event", () => {
    const completed = { ...task("a", "2026-08-14T10:00:00"), status: "completed" as const, progress: 1, updated_at: "2026-08-14T10:02:00" };
    const stale = { ...task("a", "2026-08-14T10:00:00"), status: "running" as const, progress: 0.8, updated_at: "2026-08-14T10:01:00" };
    expect(mergeTaskList([completed], [stale], "project", "speech")).toEqual([completed]);
  });

  it("keeps task state scoped to the current project and module", () => {
    const oldProject = { ...task("old", "2026-08-14T10:00:00"), project_id: "other" };
    const currentProject = { ...task("new", "2026-08-14T10:01:00"), project_id: "project" };
    expect(mergeTaskList([oldProject], [currentProject], "project", "speech")).toEqual([currentProject]);
  });
});