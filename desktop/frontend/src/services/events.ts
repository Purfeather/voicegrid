import type { AppEvent } from "../types";

export function subscribeEvents(onEvent: (event: AppEvent) => void): () => void {
  const source = new EventSource("/api/v2/events");
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as AppEvent);
    } catch {
      // Ignore malformed local events and keep the stream alive.
    }
  };
  return () => source.close();
}
