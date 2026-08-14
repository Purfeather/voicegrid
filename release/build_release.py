from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
BUILD = json.loads((ROOT / "build.json").read_text(encoding="utf-8"))
VERSION = str(BUILD["version"])
DEFAULT_RELEASE_ROOT = Path(r"D:\VoiceGrid-Release")
DEFAULT_BASE_RUNTIME = Path(r"D:\MOSS-TTS-v1.5-Portable\runtime")
PACKAGE_NAMES = {
    "standard": f"VoiceGrid-{VERSION}-Standard",
    "offline": f"VoiceGrid-{VERSION}-Offline",
    "source": f"VoiceGrid-{VERSION}-Source",
}
MODEL_DIRS = (
    "MOSS-TTS-Local-Transformer-v1.5",
    "MOSS-Audio-Tokenizer-v2",
    "MOSS-VoiceGenerator",
    "MOSS-Audio-Tokenizer",
    "MOSS-SoundEffect-v2.0",
)
ISOLATED_RUNTIMES = ("moss-voice-generator", "moss-soundeffect-v2")
DATA_DIRS = (
    "cache",
    "logs",
    "modules",
    "projects",
    "references",
    "uploads",
    "voices",
)
TEXT_SUFFIXES = {
    ".bat", ".cmd", ".cs", ".css", ".html", ".ini", ".json", ".md",
    ".py", ".toml", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
}
FORBIDDEN_TEXT = (
    r"C:\Users\Administrator",
    r"D:\MOSS-TTS-Test-Version",
    r"D:\MOSS-TTS-v1.5-Portable",
)


def _load_release_exclusions() -> dict[str, list[str]]:
    path = ROOT / "release-exclusions.txt"
    sections: dict[str, list[str]] = {"all": []}
    current = "all"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().lower()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


RELEASE_EXCLUSIONS = _load_release_exclusions()


def _is_release_excluded(relative: Path, flavor: str) -> bool:
    posix = relative.as_posix()
    rules = RELEASE_EXCLUSIONS.get("all", []) + RELEASE_EXCLUSIONS.get(flavor, [])
    for rule in rules:
        if fnmatch.fnmatch(posix, rule) or fnmatch.fnmatch(relative.name, rule):
            return True
        if "/" in rule and (posix == rule or posix.startswith(rule.rstrip("/") + "/")):
            return True
        if "/" not in rule and any(fnmatch.fnmatch(part, rule) for part in relative.parts):
            return True
    return False


