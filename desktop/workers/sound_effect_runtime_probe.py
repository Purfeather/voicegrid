from __future__ import annotations

import json
import tempfile
from pathlib import Path


def probe_sound_effect_runtime(directory: Path | None = None) -> dict[str, int | str]:
    import numpy as np
    import soundfile as sf

    sample_rate = 48_000
    frames = sample_rate
    timeline = np.arange(frames, dtype=np.float32) / sample_rate
    audio = (0.1 * np.sin(2.0 * np.pi * 440.0 * timeline)).astype(np.float32)
    if directory is None:
        with tempfile.TemporaryDirectory(prefix="voicegrid-sound-effect-probe-") as temporary:
            return probe_sound_effect_runtime(Path(temporary))
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "sound-effect-48khz-probe.wav"
    try:
        sf.write(target, audio, sample_rate, format="WAV", subtype="PCM_24")
        info = sf.info(target)
        decoded, decoded_rate = sf.read(target, dtype="float32", always_2d=True)
        if info.format != "WAV" or info.subtype != "PCM_24":
            raise RuntimeError(f"WAV probe format mismatch: {info.format}/{info.subtype}")
        if info.samplerate != sample_rate or decoded_rate != sample_rate:
            raise RuntimeError("WAV probe sample rate mismatch")
        if info.channels != 1 or decoded.shape != (frames, 1):
            raise RuntimeError("WAV probe channel or frame count mismatch")
        if not np.isfinite(decoded).all() or float(np.max(np.abs(decoded))) <= 0.0:
            raise RuntimeError("WAV probe decoded invalid samples")
        return {
            "format": info.format,
            "subtype": info.subtype,
            "sample_rate": int(info.samplerate),
            "channels": int(info.channels),
            "frames": int(info.frames),
        }
    finally:
        target.unlink(missing_ok=True)


if __name__ == "__main__":
    print(json.dumps(probe_sound_effect_runtime(), ensure_ascii=True))
