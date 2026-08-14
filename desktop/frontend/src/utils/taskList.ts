import type { TaskRecord } from "../types";

export function upsertTask(tasks: TaskRecord[], task: TaskRecord): TaskRecord[] {
  return [task, ...tasks.filter((item) => item.id !== task.id)]
    .sort((left, right) => right.created_at.localeCompare(left.created_at));
}