def prune_release_stage(destination: Path, flavor: str) -> None:
    for path in sorted(destination.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        relative = path.relative_to(destination)
        if not _is_release_excluded(relative, flavor):
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

def run(command: list[str], cwd: Path = ROOT) -> None:
    print("+", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def ensure_release_root(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.drive.upper() != "D:" or resolved.name != "VoiceGrid-Release":
        raise ValueError(f"Release root must be D:\\VoiceGrid-Release, got {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    for name in ("work", "staging", "artifacts", "certificates", "reports", "tools"):
        (resolved / name).mkdir(exist_ok=True)
    return resolved


def safe_remove(path: Path, release_root: Path) -> None:
    resolved = path.resolve()
    if release_root.resolve() not in resolved.parents:
        raise ValueError(f"Refusing to remove outside release root: {resolved}")
    if resolved.is_dir():
        shutil.rmtree(resolved)
    elif resolved.exists():
        resolved.unlink()


def copytree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".mypy_cache",
            ".ruff_cache", "*.tmp", "*.temp", "*.bak",
        ),
    )


def copy_binary_application(destination: Path) -> None:
    for filename in (
        "LICENSE", "README.md", "build.json", "config.json", "requirements.txt",
        "VoiceGrid 声格.exe", "备用启动.bat", "使用说明.txt", "更新日志.log",
    ):
        shutil.copy2(ROOT / filename, destination / filename)
    copytree(ROOT / "LICENSES", destination / "LICENSES")
    copytree(ROOT / "app", destination / "app")
    for name in ("backend", "inference", "native", "workers"):
        copytree(ROOT / "desktop" / name, destination / "desktop" / name)
    for filename in (
        "__init__.py", "host.py", "splash.html", "splash_host.py",
        "splash-identity.json",
    ):
        target = destination / "desktop" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "desktop" / filename, target)
    copytree(ROOT / "desktop" / "assets", destination / "desktop" / "assets")
    copytree(
        ROOT / "desktop" / "frontend" / "dist",
        destination / "desktop" / "frontend" / "dist",
    )
    for name in DATA_DIRS:
        (destination / "data" / name).mkdir(parents=True, exist_ok=True)
    (destination / "optional-models").mkdir(exist_ok=True)
    (destination / "runtimes").mkdir(exist_ok=True)


def rebuild_portable_runtime(
    base_runtime: Path,
    source_site_packages: Path,
    destination: Path,
    marker: Path | None = None,
) -> None:
    if not (base_runtime / "python.exe").is_file():
        raise FileNotFoundError(f"Portable Python base is missing: {base_runtime}")
    if not source_site_packages.is_dir():
        raise FileNotFoundError(f"Site-packages source is missing: {source_site_packages}")
    copytree(base_runtime, destination)
    target_packages = destination / "Lib" / "site-packages"
    if target_packages.exists():
        shutil.rmtree(target_packages)
    copytree(source_site_packages, target_packages)
    if marker is not None:
        shutil.copy2(marker, destination / marker.name)


def validate_python(runtime: Path, imports: str) -> None:
    python = runtime / "python.exe"
    run([
        str(python),
        "-c",
        (
            "import sys;"
            "assert sys.version_info[:2] == (3, 12), sys.version;"
            f"{imports};"
            "print(sys.version);print(sys.prefix)"
        ),
    ])


def stage_standard(release_root: Path, base_runtime: Path) -> Path:
    destination = release_root / "staging" / PACKAGE_NAMES["standard"]
    if destination.exists():
        safe_remove(destination, release_root)
    destination.mkdir(parents=True)
    copy_binary_application(destination)
    rebuild_portable_runtime(
        base_runtime,
        ROOT / ".venv" / "Lib" / "site-packages",
        destination / "runtime",
    )
    validate_python(
        destination / "runtime",
        "import torch,torchaudio,transformers,modelscope,fastapi,pydantic,"
        "uvicorn,webview,soundfile,pystray,PIL",
    )
    prune_release_stage(destination, "standard")
    write_package_metadata(destination, "standard")
    verify_stage(destination, expect_models=False, flavor="standard")
    return destination


def stage_offline(release_root: Path, base_runtime: Path, standard: Path) -> Path:
    destination = release_root / "staging" / PACKAGE_NAMES["offline"]
    if destination.exists():
        safe_remove(destination, release_root)
    copytree(standard, destination)
    for model in MODEL_DIRS:
        source = ROOT / "optional-models" / model
        if not source.is_dir():
            raise FileNotFoundError(f"Offline model is missing: {source}")
        copytree(source, destination / "optional-models" / model)
    for runtime_name in ISOLATED_RUNTIMES:
        source = ROOT / "runtimes" / runtime_name
        rebuild_portable_runtime(
            base_runtime,
            source / "Lib" / "site-packages",
            destination / "runtimes" / runtime_name,
            source / ".voicegrid-runtime.json",
        )
    copytree(
        ROOT / "runtimes" / "sources",
        destination / "runtimes" / "sources",
    )
    validate_python(
        destination / "runtimes" / "moss-voice-generator",
        "import torch,torchaudio,transformers,modelscope,modelscope_hub,"
        "soundfile,librosa,tiktoken,accelerate,safetensors,orjson,yaml,einops,scipy",
    )
    validate_python(
        destination / "runtimes" / "moss-soundeffect-v2",
        "import torch,torchaudio,torchvision,transformers,modelscope_hub,"
        "soundfile,diffusers,audiotools,moss_soundeffect_v2",
    )
    prune_release_stage(destination, "offline")
    write_package_metadata(destination, "offline")
    verify_stage(destination, expect_models=True, flavor="offline")
    return destination


def source_files() -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={ROOT.as_posix()}",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8"))
        posix = relative.as_posix()
        if posix == "VoiceGrid 声格.exe" or posix.startswith("desktop/frontend/dist/") or _is_release_excluded(relative, "source"):
            continue
        paths.append(relative)
    return paths


def stage_source(release_root: Path) -> Path:
    destination = release_root / "staging" / PACKAGE_NAMES["source"]
    if destination.exists():
        safe_remove(destination, release_root)
    destination.mkdir(parents=True)
    for relative in source_files():
        source = ROOT / relative
        if not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    prune_release_stage(destination, "source")
    write_package_metadata(destination, "source")
    verify_stage(destination, expect_models=False, source_package=True, flavor="source")
    return destination


