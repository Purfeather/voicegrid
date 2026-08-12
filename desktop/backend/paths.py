from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = Path(os.environ.get("MOSS_TTS_RUNTIME_ROOT", ROOT)).resolve()
DESKTOP_DIR = ROOT / "desktop"
FRONTEND_DIST = DESKTOP_DIR / "frontend" / "dist"
ASSETS_DIR = DESKTOP_DIR / "assets"
DATA_DIR = Path(os.environ.get("MOSS_TTS_DATA_DIR", RUNTIME_ROOT / "data")).resolve()
APP_DB = DATA_DIR / "app.db"
PROJECTS_DIR = Path(os.environ.get("MOSS_TTS_PROJECTS_DIR", RUNTIME_ROOT / "projects")).resolve()
OUTPUTS_DIR = Path(os.environ.get("MOSS_TTS_OUTPUTS_DIR", RUNTIME_ROOT / "outputs")).resolve()
REFERENCES_DIR = Path(os.environ.get("MOSS_TTS_REFERENCES_DIR", RUNTIME_ROOT / "references")).resolve()
UPLOADS_DIR = DATA_DIR / "uploads"
VOICES_DIR = DATA_DIR / "voices"
CACHE_DIR = DATA_DIR / "cache"
RAW_OUTPUTS_DIR = CACHE_DIR / "raw_outputs"
VOICE_CACHE_DIR = CACHE_DIR / "voice_cache"
HF_HOME_DIR = CACHE_DIR / "hf_cache"
HF_MODULES_DIR = CACHE_DIR / "hf_modules"
MODELS_DIR = ROOT / "models"
MOSS_MODEL_DIR = MODELS_DIR / "MOSS-TTS-Local-Transformer-v1.5"
MOSS_CODEC_DIR = MODELS_DIR / "MOSS-Audio-Tokenizer-v2"
LOGS_DIR = Path(os.environ.get("MOSS_TTS_LOGS_DIR", RUNTIME_ROOT / "logs")).resolve()


def ensure_directories() -> None:
    for directory in (
        DATA_DIR,
        PROJECTS_DIR,
        OUTPUTS_DIR,
        REFERENCES_DIR,
        UPLOADS_DIR,
        VOICES_DIR,
        CACHE_DIR,
        RAW_OUTPUTS_DIR,
        VOICE_CACHE_DIR,
        HF_HOME_DIR,
        HF_MODULES_DIR,
        LOGS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
