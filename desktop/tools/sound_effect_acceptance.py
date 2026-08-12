from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from desktop.tools.acceptance_common import (
    JsonHttpClient,
    NvidiaSmiSampler,
    WavExpectations,
    cancel_task_and_wait,
    create_module_task,
    get_or_create_project,
    inspect_wav,
    poll_task,
    save_module_workspace,
    wait_for_task_progress,
    write_report,
)


MODULE_ID = "sound_effect"
DEFAULT_SEED = 2026
RETRY_SEED = 2027
DEFAULT_REPORT_DIR = Path(__file__).resolve().parents[1] / "tests" / "reports"


@dataclass(frozen=True)
class SoundEffectCase:
    case_id: str
    title: str
    prompt: str
    seconds: int


GATE = SoundEffectCase(
    "GATE",
    "FP16低显存技术闸门",
    "The crisp, rhythmic click-clack of fast typing on a mechanical keyboard, recorded close-up in a quiet room.",
    3,
)

CASES = (
    SoundEffectCase("A", "近距离机械键盘", "近距离录制的机械键盘快速敲击，按键清脆、节奏连续，安静室内环境。", 5),
    SoundEffectCase("B", "雨夜城市道路", "雨夜城市道路，车辆驶过湿润路面，轮胎带起水花，远近层次清晰。", 10),
    SoundEffectCase("C", "金属门与仓库回声", "沉重金属门缓慢开启，铰链机械摩擦，声音在空旷仓库中产生长回声。", 20),
    SoundEffectCase("D", "渐进森林环境", "清晨森林环境，风吹树叶逐渐增强，小鸟在不同距离鸣叫，远处溪流持续流动。", 30),
)


def workspace_for(case: SoundEffectCase, seed: int = DEFAULT_SEED, steps: int = 100) -> dict[str, Any]:
    return {
        "prompt": case.prompt,
        "parameters": {
            "seconds": case.seconds,
            "num_inference_steps": steps,
            "cfg_scale": 4.0,
            "sigma_shift": 5.0,
            "seed": seed,
        },
    }


def dry_run_plan(project_name: str, base_url: str) -> dict[str, Any]:
    return {
        "tool": "sound_effect_acceptance",
        "dry_run": True,
        "project_name": project_name,
        "base_url": base_url,
        "module": MODULE_ID,
        "gate": {**asdict(GATE), "workspace": workspace_for(GATE, steps=10)},
        "cases": [{**asdict(case), "workspace": workspace_for(case)} for case in CASES],
        "cancel_recovery": True,
        "rules": {
            "gate_stops_matrix": True,
            "single_technical_retry_seed": RETRY_SEED,
            "wav": "48 kHz mono PCM-24",
            "duration_tolerance_seconds": 0.02,
        },
    }


def _progress(task: dict[str, Any]) -> None:
    print(f"[{task.get('status', '?'):>9}] {float(task.get('progress') or 0) * 100:6.1f}% {task.get('message', '')}", flush=True)


def run_case(
    client: JsonHttpClient,
    project_id: str,
    case: SoundEffectCase,
    seed: int,
    steps: int,
    attempt: int,
    temporary_directory: Path,
    timeout: float,
    sampler: NvidiaSmiSampler,
) -> dict[str, Any]:
    workspace = workspace_for(case, seed=seed, steps=steps)
    started = time.monotonic()
    mark = sampler.mark()
    result: dict[str, Any] = {
        "case_id": case.case_id,
        "title": case.title,
        "attempt": attempt,
        "seed": seed,
        "workspace": workspace,
        "task_status": "not_started",
        "technical_passed": False,
        "failures": [],
    }
    try:
        saved = save_module_workspace(client, project_id, MODULE_ID, workspace)
        result["project_revision"] = saved["revision"]
        task = create_module_task(client, project_id, MODULE_ID, workspace)
        result["task_id"] = task["id"]
        terminal = poll_task(client, task["id"], timeout=timeout, interval=.5, on_update=_progress)
        result["task_status"] = terminal.get("status")
        result["task_message"] = terminal.get("message")
        result["task_error"] = terminal.get("error")
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["gpu"] = sampler.summary_since(mark)
        if terminal.get("status") != "completed" or not terminal.get("result_id"):
            result["failures"] = ["task_not_completed"]
            return result
        output_id = str(terminal["result_id"])
        history = client.get(f"/projects/{project_id}/history", {"module": MODULE_ID})
        result["output_id"] = output_id
        result["output"] = next((item for item in history if item.get("id") == output_id), {})
        local_path = temporary_directory / f"{case.case_id.lower()}-attempt-{attempt}.wav"
        result["download"] = client.download(f"/artifacts/{output_id}", local_path, {"download": True})
        result["wav"] = inspect_wav(local_path, WavExpectations(
            format="WAV",
            subtype="PCM_24",
            sample_rate=48000,
            channels=1,
            minimum_duration=max(.25, case.seconds - .02),
            maximum_duration=case.seconds + .02,
            maximum_clipping_ratio=.005,
        ))
        result["technical_passed"] = bool(result["wav"]["passed"])
        result["failures"] = list(result["wav"]["failures"])
    except Exception as exc:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["gpu"] = sampler.summary_since(mark)
        result["failures"] = ["exception"]
        result["exception"] = f"{type(exc).__name__}: {exc}"
    return result


