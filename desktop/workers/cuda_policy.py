from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SdpaPolicy:
    flash: bool
    memory_efficient: bool
    math: bool
    label: str


@dataclass(frozen=True)
class VoiceGeneratorPrecisionPolicy:
    model_dtype: str
    projection_dtype: str
    sampling_dtype: str
    attention_backend: str
    runtime_label: str
    reason: str


def sdpa_policy(capability: tuple[int, int]) -> SdpaPolicy:
    """Prefer FP32-accumulating math SDPA on pre-Ampere NVIDIA GPUs."""

    if int(capability[0]) < 8:
        return SdpaPolicy(flash=False, memory_efficient=False, math=True, label="sdpa-math")
    return SdpaPolicy(flash=True, memory_efficient=True, math=True, label="sdpa")


def voice_generator_precision_policy(
    capability: tuple[int, int],
    native_bf16: bool,
) -> VoiceGeneratorPrecisionPolicy:
    """Select the smallest stable precision supported by the GPU generation."""

    attention = sdpa_policy(capability).label
    if int(capability[0]) >= 8 and native_bf16:
        model_dtype = "bfloat16"
        reason = "Ampere-or-newer GPU uses the model's official native BF16 CUDA precision."
    else:
        model_dtype = "float32"
        reason = "Pre-Ampere GPUs use FP32 because VoiceGenerator emits NaN logits in FP16."
    return VoiceGeneratorPrecisionPolicy(
        model_dtype=model_dtype,
        projection_dtype=model_dtype,
        sampling_dtype="float32",
        attention_backend=attention,
        runtime_label=f"{model_dtype}-model+float32-sampling+{attention}",
        reason=reason,
    )


def configure_sdpa(torch_module: Any, capability: tuple[int, int]) -> SdpaPolicy:
    policy = sdpa_policy(capability)
    torch_module.backends.cuda.enable_cudnn_sdp(False)
    torch_module.backends.cuda.enable_flash_sdp(policy.flash)
    torch_module.backends.cuda.enable_mem_efficient_sdp(policy.memory_efficient)
    torch_module.backends.cuda.enable_math_sdp(policy.math)
    allow_reduced_precision = getattr(torch_module.backends.cuda, "allow_fp16_bf16_reduction_math_sdp", None)
    if callable(allow_reduced_precision):
        allow_reduced_precision(False)
    return policy
