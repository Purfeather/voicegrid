import { afterEach, describe, expect, it } from "vitest";
import { subscribeEvents } from "./events";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  emit(event: { type: string; payload: unknown }) {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent<string>);
  }
}

const eventSourceGlobal = globalThis as typeof globalThis & {
  EventSource?: typeof EventSource;
};
const originalEventSource = eventSourceGlobal.EventSource;

afterEach(() => {
  eventSourceGlobal.EventSource = originalEventSource;
  FakeEventSource.instances = [];
});

describe("subscribeEvents", () => {
  it("fans out one SSE connection to all workbench listeners", () => {
    eventSourceGlobal.EventSource = FakeEventSource as unknown as typeof EventSource;
    const receivedA: unknown[] = [];
    const receivedB: unknown[] = [];
    const unsubscribeA = subscribeEvents((event) => receivedA.push(event));
    const unsubscribeB = subscribeEvents((event) => receivedB.push(event));
    const source = FakeEventSource.instances[0];

    source.emit({ type: "task.updated", payload: { id: "task-1", status: "completed" } });
    source.emit({ type: "runtime.updated", payload: { state: "idle" } });

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(receivedA).toHaveLength(2);
    expect(receivedB).toHaveLength(2);

    unsubscribeA();
    unsubscribeB();
    expect(source.closed).toBe(true);
  });
});
