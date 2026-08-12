from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .paths import RAW_OUTPUTS_DIR


def _safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" ._")
    return value[:160] or f"voice_{datetime.now():%Y%m%d_%H%M%S}"


def _resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return audio
    divisor = math.gcd(source_rate, target_rate)
    return resample_poly(audio, target_rate // divisor, source_rate // divisor, axis=0).astype(np.float32)


def _channels(audio: np.ndarray, count: int) -> np.ndarray:
    if audio.ndim == 1:
        audio = audio[:, None]
    if count == 1:
        return np.mean(audio, axis=1, keepdims=True)
    if audio.shape[1] == 1:
        return np.repeat(audio, 2, axis=1)
    return audio[:, :2]


def _normalize_loudness(audio: np.ndarray, sample_rate: int, target_lufs: float | None) -> tuple[np.ndarray, float | None]:
    if target_lufs is None or len(audio) < int(sample_rate * 0.45):
        return audio, None
    import pyloudnorm as pyln

    meter = pyln.Meter(sample_rate)
    measured = float(meter.integrated_loudness(audio[:, 0] if audio.shape[1] == 1 else audio))
    normalized = pyln.normalize.loudness(audio, measured, float(target_lufs))
    peak = float(np.max(np.abs(normalized)))
    ceiling = 10 ** (-1.0 / 20.0)
    if peak > ceiling:
        normalized *= ceiling / peak
    return normalized.astype(np.float32), measured


class _SafeTemplate(dict):
    def __missing__(self, key: str) -> str:
        return "_" + key + "_"


def render_output(source_path: str, profile: dict[str, Any], project_name: str, voice_name: str, index: int) -> dict[str, Any]:
    source = Path(source_path).resolve()
    if RAW_OUTPUTS_DIR.resolve() not in source.parents:
        raise ValueError("模型临时输出不在受控目录内。")
    audio, source_rate = sf.read(str(source), always_2d=True, dtype="float32")
    target_rate = int(profile.get("sample_rate", 48000))
    target_channels = int(profile.get("channels", 1))
    processed = _channels(_resample(audio, source_rate, target_rate), target_channels)
    processed, measured_lufs = _normalize_loudness(processed, target_rate, profile.get("loudness_lufs"))

    output_format = str(profile.get("format", "WAV")).upper()
    extension = ".flac" if output_format == "FLAC" else ".wav"
    output_directory = Path(profile["output_directory"]).expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    template = str(profile.get("filename_template") or "{project}_{voice}_{index}_{date}")
    filename = template.format_map(_SafeTemplate(project=_safe_filename(project_name), voice=_safe_filename(voice_name), index=f"{index:03d}", date=f"{datetime.now():%Y%m%d_%H%M%S}"))
    target = output_directory / f"{_safe_filename(filename)}{extension}"
    requested_depth = int(profile.get("bit_depth", 24))
    bit_depth = 24 if extension == ".flac" and requested_depth == 32 else requested_depth
    subtype = "PCM_24" if bit_depth == 24 else ("FLOAT" if bit_depth == 32 else "PCM_16")
    sf.write(str(target), processed, target_rate, subtype=subtype)
    metadata = {
        "path": str(target),
        "filename": target.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "duration": round(len(processed) / target_rate, 3),
        "sample_rate": target_rate,
        "channels": target_channels,
        "bit_depth": bit_depth,
        "format": output_format,
        "target_lufs": profile.get("loudness_lufs"),
        "source_lufs": None if measured_lufs is None else round(measured_lufs, 2),
    }
    target.with_suffix(target.suffix + ".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    source.unlink(missing_ok=True)
    return metadata
