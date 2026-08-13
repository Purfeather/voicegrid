from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import (
    MOSS_CODEC_DIR,
    MOSS_MODEL_DIR,
    ROOT,
    SOUND_EFFECT_MODEL_DIR,
    SOUND_EFFECT_RUNTIME_DIR,
    VOICE_GENERATOR_CODEC_DIR,
    VOICE_GENERATOR_MODEL_DIR,
    VOICE_GENERATOR_RUNTIME_DIR,
)


MODEL_LOCKS: dict[str, dict[str, Any]] = {
    "openmoss/MOSS-TTS-Local-Transformer-v1.5": {
        "revision": "master",
        "file_count": 19,
        "total_bytes": 9_116_899_103,
        "manifest_sha256": "2ec85506d2450ce65beb83164ecedc3cf81fb38bbdedf3c0a5e35c0b49cf5063",
    },
    "openmoss/MOSS-Audio-Tokenizer-v2": {
        "revision": "master",
        "file_count": 15,
        "total_bytes": 8_498_219_117,
        "manifest_sha256": "84fd35a7f8bc745b6c4832d7d7f2d221756ff261c6f6a860d8f40a086a7f48ba",
    },
    "openmoss/MOSS-VoiceGenerator": {
        "revision": "master",
        "file_count": 17,
        "total_bytes": 4_244_249_582,
        "manifest_sha256": "298fbb371515291742daa6e537e5833cd3c7b5eb3a3e09b16aaaeaac0577f318",
    },
    "openmoss/MOSS-Audio-Tokenizer": {
        "revision": "master",
        "file_count": 14,
        "total_bytes": 7_101_116_247,
        "manifest_sha256": "c20df5cbcba8b90d599a5389936ce98d7fcdb9d86556e724b191733f9f6211ac",
    },
    "openmoss/MOSS-SoundEffect-v2.0": {
        "revision": "master",
        "file_count": 18,
        "total_bytes": 11_230_171_166,
        "manifest_sha256": "b50a3034b1abae0bfcc7435e079e5c03705b1a61ee17f22aaae1941126c7daf7",
    },
}


MODULES: dict[str, dict[str, Any]] = {
    "speech": {
        "name": "语音合成",
        "model_name": "MOSS-TTS Local Transformer v1.5 · 4B",
        "model_id": "openmoss/MOSS-TTS-Local-Transformer-v1.5",
        "description": "参考音色克隆、情感表演、长文本切分与工程化交付。",
        "disk_gb": 16.4,
        "runtime_python": "主程序环境",
        "runtime_mode": "host",
        "engine_available": True,
    },
    "voice_design": {
        "name": "音色设计",
        "model_name": "MOSS-VoiceGenerator · 1.7B",
        "model_id": "openmoss/MOSS-VoiceGenerator",
        "codec_id": "openmoss/MOSS-Audio-Tokenizer",
        "description": "无需参考音频，通过自然语言创建可供配音使用的新音色。",
        "disk_gb": 14.0,
        "runtime_python": "Python 3.12（独立环境）",
        "runtime_mode": "isolated",
        "engine_available": True,
    },
    "sound_effect": {
        "name": "音效生成",
        "model_name": "MOSS-SoundEffect v2.0",
        "model_id": "openmoss/MOSS-SoundEffect-v2.0",
        "description": "根据中英文描述生成最长 30 秒的 48 kHz 音效。",
        "disk_gb": 18.0,
        "runtime_python": "Python 3.12（必需）",
        "runtime_mode": "isolated",
        "engine_available": True,
        "engine_message": "使用 Python 3.12 独立工作进程、FP16 与阶段式低显存调度。",
    },
}


