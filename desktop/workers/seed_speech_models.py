from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from desktop.backend.module_service import MODEL_LOCKS
from desktop.workers.module_downloader import install_manifest, manifest_digest, verify_install_manifest


REPOSITORIES = {
    "openmoss/MOSS-TTS-Local-Transformer-v1.5": "MOSS-TTS-Local-Transformer-v1.5",
    "openmoss/MOSS-Audio-Tokenizer-v2": "MOSS-Audio-Tokenizer-v2",
}


def copy_locked_repository(source: Path, destination: Path, repo_id: str, files: list[object]) -> None:
    lock = MODEL_LOCKS[repo_id]
    manifest = install_manifest(files)
    if manifest_digest(files) != lock["manifest_sha256"]:
        raise RuntimeError(f"ModelScope manifest changed for {repo_id}")
    staging = destination.parent / f".{destination.name}.seed-partial"
    previous = destination.parent / f".{destination.name}.seed-previous"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for entry in manifest:
        relative = Path(str(entry["path"]))
        source_file = source / relative
        if not source_file.is_file():
            raise FileNotFoundError(f"Source model is missing locked file: {source_file}")
        target_file = staging / relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
    verification = verify_install_manifest(staging, manifest)
    if not verification.valid:
        raise RuntimeError(f"Seed verification failed for {repo_id}: {verification}")
    marker = {
        "repo_id": repo_id,
        "revision": lock["revision"],
        "manifest_sha256": lock["manifest_sha256"],
        "file_count": lock["file_count"],
        "total_bytes": lock["total_bytes"],
        "files": manifest,
        "verified_at": datetime.now().isoformat(timespec="seconds"),
        "source": "read-only local seed",
    }
    (staging / ".voicegrid-install.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--destination-root", required=True)
    args = parser.parse_args()

    from modelscope_hub.api import HubApi
    from modelscope_hub.constants import RepoType

    source_root = Path(args.source_root).resolve()
    destination_root = Path(args.destination_root).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    api = HubApi()
    for repo_id, folder_name in REPOSITORIES.items():
        lock = MODEL_LOCKS[repo_id]
        files = api.list_repo_files(repo_id, RepoType.MODEL, revision=lock["revision"], recursive=True)
        copy_locked_repository(source_root / folder_name, destination_root / folder_name, repo_id, files)
        print(f"verified {repo_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
