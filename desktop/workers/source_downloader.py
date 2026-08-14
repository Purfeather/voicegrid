from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path


def _tree_digest(root: Path) -> tuple[str, list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append({"path": relative, "size": path.stat().st_size, "sha256": digest})
    payload = "\n".join(f"{row['path']}\t{row['size']}\t{row['sha256']}" for row in rows).encode("utf-8")
    return hashlib.sha256(payload).hexdigest(), rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--subdirectory", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--tree-sha256", required=True)
    args = parser.parse_args()

    destination = Path(args.destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    archive = destination.parent / f".{destination.name}-{args.revision}.zip.partial"
    extract_root = destination.parent / f".{destination.name}.extract"
    staging = destination.parent / f".{destination.name}.partial"
    url = f"https://codeload.github.com/{args.repository}/zip/{args.revision}"

    request = urllib.request.Request(url, headers={"User-Agent": "VoiceGrid/1.0 source installer"})
    with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as target:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            target.write(block)
            downloaded += len(block)
            print(
                "VOICEGRID_INSTALL_PROGRESS "
                + json.dumps({"downloaded": downloaded, "total": total or downloaded, "file": "官方推理源码"}, ensure_ascii=False),
                flush=True,
            )

    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as package:
            package.extractall(extract_root)
        roots = [item for item in extract_root.iterdir() if item.is_dir()]
        if len(roots) != 1:
            raise RuntimeError("官方源码压缩包结构异常。")
        source = roots[0] / args.subdirectory
        if not (source / "pyproject.toml").is_file() or not (source / "pipeline_moss_soundeffect.py").is_file():
            raise RuntimeError("官方源码中缺少 MOSS-SoundEffect v2 推理包。")
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source, staging)
        license_path = roots[0] / "LICENSE"
        if license_path.is_file():
            shutil.copy2(license_path, staging / "UPSTREAM_LICENSE")
        digest, files = _tree_digest(staging)
        if digest != args.tree_sha256:
            raise RuntimeError(
                f"官方推理源码内容与 VoiceGrid 锁定清单不一致，安装已停止（实际摘要：{digest}）。"
            )
        marker = {
            "repository": args.repository,
            "revision": args.revision,
            "subdirectory": args.subdirectory,
            "tree_sha256": digest,
            "files": files,
            "verified_at": datetime.now().isoformat(timespec="seconds"),
        }
        (staging / ".voicegrid-source.json").write_text(
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
    finally:
        archive.unlink(missing_ok=True)
        if extract_root.exists():
            shutil.rmtree(extract_root)
        if staging.exists():
            shutil.rmtree(staging)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
