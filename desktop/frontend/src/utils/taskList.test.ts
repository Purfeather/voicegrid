import { describe, expect, it } from "vitest";
import type { TaskRecord } from "../types";
import { upsertTask } from "./taskList";

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
});