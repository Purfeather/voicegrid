import { describe, expect, it, vi } from "vitest";
import { flushActiveProjectForExit, registerExitSaveHandler } from "./exitCoordinator";

describe("exit coordinator", () => {
  it("flushes the active workspace before exit", async () => {
    const handler = vi.fn(async () => undefined);
    const unregister = registerExitSaveHandler(handler);
    await flushActiveProjectForExit();
    expect(handler).toHaveBeenCalledTimes(1);
    unregister();
  });

  it("only keeps the latest mounted workspace handler", async () => {
    const oldHandler = vi.fn(async () => undefined);
    const currentHandler = vi.fn(async () => undefined);
    const unregisterOld = registerExitSaveHandler(oldHandler);
    const unregisterCurrent = registerExitSaveHandler(currentHandler);
    unregisterOld();
    await flushActiveProjectForExit();
    expect(oldHandler).not.toHaveBeenCalled();
    expect(currentHandler).toHaveBeenCalledTimes(1);
    unregisterCurrent();
  });
});
