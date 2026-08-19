import type { AppEvent } from "../types";

type EventListener = (event: AppEvent) => void;

let source: EventSource | null = null;
const listeners = new Set<EventListener>();

function ensureSource() {
  if (source || typeof EventSource === "undefined") return;
  source = new EventSource("/api/v2/events");
  source.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data) as AppEvent;
      for (const listener of listeners) listener(event);
    } catch {
      // Ignore malformed local events and keep the stream alive.
    }
  };
}

export function subscribeEvents(onEvent: (event: AppEvent) => void): () => void {
  listeners.add(onEvent);
  ensureSource();
  return () => {
    listeners.delete(onEvent);
    if (!listeners.size && source) {
      source.close();
      source = null;
    }
  };
}
