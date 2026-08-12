import { describe, expect, it } from "vitest";
import { splitText } from "./text";

describe("splitText", () => {
  it("updates from pasted text and respects the configured limit", () => {
    const text = "第一句用于测试。第二句继续测试。第三句也需要完整保留。";
    const segments = splitText(text, 20);
    expect(segments.length).toBeGreaterThan(1);
    expect(segments.every((segment) => segment.length <= 20)).toBe(true);
  });
});
