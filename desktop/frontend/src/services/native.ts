import type { StartupStatus } from "../types";
import { flushActiveProjectForExit } from "./exitCoordinator";

type NativeBridge = {
  window_action?: (action: string) => Promise<string> | string;
  select_folder?: (initial: string) => Promise<string | null> | string | null;
  open_folder?: (path: string) => Promise<boolean> | boolean;
  startup_status?: () => Promise<StartupStatus> | StartupStatus;
  continue_waiting?: () => Promise<StartupStatus> | StartupStatus;
  retry_startup?: () => Promise<StartupStatus> | StartupStatus;
  open_log_folder?: () => Promise<boolean> | boolean;
  frontend_ready?: () => Promise<StartupStatus> | StartupStatus;
  frontend_event?: (event: string, message: string) => Promise<boolean> | boolean;
  exit_save_completed?: (success: boolean) => Promise<boolean> | boolean;
};

declare global {
  interface Window {
    pywebview?: { api?: NativeBridge };
  }
}

window.addEventListener("voicegrid:exit-requested", () => {
  void (async () => {
    let success = true;
    try {
      await flushActiveProjectForExit();
    } catch {
      success = false;
    }
    await window.pywebview?.api?.exit_save_completed?.(success);
  })();
});

async function waitForBridge(timeoutMs = 3000): Promise<NativeBridge | null> {
  if (window.pywebview?.api) return window.pywebview.api;
  const started = performance.now();
  return new Promise((resolve) => {
    const check = () => {
      if (window.pywebview?.api) { resolve(window.pywebview.api); return; }
      if (performance.now() - started >= timeoutMs) { resolve(null); return; }
      window.setTimeout(check, 25);
    };
    check();
  });
}

export async function windowAction(action: "minimize" | "maximize" | "hide" | "exit"): Promise<void> {
  if (window.pywebview?.api?.window_action) {
    await window.pywebview.api.window_action(action);
    return;
  }
  await fetch(`/api/v2/desktop/action/${action}`, { method: "POST" }).catch(() => undefined);
}

export async function selectFolder(initial = ""): Promise<string | null> {
  return (await window.pywebview?.api?.select_folder?.(initial)) ?? null;
}

export async function openFolder(path: string): Promise<boolean> {
  return (await window.pywebview?.api?.open_folder?.(path)) ?? false;
}

export async function startupStatus(): Promise<StartupStatus | null> {
  return (await (await waitForBridge())?.startup_status?.()) ?? null;
}

export async function continueWaiting(): Promise<StartupStatus | null> {
  return (await (await waitForBridge())?.continue_waiting?.()) ?? null;
}

export async function retryStartup(): Promise<StartupStatus | null> {
  return (await (await waitForBridge())?.retry_startup?.()) ?? null;
}

export async function openLogFolder(): Promise<boolean> {
  return (await (await waitForBridge())?.open_log_folder?.()) ?? false;
}

export async function notifyFrontendReady(): Promise<void> {
  await (await waitForBridge(5000))?.frontend_ready?.();
}

export async function reportStartupEvent(event: string, message: string): Promise<void> {
  await (await waitForBridge())?.frontend_event?.(event, message);
}
