import type { TaskRecord } from "../types";

const TERMINAL_STATUSES = new Set<TaskRecord["status"]>(["completed", "failed", "cancelled"]);

function timestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function shouldReplace(current: TaskRecord, incoming: TaskRecord): boolean {
  const currentTime = timestamp(current.updated_at);
  const incomingTime = timestamp(incoming.updated_at);
  if (incomingTime !== currentTime) return incomingTime > currentTime;
  if (TERMINAL_STATUSES.has(current.status) && !TERMINAL_STATUSES.has(incoming.status)) return false;
  return true;
}

export function upsertTask(tasks: TaskRecord[], task: TaskRecord): TaskRecord[] {
  const existing = tasks.find((item) => item.id === task.id);
  const next = existing && !shouldReplace(existing, task) ? existing : task;
  return [next, ...tasks.filter((item) => item.id !== task.id)]
    .sort((left, right) => right.created_at.localeCompare(left.created_at));
}

export function mergeTaskList(tasks: TaskRecord[], incoming: TaskRecord[], projectId: string, module: TaskRecord["module"]): TaskRecord[] {
  const scoped = tasks.filter((task) => task.project_id === projectId && task.module === module);
  return incoming.reduce((merged, task) => upsertTask(merged, task), scoped);
}
