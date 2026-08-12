from __future__ import annotations

import math
import re
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .paths import ROOT, UPLOADS_DIR


AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".ogg", ".m4a"}


def internal_audio_path(value: str | Path) -> Path:
    path = Path(value).resolve()
    root = ROOT.resolve()
    if path != root and root not in path.parents:
        raise ValueError("音频文件不在应用目录内。")
    if path.suffix.lower() not in AUDIO_SUFFIXES:
        raise ValueError("不支持的音频格式。")
    if not path.is_file():
        raise FileNotFoundError("音频文件不存在。")
    return path


def save_upload(filename: str, content: bytes) -> Path:
    suffix = Path(filename or "reference.wav").suffix.lower()
    if suffix not in AUDIO_SUFFIXES:
        raise ValueError("只支持 WAV、FLAC、MP3、OGG 和 M4A 音频。")
    stem = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", Path(filename).stem)[:48] or "reference"
    target = UPLOADS_DIR / f"{uuid.uuid4().hex}_{stem}{suffix}"
    target.write_bytes(content)
    return target


def _frame_rms(mono: np.ndarray, sample_rate: int) -> np.ndarray:
    frame = max(256, int(sample_rate * 0.05))
    hop = max(128, frame // 2)
    if len(mono) < frame:
        return np.array([float(np.sqrt(np.mean(np.square(mono)) + 1e-12))])
    count = 1 + (len(mono) - frame) // hop
    return np.array([float(np.sqrt(np.mean(np.square(mono[index * hop:index * hop + frame])) + 1e-12)) for index in range(count)])


def analyze_audio(path_value: str | Path) -> dict[str, Any]:
    path = internal_audio_path(path_value)
    audio, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
    if audio.size == 0:
        raise ValueError("音频为空。")
    mono = np.mean(audio, axis=1)
    duration = len(mono) / float(sample_rate)
    peak = float(np.max(np.abs(mono)))
    clipping_ratio = float(np.mean(np.abs(mono) >= 0.999))
    rms = float(np.sqrt(np.mean(np.square(mono)) + 1e-12))
    rms_dbfs = 20.0 * math.log10(max(rms, 1e-9))
    frames = _frame_rms(mono, sample_rate)
    frames_db = 20.0 * np.log10(np.maximum(frames, 1e-9))
    silence_ratio = float(np.mean(frames_db < -45.0))
    active = frames[frames_db >= -45.0]
    if len(active) >= 4:
        signal = float(np.percentile(active, 85))
        noise = float(np.percentile(active, 15))
        snr = 20.0 * math.log10(max(signal, 1e-9) / max(noise, 1e-9))
    else:
        snr = 0.0

    score = 100
    findings: list[dict[str, str]] = []
    if duration < 2.0:
        score -= 28
        findings.append({"level": "error", "message": "参考音频过短，建议保留完整句子和自然停连。"})
    elif duration > 45.0:
        score -= 12
        findings.append({"level": "warning", "message": "参考音频较长，建议裁取更集中、干净的代表片段。"})
    if clipping_ratio > 0.001:
        score -= 26
        findings.append({"level": "error", "message": "检测到削波，可能降低音色克隆的自然度。"})
    if snr < 12:
        score -= 24
        findings.append({"level": "error", "message": "信噪比较低，建议降噪或更换录音。"})
    elif snr < 20:
        score -= 10
        findings.append({"level": "warning", "message": "存在可感知底噪，仍可试用。"})
    if silence_ratio > 0.45:
        score -= 14
        findings.append({"level": "warning", "message": "静音占比较高，建议收紧有效语音范围。"})
    if peak < 0.08:
        score -= 12
        findings.append({"level": "warning", "message": "录音电平偏低。"})
    if sample_rate < 22050:
        score -= 10
        findings.append({"level": "warning", "message": "采样率偏低，细节可能不足。"})
    if not findings:
        findings.append({"level": "success", "message": "时长、电平、静音和噪声指标适合用于音色克隆。"})

    score = max(0, min(100, score))
    points = min(520, len(mono))
    edges = np.linspace(0, len(mono), points + 1, dtype=int)
    waveform = [float(np.max(np.abs(mono[edges[index]:max(edges[index + 1], edges[index] + 1)]))) for index in range(points)]
    return {
        "duration": round(duration, 3),
        "sample_rate": int(sample_rate),
        "channels": int(audio.shape[1]),
        "peak_dbfs": round(20.0 * math.log10(max(peak, 1e-9)), 2),
        "rms_dbfs": round(rms_dbfs, 2),
        "clipping_ratio": round(clipping_ratio * 100.0, 4),
        "snr_db": round(snr, 2),
        "silence_ratio": round(silence_ratio * 100.0, 2),
        "score": score,
        "suitability": "适合克隆" if score >= 78 else ("建议处理后使用" if score >= 55 else "不建议直接使用"),
        "findings": findings,
        "waveform": waveform,
    }


def prepare_trimmed_reference(path_value: str | Path, start: float, end: float | None) -> Path:
    path = internal_audio_path(path_value)
    if start <= 0 and end is None:
        return path
    audio, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
    start_frame = max(0, min(len(audio), int(start * sample_rate)))
    end_frame = len(audio) if end is None else max(start_frame + 1, min(len(audio), int(end * sample_rate)))
    target = UPLOADS_DIR / f"trim_{uuid.uuid4().hex}.wav"
    sf.write(str(target), audio[start_frame:end_frame], sample_rate, subtype="PCM_24")
    return target
