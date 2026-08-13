from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "desktop" / "frontend"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
RAW_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")


def run(label: str, command: list[str], cwd: Path = ROOT) -> None:
    print(f"\n== {label} ==", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def check_component_colors() -> None:
    problems: list[str] = []
    source = FRONTEND / "src"
    for path in source.rglob("*.css"):
        if path.name == "tokens.css":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if RAW_COLOR.search(line):
                problems.append(f"{path.relative_to(ROOT)}:{number}")
    if problems:
        raise SystemExit("组件 CSS 包含未经过设计令牌的颜色：\n" + "\n".join(problems))
    print("Component colors use semantic tokens.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the VoiceGrid development quality gate.")
    parser.add_argument("--skip-dist-check", action="store_true", help="Allow rebuilt frontend assets to differ from Git.")
    args = parser.parse_args()
    if not PYTHON.is_file():
        raise SystemExit(f"Missing project Python runtime: {PYTHON}")

    run("encoding and line endings", [str(PYTHON), "-m", "unittest", "desktop.tests.test_encoding", "-q"])
    run("backend tests", [str(PYTHON), "-m", "unittest", "discover", "-s", "desktop/tests", "-p", "test_*.py", "-q"])
    run("identity and icon consistency", [str(PYTHON), "-m", "unittest", "desktop.tests.test_identity", "-q"])
    run("generated API contracts", [str(PYTHON), "desktop/tools/generate_api_types.py", "--check"])
    run("frontend tests", ["npm.cmd", "test", "--", "--run"], FRONTEND)
    run("frontend production build", ["npm.cmd", "run", "build"], FRONTEND)
    check_component_colors()
    if not args.skip_dist_check:
        run(
            "tracked frontend assets",
            ["git", "-c", f"safe.directory={ROOT.as_posix()}", "diff", "--exit-code", "HEAD", "--", "desktop/frontend/dist"],
        )
    run("Git whitespace", ["git", "-c", f"safe.directory={ROOT.as_posix()}", "diff", "--check"])
    print("\nVoiceGrid quality gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
