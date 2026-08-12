from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def manifest_digest(files) -> str:
    rows = []
    for entry in files:
        if getattr(entry, "is_dir", False) or getattr(entry, "type", "") == "tree":
            continue
        rows.append((str(entry.path), int(entry.size or 0), str(entry.sha256 or "")))
    rows.sort()
    serialized = "\n".join(f"{path}\t{size}\t{sha256}" for path, size, sha256 in rows).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def install_inventory(files) -> tuple[int, int]:
    entries = [entry for entry in files if not getattr(entry, "is_dir", False) and getattr(entry, "type", "") != "tree"]
    return len(entries), sum(int(entry.size or 0) for entry in entries)


def install_manifest(files) -> list[dict[str, object]]:
    rows = []
    for entry in files:
        if getattr(entry, "is_dir", False) or getattr(entry, "type", "") == "tree":
            continue
        rows.append({"path": str(entry.path), "size": int(entry.size or 0), "sha256": str(entry.sha256 or "")})
    return sorted(rows, key=lambda item: str(item["path"]))


@dataclass(frozen=True)
class ManifestVerification:
    checked_count: int
    mismatches: tuple[str, ...]
    missing_paths: tuple[str, ...]
    unverified_paths: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not (self.mismatches or self.missing_paths or self.unverified_paths)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_install_manifest(root: Path, manifest: list[dict[str, object]]) -> ManifestVerification:
    """Verify every locked repository file, including hidden metadata files."""
    root = root.resolve()
    checked_count = 0
    mismatches: list[str] = []
    missing_paths: list[str] = []
    unverified_paths: list[str] = []

    for entry in manifest:
        relative = str(entry["path"]).replace("\\", "/").lstrip("/")
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            mismatches.append(f"{relative}: path escapes install root")
            continue
        if not candidate.is_file():
            missing_paths.append(relative)
            continue
        expected_size = int(entry.get("size") or 0)
        actual_size = candidate.stat().st_size
        if actual_size != expected_size:
            mismatches.append(f"{relative}: size {actual_size} != {expected_size}")
            continue
        expected_sha256 = str(entry.get("sha256") or "").lower()
        if not expected_sha256:
            unverified_paths.append(relative)
            continue
        actual_sha256 = _sha256_file(candidate)
        checked_count += 1
        if actual_sha256 != expected_sha256:
            mismatches.append(f"{relative}: sha256 {actual_sha256} != {expected_sha256}")

    return ManifestVerification(
        checked_count=checked_count,
        mismatches=tuple(mismatches),
        missing_paths=tuple(missing_paths),
        unverified_paths=tuple(unverified_paths),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()

    from modelscope_hub.api import HubApi
    from modelscope_hub.constants import RepoType
    from modelscope_hub import ProgressCallback

    destination = Path(args.destination).resolve()
    staging = destination.parent / f".{destination.name}.partial"
    api = HubApi()
    files = api.list_repo_files(args.repo_id, RepoType.MODEL, revision=args.revision, recursive=True)
    current_digest = manifest_digest(files)
    file_count, total_bytes = install_inventory(files)
    manifest = install_manifest(files)
    if current_digest != args.manifest_sha256:
        raise RuntimeError(
            "ModelScope 官方仓库内容已更新。为避免静默升级，当前安装已停止，请先更新 VoiceGrid 的模型锁定清单。"
        )
    staging.mkdir(parents=True, exist_ok=True)

    class VoiceGridProgress(ProgressCallback):
        lock = threading.Lock()
        downloaded = 0

        def update(self, size: int) -> None:
            with self.lock:
                type(self).downloaded += int(size)
                completed = min(type(self).downloaded, total_bytes)
                print(
                    "VOICEGRID_INSTALL_PROGRESS "
                    + json.dumps(
                        {"downloaded": completed, "total": total_bytes, "file": self.filename},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    api.download_repo(
        args.repo_id,
        RepoType.MODEL,
        revision=args.revision,
        local_dir=staging,
        max_workers=4,
        progress_callbacks=[VoiceGridProgress],
    )
    verification = verify_install_manifest(staging, manifest)
    if not verification.valid:
        raise RuntimeError(f"模型完整性校验失败：{verification}")
    marker = {
        "repo_id": args.repo_id,
        "revision": args.revision,
        "manifest_sha256": args.manifest_sha256,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "files": manifest,
        "verified_at": datetime.now().isoformat(timespec="seconds"),
    }
    (staging / ".voicegrid-install.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    previous = destination.parent / f".{destination.name}.previous"
    if previous.exists():
        shutil.rmtree(previous)
    if destination.exists():
        os.replace(destination, previous)
    try:
        os.replace(staging, destination)
    except Exception:
        if previous.exists() and not destination.exists():
            os.replace(previous, destination)
        raise
    if previous.exists():
        shutil.rmtree(previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
