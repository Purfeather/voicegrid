"""Compatibility imports for the relocated speech inference engine."""

from desktop.inference.model_engine import ENGINE, PAUSE_MARKER_PATTERN, ModelEngine, TaskCancelled, split_text

__all__ = ["ENGINE", "PAUSE_MARKER_PATTERN", "ModelEngine", "TaskCancelled", "split_text"]
