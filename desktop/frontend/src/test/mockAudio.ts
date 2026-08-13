import { vi } from "vitest";

export class MockAudio {
  static instances: MockAudio[] = [];

  currentTime = 0;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  pause = vi.fn();
  play = vi.fn(() => Promise.resolve());

  constructor(public readonly src: string) {
    MockAudio.instances.push(this);
  }

  static install() {
    MockAudio.instances = [];
    vi.stubGlobal("Audio", MockAudio);
  }
}
