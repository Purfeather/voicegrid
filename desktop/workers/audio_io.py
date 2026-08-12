from __future__ import annotations

from pathlib import Path
from typing import Any


def write_pcm24_wav(output_path: Path, audio: Any, sample_rate: int) -> dict[str, int | float | str]:
    import numpy as np
    import soundfile as sf

    samples = audio.detach().cpu().float().numpy() if hasattr(audio, "detach") else np.asarray(audio, dtype=np.float32)
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim == 1:
        samples = samples[np.newaxis, :]
    if samples.ndim != 2 or samples.shape[0] < 1 or samples.shape[1] < 1:
        raise RuntimeError("音频形状无效。")
    if not np.isfinite(samples).all():
        raise RuntimeError("音频包含无效数值。")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, samples.T, sample_rate, format="WAV", subtype="PCM_24")
    info = sf.info(output_path)
    if info.format != "WAV" or info.subtype != "PCM_24":
        raise RuntimeError(f"WAV 写入校验失败：{info.format}/{info.subtype}")
    if info.samplerate != sample_rate or info.channels != samples.shape[0] or info.frames != samples.shape[1]:
        raise RuntimeError("WAV 的采样率、声道或帧数校验失败。")
    return {
        "path": str(output_path),
        "sample_rate": int(info.samplerate),
        "channels": int(info.channels),
        "frames": int(info.frames),
        "duration": float(info.frames / info.samplerate),
        "subtype": info.subtype,
    }