def write_package_metadata(destination: Path, flavor: str) -> None:
    payload = {
        "product": BUILD["product"],
        "version": VERSION,
        "build_id": BUILD["build_id"],
        "license": "MIT",
        "flavor": flavor,
        "models_included": list(MODEL_DIRS) if flavor == "offline" else [],
    }
    (destination / "RELEASE-MANIFEST.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def iter_files(root: Path) -> Iterable[Path]:
    return (path for path in root.rglob("*") if path.is_file())


def has_reparse_point(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def verify_stage(
    destination: Path,
    expect_models: bool,
    source_package: bool = False,
    flavor: str | None = None,
) -> None:
    if flavor is not None:
        violations = [path.relative_to(destination).as_posix() for path in iter_files(destination) if _is_release_excluded(path.relative_to(destination), flavor)]
        if violations:
            raise RuntimeError(f"Release exclusions leaked into {flavor}: {violations[:20]}")
    if not (destination / "LICENSE").is_file():
        raise RuntimeError(f"MIT license is missing from {destination}")
    if not source_package:
        required = (
            destination / "VoiceGrid 声格.exe",
            destination / "runtime" / "pythonw.exe",
            destination / "desktop" / "frontend" / "dist" / "index.html",
        )
        if not all(path.is_file() for path in required):
            raise RuntimeError(f"Portable package is incomplete: {destination}")
    reparse = [path for path in destination.rglob("*") if has_reparse_point(path)]
    if reparse:
        raise RuntimeError(f"Reparse points are forbidden: {reparse[:3]}")
    if not source_package:
        violations: list[str] = []
        for path in iter_files(destination):
            if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 4 * 1024 * 1024:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for marker in FORBIDDEN_TEXT:
                if marker in text:
                    violations.append(f"{path.relative_to(destination)}: {marker}")
        if violations:
            raise RuntimeError("Absolute development paths found:\n" + "\n".join(violations[:20]))
    present_models = {
        name for name in MODEL_DIRS
        if (destination / "optional-models" / name).is_dir()
    }
    if expect_models and present_models != set(MODEL_DIRS):
        raise RuntimeError(f"Offline model set is incomplete: {present_models}")
    if not expect_models and present_models:
        raise RuntimeError(f"Models leaked into non-offline package: {present_models}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_file_manifest(stage: Path, report: Path) -> None:
    lines = []
    for path in sorted(iter_files(stage), key=lambda item: item.as_posix().lower()):
        lines.append(f"{sha256(path)}  {path.relative_to(stage).as_posix()}")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def find_7zip(release_root: Path) -> Path:
    candidates = (
        release_root / "tools" / "7zip-26.02" / "7z.exe",
        release_root / "tools" / "7zip-26.02" / "7za.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("7-Zip 26.02 is missing from release tools.")


def archive_stage(release_root: Path, flavor: str) -> list[Path]:
    stage = release_root / "staging" / PACKAGE_NAMES[flavor]
    if not stage.is_dir():
        raise FileNotFoundError(stage)
    artifacts = release_root / "artifacts"
    base = artifacts / f"{PACKAGE_NAMES[flavor]}.7z"
    for old in artifacts.glob(base.name + "*"):
        safe_remove(old, release_root)
    seven_zip = find_7zip(release_root)
    command = [
        str(seven_zip), "a", "-t7z", "-mx=5", "-m0=lzma2", "-mmt=on",
    ]
    # The offline edition is always distributed as 4 GiB volumes. Standard
    # and source editions stay as single archives; their compressed artifact
    # size is validated after creation and must remain within the 4 GiB limit.
    if flavor == "offline":
        command.append("-v4g")
    command.extend([str(base), stage.name])
    run(command, stage.parent)
    volumes = sorted(artifacts.glob(base.name + "*"))
    if not volumes:
        raise RuntimeError(f"Archive was not created: {base}")
    if flavor != "offline" and len(volumes) == 1 and volumes[0].stat().st_size > 4 * 1024**3:
        raise RuntimeError(
            f"{flavor} archive exceeds 4 GiB and must be rebuilt as volumes: {volumes[0]}"
        )
    run([str(seven_zip), "t", str(volumes[0])], artifacts)
    return volumes


def write_artifact_hashes(release_root: Path) -> Path:
    artifacts = release_root / "artifacts"
    paths = [
        path for path in artifacts.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    output = artifacts / "SHA256SUMS.txt"
    output.write_text(
        "\n".join(f"{sha256(path)}  {path.name}" for path in sorted(paths)) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build VoiceGrid portable release packages.")
    parser.add_argument(
        "command",
        choices=("stage", "stage-source", "manifest", "archive", "all"),
        default="all",
        nargs="?",
    )
    parser.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE_ROOT)
    parser.add_argument("--base-runtime", type=Path, default=DEFAULT_BASE_RUNTIME)
    args = parser.parse_args()
    release_root = ensure_release_root(args.release_root)
    stages: dict[str, Path] = {}
    if args.command in {"stage", "all"}:
        stages["standard"] = stage_standard(release_root, args.base_runtime)
        stages["offline"] = stage_offline(
            release_root,
            args.base_runtime,
            stages["standard"],
        )
        stages["source"] = stage_source(release_root)
    elif args.command == "stage-source":
        stages["source"] = stage_source(release_root)
    if args.command in {"manifest", "all"}:
        for flavor in PACKAGE_NAMES:
            stage = release_root / "staging" / PACKAGE_NAMES[flavor]
            if not stage.is_dir():
                raise FileNotFoundError(stage)
            write_file_manifest(
                stage,
                release_root / "reports" / f"{PACKAGE_NAMES[flavor]}-FILES-SHA256.txt",
            )
    if args.command in {"archive", "all"}:
        for flavor in ("standard", "offline", "source"):
            archive_stage(release_root, flavor)
        write_artifact_hashes(release_root)
    print("VoiceGrid release build completed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
