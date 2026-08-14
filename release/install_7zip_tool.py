from __future__ import annotations

import hashlib
import subprocess
import urllib.request
from pathlib import Path


RELEASE_ROOT = Path(r"D:\VoiceGrid-Release")
URL = "https://www.7-zip.org/a/7z2602-x64.exe"
EXPECTED_SHA256 = "6745fa76dc2ea031596d8678f6f6b99c3c1b435b4164a63485adbbc7b8d82ef0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    work = RELEASE_ROOT / "work"
    target = RELEASE_ROOT / "tools" / "7zip-26.02"
    work.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    installer = work / "7z2602-x64.exe"
    if not installer.is_file() or sha256(installer) != EXPECTED_SHA256:
        temporary = work / "7z2602-x64.exe.download"
        urllib.request.urlretrieve(URL, temporary)
        if sha256(temporary) != EXPECTED_SHA256:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("The official 7-Zip installer hash does not match the pinned release.")
        temporary.replace(installer)
    subprocess.run(
        [str(installer), "/S", f"/D={target}"],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    executable = target / "7z.exe"
    if not executable.is_file():
        raise RuntimeError("7-Zip was not installed into the release tool directory.")
    subprocess.run([str(executable), "i"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
