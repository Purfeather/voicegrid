import { describe, expect, it } from "vitest";
import { countSpokenCharacters, insertPauseMarker, PAUSE_MARKER, splitText } from "./text";

describe("splitText", () => {
  it("updates from pasted text and respects the configured limit", () => {
    const text = "第一句用于测试。第二句继续测试。第三句也需要完整保留。";
    const segments = splitText(text, 20);
    expect(segments.length).toBeGreaterThan(1);
    expect(segments.every((segment) => segment.length <= 20)).toBe(true);
  });

  it("keeps native pause markers intact without making them standalone segments", () => {
    const text = `第一段很长的台词${PAUSE_MARKER}第二段继续说话。`;
    const segments = splitText(text, 20);
    expect(segments.join("")).toBe(text);
    expect(segments.filter((segment) => segment.includes(PAUSE_MARKER))).toHaveLength(1);
    expect(segments).not.toContain(PAUSE_MARKER);
    expect(countSpokenCharacters(text)).toBe("第一段很长的台词第二段继续说话。".length);
  });

  it("inserts a one-second marker at the requested cursor or at the end", () => {
    expect(insertPauseMarker("前后", 1)).toEqual({ value: `前${PAUSE_MARKER}后`, cursor: 1 + PAUSE_MARKER.length });
    expect(insertPauseMarker("台词", null)).toEqual({ value: `台词${PAUSE_MARKER}`, cursor: 2 + PAUSE_MARKER.length });
  });
});