RUNTIME_IMPORT_CHECKS = {
    "voice_design": "import torch, torchaudio, transformers, modelscope, modelscope_hub, soundfile, librosa, tiktoken, accelerate, safetensors, orjson, tqdm, yaml, einops, scipy, psutil, packaging",
    "sound_effect": "import torch, torchaudio, torchvision, transformers, modelscope_hub, soundfile, diffusers, audiotools, moss_soundeffect_v2; from moss_soundeffect_v2 import MossSoundEffectPipeline",
}


RUNTIME_VERSION_LOCKS = {
    "voice_design": {
        "torch": "2.9.1+cu128",
        "torchaudio": "2.9.1+cu128",
        "transformers": "5.0.0",
        "modelscope": "1.39.1",
        "modelscope-hub": "0.2.0",
        "accelerate": "1.14.0",
        "safetensors": "0.6.2",
        "numpy": "2.1.0",
        "orjson": "3.11.4",
        "tqdm": "4.67.1",
        "PyYAML": "6.0.3",
        "einops": "0.8.1",
        "scipy": "1.16.2",
        "librosa": "0.11.0",
        "tiktoken": "0.12.0",
        "soundfile": "0.14.0",
        "psutil": "7.2.2",
        "packaging": "26.3",
    },
    "sound_effect": {
        "moss-soundeffect-v2": "0.1.0",
        "torch": "2.9.0+cu128",
        "torchaudio": "2.9.0+cu128",
        "torchvision": "0.24.0+cu128",
        "transformers": "4.57.1",
        "modelscope": "1.39.1",
        "modelscope-hub": "0.2.0",
        "einops": "0.8.2",
        "pillow": "12.2.0",
        "tqdm": "4.67.3",
        "safetensors": "0.7.0",
        "numpy": "1.26.4",
        "diffusers": "0.37.1",
        "ftfy": "6.3.1",
        "regex": "2026.4.4",
        "soundfile": "0.13.1",
        "descript-audiotools": "0.7.2",
    },
}


RUNTIME_PYTHON_LOCKS = {
    "voice_design": (3, 12),
    "sound_effect": (3, 12),
}


SOUND_EFFECT_SOURCE_REVISION = "58b20a0d5fcc6766658d50967a90a9d890009a46"
SOUND_EFFECT_SOURCE_TREE_SHA256 = "09dc5d50d7e9659383ab693f0addc85a17bb2855e6dbbc2929f84d99538bac70"


MODULE_MODEL_JOBS: dict[str, tuple[tuple[str, Path], ...]] = {
    "speech": (
        ("openmoss/MOSS-TTS-Local-Transformer-v1.5", MOSS_MODEL_DIR),
        ("openmoss/MOSS-Audio-Tokenizer-v2", MOSS_CODEC_DIR),
    ),
    "voice_design": (
        ("openmoss/MOSS-VoiceGenerator", VOICE_GENERATOR_MODEL_DIR),
        ("openmoss/MOSS-Audio-Tokenizer", VOICE_GENERATOR_CODEC_DIR),
    ),
    "sound_effect": (("openmoss/MOSS-SoundEffect-v2.0", SOUND_EFFECT_MODEL_DIR),),
}


MODULE_RUNTIME_DIRS: dict[str, Path | None] = {
    "speech": None,
    "voice_design": VOICE_GENERATOR_RUNTIME_DIR,
    "sound_effect": SOUND_EFFECT_RUNTIME_DIR,
}


def model_jobs(module_id: str) -> tuple[tuple[str, Path], ...]:
    return MODULE_MODEL_JOBS.get(module_id, ())


def model_ids(module_id: str) -> list[str]:
    return [model_id for model_id, _ in model_jobs(module_id)]


def runtime_dir(module_id: str) -> Path | None:
    return MODULE_RUNTIME_DIRS.get(module_id)


def manual_paths(module_id: str) -> list[str]:
    paths = [destination for _, destination in model_jobs(module_id)]
    runtime = runtime_dir(module_id)
    if runtime is not None:
        paths.append(runtime)
    return [str(path.relative_to(ROOT)) for path in paths]
