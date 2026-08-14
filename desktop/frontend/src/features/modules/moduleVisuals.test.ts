import { describe, expect, it } from "vitest";
import { MODULE_ORDER, MODULE_VISUALS } from "./moduleVisuals";

describe("module visuals registry", () => {
  it("defines the shared production metadata for every module", () => {
    expect(MODULE_ORDER).toEqual(["speech", "voice_design", "sound_effect"]);
    for (const id of MODULE_ORDER) {
      const visual = MODULE_VISUALS[id];
      expect(visual.path).toBeTruthy();
      expect(visual.fallbackName).toBeTruthy();
      expect(visual.assetLabel).toBeTruthy();
      expect(visual.emptyOutputTitle).toBeTruthy();
      expect(visual.emptyActivityTitle).toBeTruthy();
      expect(visual.installEyebrow).toBe("MODULE STATUS");
    }
  });
});
