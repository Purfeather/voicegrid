from __future__ import annotations

from functools import wraps
from typing import Any, Callable


def validate_sampleable_logits(logits: Any) -> None:
    """Fail clearly before CUDA multinomial when a model emits no valid row."""

    if not hasattr(logits, "numel"):
        return
    if int(logits.numel()) == 0:
        # The official generator legitimately calls the sampler with a
        # ``0 x vocab`` tensor when no delayed audio channel is due on the
        # current step.  PyTorch returns an empty sample for that shape and
        # the masked assignment is a no-op.  Only a missing vocabulary is an
        # invalid distribution.
        dimensions = int(logits.dim()) if hasattr(logits, "dim") else 0
        vocabulary_size = int(logits.size(-1)) if dimensions else 0
        if dimensions >= 2 and vocabulary_size > 0:
            return
        raise RuntimeError("模型输出了空的采样分布。")
    import torch

    flattened = logits.reshape(-1, logits.size(-1))
    nan_count = int(torch.isnan(flattened).sum().item())
    positive_inf_count = int(torch.isposinf(flattened).sum().item())
    finite_per_row = torch.isfinite(flattened).any(dim=-1)
    invalid_rows = int((~finite_per_row).sum().item())
    if nan_count or positive_inf_count or invalid_rows:
        raise RuntimeError(
            "模型输出的采样分布无效："
            f"NaN={nan_count}，正无穷={positive_inf_count}，无有限候选行={invalid_rows}。"
        )


def promote_sampling_logits_to_float32(sample_function: Callable[..., Any]) -> Callable[..., Any]:
    """Run probability filtering and multinomial sampling with FP32 logits."""

    @wraps(sample_function)
    def stable_sample_token(*args: Any, **kwargs: Any) -> Any:
        if args:
            logits, *remaining = args
            promoted_logits = logits.float()
            validate_sampleable_logits(promoted_logits)
            return sample_function(promoted_logits, *remaining, **kwargs)
        logits = kwargs.get("logits")
        if logits is None:
            return sample_function(**kwargs)
        promoted = dict(kwargs)
        promoted["logits"] = logits.float()
        validate_sampleable_logits(promoted["logits"])
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
