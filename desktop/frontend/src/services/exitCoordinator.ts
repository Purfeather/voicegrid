type ExitSaveHandler = () => Promise<void>;

let activeHandler: ExitSaveHandler | null = null;

export function registerExitSaveHandler(handler: ExitSaveHandler): () => void {
  activeHandler = handler;
  return () => {
    if (activeHandler === handler) activeHandler = null;
  };
}

export async function flushActiveProjectForExit(): Promise<void> {
  await activeHandler?.();
}
