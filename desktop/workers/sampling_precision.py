from __future__ import annotations

from functools import wraps
from typing import Any, Callable


def promote_sampling_logits_to_float32(sample_function: Callable[..., Any]) -> Callable[..., Any]:
    """Run probability filtering and multinomial sampling with FP32 logits."""

    @wraps(sample_function)
    def stable_sample_token(*args: Any, **kwargs: Any) -> Any:
        if args:
            logits, *remaining = args
            return sample_function(logits.float(), *remaining, **kwargs)
        logits = kwargs.get("logits")
        if logits is None:
            return sample_function(**kwargs)
        promoted = dict(kwargs)
        promoted["logits"] = logits.float()
        return sample_function(**promoted)

    setattr(stable_sample_token, "_voicegrid_fp32_sampling", True)
    return stable_sample_token


def install_fp32_sampling(model: Any) -> bool:
    """Patch a remote-code model module once without copying its sampling logic."""

    import importlib

    model_module = importlib.import_module(model.__class__.__module__)
    sample_function = getattr(model_module, "sample_token", None)
    if not callable(sample_function):
        return False
    if getattr(sample_function, "_voicegrid_fp32_sampling", False):
        return True
    setattr(model_module, "sample_token", promote_sampling_logits_to_float32(sample_function))
    return True
