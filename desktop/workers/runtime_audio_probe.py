from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

try:
    from .audio_io import write_pcm24_wav
except ImportError:  # Direct execution by an isolated optional runtime.
    from audio_io import write_pcm24_wav


def probe_pcm24(directory: Path | None = None) -> dict[str, int | str]:
    import numpy as np
    import soundfile as sf

    sample_rate = 24_000
    channels = 1
    frames = sample_rate
    timeline = np.arange(frames, dtype=np.float32) / sample_rate
    audio = (0.1 * np.sin(2.0 * np.pi * 220.0 * timeline)).astype(np.float32)

    if directory is None:
        with tempfile.TemporaryDirectory(prefix="voicegrid-audio-probe-") as temporary:
            return probe_pcm24(Path(temporary))

    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "pcm24-probe.wav"
    try:
        write_pcm24_wav(target, audio, sample_rate)
        info = sf.info(target)
        decoded, decoded_rate = sf.read(target, dtype="float32", always_2d=True)
        if info.format != "WAV" or info.subtype != "PCM_24":
            raise RuntimeError(f"WAV probe format mismatch: {info.format}/{info.subtype}")
        if info.samplerate != sample_rate or decoded_rate != sample_rate:
            raise RuntimeError("WAV probe sample rate mismatch")
        if info.channels != channels or decoded.shape != (frames, channels):
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(probe_pcm24(args.directory), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
