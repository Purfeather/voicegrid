from __future__ import annotations

import json
import queue
import threading
from contextlib import contextmanager
from typing import Any, Iterator


class EventBroker:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.subscribers: set[queue.Queue] = set()

    @contextmanager
    def subscribe(self) -> Iterator[queue.Queue]:
        target: queue.Queue = queue.Queue(maxsize=128)
        with self.lock:
            self.subscribers.add(target)
        try:
            yield target
        finally:
            with self.lock:
                self.subscribers.discard(target)

    def publish(self, event_type: str, payload: Any) -> None:
        event = {"type": event_type, "payload": payload}
        with self.lock:
            subscribers = tuple(self.subscribers)
        for target in subscribers:
            try:
                target.put_nowait(event)
            except queue.Full:
                try:
                    target.get_nowait()
                    target.put_nowait(event)
                except queue.Empty:
                    pass

    @staticmethod
    def encode(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


EVENTS = EventBroker()
