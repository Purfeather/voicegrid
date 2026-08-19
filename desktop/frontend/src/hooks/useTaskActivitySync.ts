import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import type { ModuleId, TaskRecord } from "../types";
import { subscribeEvents } from "../services/events";
import { upsertTask } from "../utils/taskList";

const TERMINAL_STATUSES = new Set<TaskRecord["status"]>(["completed", "failed", "cancelled"]);
const RECONCILE_INTERVAL_MS = 2000;

interface Options {
  projectId: string;
  module: ModuleId;
  tasks: TaskRecord[];
  setTasks: Dispatch<SetStateAction<TaskRecord[]>>;
  reconcile: () => Promise<void>;
}

export function useTaskActivitySync({ projectId, module, tasks, setTasks, reconcile }: Options): void {
  const reconcileRef = useRef(reconcile);

  useEffect(() => {
    reconcileRef.current = reconcile;
  }, [reconcile]);

  useEffect(() => subscribeEvents((event) => {
    if (event.type === "task.updated") {
      const task = event.payload as TaskRecord;
      if (task.project_id !== projectId || task.module !== module) return;
      setTasks((current) => upsertTask(current, task));
      if (TERMINAL_STATUSES.has(task.status)) {
        window.setTimeout(() => {
          void reconcileRef.current().catch(() => undefined);
        }, 0);
      }
      return;
    }

    if (event.type === "task.removed") {
      const removed = event.payload as { id: string; project_id: string; module?: ModuleId };
      if (removed.project_id === projectId && (!removed.module || removed.module === module)) {
        setTasks((current) => current.filter((task) => task.id !== removed.id));
      }
      return;
    }

    if (event.type === "activity.cleared") {
      const cleared = event.payload as { project_id?: string; module?: ModuleId };
      if (cleared.project_id === projectId && (!cleared.module || cleared.module === module)) {
        setTasks((current) => current.filter((task) => task.status === "queued" || task.status === "running"));
      }
    }
  }), [module, projectId, setTasks]);

  const hasActiveTask = tasks.some((task) => task.status === "queued" || task.status === "running");

  useEffect(() => {
    if (!hasActiveTask) return;

    let disposed = false;
    let inFlight = false;

    const run = async () => {
      if (disposed || inFlight) return;
      inFlight = true;
      try {
        await reconcileRef.current();
      } catch {
        // The next interval retries a transient API failure.
      } finally {
        inFlight = false;
      }
    };

    const timer = window.setInterval(() => {
      void run();
    }, RECONCILE_INTERVAL_MS);

    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [hasActiveTask, module, projectId]);
}
