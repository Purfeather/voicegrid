from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from .module_catalog import (
    MODEL_LOCKS,
    RUNTIME_IMPORT_CHECKS,
    RUNTIME_PYTHON_LOCKS,
    RUNTIME_VERSION_LOCKS,
    SOUND_EFFECT_SOURCE_REVISION,
    SOUND_EFFECT_SOURCE_TREE_SHA256,
    model_jobs,
    runtime_dir,
)
from .paths import ROOT, SOUND_EFFECT_SOURCE_DIR


LogCallback = Callable[[str, str], None]


def runtime_python(runtime: Path) -> Path:
    portable = runtime / "python.exe"
    return portable if portable.is_file() else runtime / "Scripts" / "python.exe"


def requirements_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_manifest_file(root: Path, relative: str) -> Path | None:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        return None
    return candidate


def _lock_for_model_path(path: Path) -> dict[str, object] | None:
    for jobs in (model_jobs("speech"), model_jobs("voice_design"), model_jobs("sound_effect")):
        for model_id, destination in jobs:
            if path.name == destination.name:
                return MODEL_LOCKS[model_id]
    return None


def model_complete(path: Path, module_id: str) -> bool:
    if not path.is_dir():
        return False
    marker = path / ".voicegrid-install.json"
    if marker.is_file():
        try:
            state = json.loads(marker.read_text(encoding="utf-8"))
            lock = MODEL_LOCKS.get(str(state.get("repo_id")))
            if lock and state.get("manifest_sha256") == lock["manifest_sha256"]:
                files = list(state.get("files") or [])
                if len(files) != int(lock["file_count"]) or sum(int(item.get("size", 0)) for item in files) != int(lock["total_bytes"]):
                    return False
                for item in files:
                    candidate = _safe_manifest_file(path, str(item.get("path") or ""))
                    if candidate is None or not candidate.is_file() or candidate.stat().st_size != int(item.get("size", -1)):
                        return False
                return True
        except Exception:
            return False
    required = "model_index.json" if module_id == "sound_effect" else "config.json"
    config = path / required
    weights = list(path.rglob("*.safetensors"))
    lock = _lock_for_model_path(path)
    content_files = [
        item
        for item in path.rglob("*")
        if item.is_file() and item.name != ".voicegrid-install.json" and ".cache" not in item.parts
    ]
    return bool(
        lock
        and config.is_file()
        and config.stat().st_size > 0
        and weights
        and all(item.stat().st_size > 0 for item in weights)
        and len(content_files) == int(lock["file_count"])
        and sum(item.stat().st_size for item in content_files) == int(lock["total_bytes"])
    )