def run_with_retry(client: JsonHttpClient, project_id: str, case: SoundEffectCase, steps: int, temporary: Path, timeout: float, sampler: NvidiaSmiSampler) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    first = run_case(client, project_id, case, DEFAULT_SEED, steps, 1, temporary, timeout, sampler)
    attempts = [first]
    if first.get("task_status") == "completed" and not first.get("technical_passed"):
        second = run_case(client, project_id, case, RETRY_SEED, steps, 2, temporary, timeout, sampler)
        attempts.append(second)
    return attempts[-1], attempts


def run_cancel_recovery(client: JsonHttpClient, project_id: str, timeout: float) -> dict[str, Any]:
    long_workspace = workspace_for(CASES[-1])
    save_module_workspace(client, project_id, MODULE_ID, long_workspace)
    task = create_module_task(client, project_id, MODULE_ID, long_workspace)
    observed = wait_for_task_progress(client, task["id"], .12, timeout=min(timeout, 600), interval=.5)
    if observed.get("status") not in {"queued", "running"}:
        return {"passed": False, "task": observed, "failure": "task_finished_before_cancel"}
    cancelled = cancel_task_and_wait(client, task["id"], timeout=180, interval=.5)
    gate_workspace = workspace_for(GATE, steps=10)
    save_module_workspace(client, project_id, MODULE_ID, gate_workspace)
    recovery = create_module_task(client, project_id, MODULE_ID, gate_workspace)
    recovered = poll_task(client, recovery["id"], timeout=timeout, interval=.5, on_update=_progress)
    return {
        "passed": cancelled.get("status") == "cancelled" and recovered.get("status") == "completed",
        "cancelled_task": cancelled,
        "recovery_task": recovered,
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    client = JsonHttpClient(args.base_url, timeout=60)
    descriptor = next(item for item in client.get("/modules") if item["id"] == MODULE_ID)
    if not descriptor.get("installed") or not descriptor.get("engine_available"):
        raise RuntimeError(f"音效模块尚未就绪：{descriptor.get('message') or descriptor.get('engine_message')}")
    project, created = get_or_create_project(client, args.project_name)
    report: dict[str, Any] = {
        "title": "声格 VoiceGrid MOSS-SoundEffect-v2.0 硬件验收",
        "status": "running",
        "started_at": started_at,
        "base_url": args.base_url,
        "project": {"id": project["id"], "name": project["name"], "created": created},
        "module": descriptor,
        "samples": [],
        "errors": [],
    }
    with tempfile.TemporaryDirectory(prefix="voicegrid-sfx-acceptance-") as temporary_name:
        temporary = Path(temporary_name)
        with NvidiaSmiSampler(interval=.5) as sampler:
            gate, gate_attempts = run_with_retry(client, project["id"], GATE, 10, temporary, args.timeout, sampler)
            report["samples"].extend(gate_attempts)
            report["gate_passed"] = bool(gate.get("technical_passed"))
            if report["gate_passed"] and not args.gate_only:
                for case in CASES:
                    _, attempts = run_with_retry(client, project["id"], case, 100, temporary, args.timeout, sampler)
                    report["samples"].extend(attempts)
                report["cancel_recovery"] = run_cancel_recovery(client, project["id"], args.timeout)
            report["gpu"] = sampler.summary()
    client.post("/runtime/release")
    final_by_case: dict[str, dict[str, Any]] = {}
    for sample in report["samples"]:
        final_by_case[str(sample.get("case_id"))] = sample
    required = list(final_by_case.values())
    report["status"] = "passed" if report.get("gate_passed") and all(sample.get("technical_passed") for sample in required) and (args.gate_only or (report.get("cancel_recovery") or {}).get("passed")) else "failed"
    report["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VoiceGrid MOSS-SoundEffect-v2.0 acceptance runner")
    parser.add_argument("--base-url", default="http://127.0.0.1:7862")
    parser.add_argument("--project-name", default="音效生成验收_20260813")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--gate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        print(json.dumps(dry_run_plan(args.project_name, args.base_url), ensure_ascii=False, indent=2))
        return 0
    try:
        report = execute(args)
    except Exception as exc:
        report = {
            "title": "声格 VoiceGrid MOSS-SoundEffect-v2.0 硬件验收",
            "status": "failed",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "base_url": args.base_url,
            "project": {"name": args.project_name},
            "samples": [],
            "gpu": {},
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path, markdown_path = write_report(report, args.report_dir, f"sound-effect-{stamp}")
    print(json.dumps({"status": report["status"], "json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
