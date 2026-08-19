from __future__ import annotations

import json
import queue
import threading
from contextlib import contextmanager
from typing import Any, Iterator


TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled"})


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

    @staticmethod
    def _is_critical(event: dict[str, Any]) -> bool:
        event_type = event.get("type")
        if event_type in {"task.removed", "activity.cleared"}:
            return True
        if event_type == "task.updated":
            payload = event.get("payload")
            return isinstance(payload, dict) and payload.get("status") in TERMINAL_TASK_STATUSES
        return False

    @classmethod
    def _put_with_priority(cls, target: queue.Queue, event: dict[str, Any]) -> None:
        try:
            target.put_nowait(event)
            return
        except queue.Full:
            pass

        buffered: list[dict[str, Any]] = []
        while True:
            try:
                buffered.append(target.get_nowait())
            except queue.Empty:
                break

        drop_index = next(
            (index for index, queued in enumerate(buffered) if not cls._is_critical(queued)),
            None,
        )
        if drop_index is None:
            if not cls._is_critical(event):
                for queued in buffered:
                    target.put_nowait(queued)
                return
            drop_index = 0

        buffered.pop(drop_index)
        for queued in buffered:
            target.put_nowait(queued)
        target.put_nowait(event)

    def publish(self, event_type: str, payload: Any) -> None:
        event = {"type": event_type, "payload": payload}
        with self.lock:
            for target in tuple(self.subscribers):
                self._put_with_priority(target, event)

    @staticmethod
    def encode(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

EVENTS = EventBroker()