def sound_effect_source_dir() -> Path | None:
    configured = os.environ.get("VOICEGRID_SOUND_EFFECT_SOURCE", "").strip()
    candidates = [
        Path(configured).expanduser() if configured else None,
        SOUND_EFFECT_SOURCE_DIR / "moss_soundeffect_v2",
        ROOT / "desktop" / "workers" / "vendor" / "moss_soundeffect_v2",
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        resolved = candidate.resolve()
        pyproject = resolved / "pyproject.toml"
        pipeline = resolved / "pipeline_moss_soundeffect.py"
        marker = resolved / ".voicegrid-source.json"
        marker_valid = False
        if marker.is_file():
            try:
                source_state = json.loads(marker.read_text(encoding="utf-8"))
                marker_valid = (
                    source_state.get("revision") == SOUND_EFFECT_SOURCE_REVISION
                    and source_state.get("tree_sha256") == SOUND_EFFECT_SOURCE_TREE_SHA256
                )
            except Exception:
                marker_valid = False
        if pyproject.is_file() and pipeline.is_file() and (configured or marker_valid):
            return resolved
    return None


def python312_venv_command(destination: Path) -> list[str]:
    configured = os.environ.get("VOICEGRID_PYTHON312", "").strip()
    if configured:
        return [configured, "-m", "venv", str(destination)]
    if sys.version_info[:2] == (3, 12):
        return [sys.executable, "-m", "venv", str(destination)]
    if os.name == "nt":
        return ["py", "-3.12", "-m", "venv", str(destination)]
    return ["python3.12", "-m", "venv", str(destination)]


def detect_module(module_id: str, log: LogCallback) -> tuple[bool, bool, list[str]]:
    jobs = model_jobs(module_id)
    model_states = [(destination, model_complete(destination, module_id)) for _, destination in jobs]
    model_ready = bool(model_states) and all(ready for _, ready in model_states)
    runtime = runtime_dir(module_id)
    runtime_ready = True if runtime is None else runtime_complete(runtime, module_id, log)
    missing = [str(path.relative_to(ROOT)) for path, ready in model_states if not ready]
    if runtime is not None and not runtime_ready:
        missing.append(str(runtime.relative_to(ROOT)))
    return model_ready, runtime_ready, missing


def runtime_complete(runtime: Path, module_id: str, log: LogCallback) -> bool:
    python = runtime_python(runtime)
    marker = runtime / ".voicegrid-runtime.json"
    requirements = ROOT / "desktop" / "workers" / f"requirements-{module_id}.txt"
    if not python.is_file() or not requirements.is_file():
        return False
    try:
        if marker.is_file():
            state = json.loads(marker.read_text(encoding="utf-8"))
            if state.get("requirements_sha256") != requirements_sha256(requirements):
                return False
            if module_id == "sound_effect" and state.get("source_revision") != SOUND_EFFECT_SOURCE_REVISION:
                return False
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        package_names = list(RUNTIME_VERSION_LOCKS[module_id])
        version_script = (
            "import importlib.metadata,json,sys;"
            f"names={package_names!r};"
            "print(json.dumps({'python':[sys.version_info.major,sys.version_info.minor],"
            "'packages':{name:importlib.metadata.version(name) for name in names}}))"
        )
        result = subprocess.run(
            [str(python), "-c", RUNTIME_IMPORT_CHECKS[module_id] + ";" + version_script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=creationflags,
        )
        if result.returncode != 0:
            log(module_id, "RUNTIME CHECK FAILED\n" + (result.stdout or "") + (result.stderr or ""))
            return False
        probe = json.loads(result.stdout.strip().splitlines()[-1])
        versions = dict(probe.get("packages") or {})
        python_lock = RUNTIME_PYTHON_LOCKS.get(module_id)
        if python_lock and tuple(probe.get("python") or ()) != python_lock:
            log(module_id, f"PYTHON VERSION MISMATCH: expected={python_lock} actual={probe.get('python')}")
            return False
        mismatches = {
            name: {"expected": version, "actual": versions.get(name)}
            for name, version in RUNTIME_VERSION_LOCKS[module_id].items()
            if versions.get(name) != version
        }
        if mismatches:
            log(module_id, f"PACKAGE VERSION MISMATCH: {json.dumps(mismatches, ensure_ascii=False)}")
            return False
        probe_script = "runtime_audio_probe.py" if module_id == "voice_design" else "sound_effect_runtime_probe.py"
        audio_probe = subprocess.run(
            [str(python), str(ROOT / "desktop" / "workers" / probe_script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=creationflags,
        )
        if audio_probe.returncode != 0:
            log(module_id, "AUDIO PROBE FAILED\n" + (audio_probe.stdout or "") + (audio_probe.stderr or ""))
            return False
        audio_result = json.loads(audio_probe.stdout.strip().splitlines()[-1])
        expected_rate = 24_000 if module_id == "voice_design" else 48_000
        if (
            audio_result.get("format") != "WAV"
            or audio_result.get("subtype") != "PCM_24"
            or int(audio_result.get("sample_rate", 0)) != expected_rate
            or int(audio_result.get("channels", 0)) != 1
        ):
            log(module_id, f"AUDIO PROBE MISMATCH: {json.dumps(audio_result, ensure_ascii=False)}")
            return False
        if not marker.is_file():
            marker.write_text(
                json.dumps(
                    {
                        "module": module_id,
                        "requirements_sha256": requirements_sha256(requirements),
                        "adopted_at": datetime.now().isoformat(timespec="seconds"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
                newline="\n",
            )
        return True
    except Exception:
        log(module_id, "RUNTIME CHECK EXCEPTION\n" + traceback.format_exc())
        return False
