from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, replace
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


MODULE_ID = "voice_design"
DEFAULT_SEED = 2026
RETRY_SEED = 2027
DEFAULT_REPORT_DIR = Path(__file__).resolve().parents[1] / "tests" / "reports"


@dataclass(frozen=True)
class VoiceGeneratorCase:
    case_id: str
    title: str
    text: str
    instruction: str
    gate: bool = False


CASES = (
    VoiceGeneratorCase(
        "A",
        "中文老年男性精度技术闸门",
        "哎呀，我的老腰啊，这年纪大了就是不行了。",
        "疲惫沙哑的老年男性声音缓慢抱怨，带有轻微呻吟。",
        gate=True,
    ),
    VoiceGeneratorCase(
        "B",
        "中文明亮年轻女性",
        "各位朋友，今天我们一起去看看清晨海边最明亮的风景。",
        "明亮清澈的年轻女性，轻快而有朝气。",
    ),
    VoiceGeneratorCase(
        "C",
        "中文中年男性纪录片旁白",
        "山谷里的雾气正在散去，第一束阳光越过山脊，照亮了沉睡的村庄。",
        "温暖沉稳的中年男性纪录片旁白。",
    ),
    VoiceGeneratorCase(
        "D",
        "英文美式酒馆老板",
        "Hey there, stranger! What brings you to our humble town?",
        "Hearty, jovial American tavern owner's voice, warmly welcoming with a slightly gruff, friendly tone.",
    ),
)


DEFAULT_PARAMETERS = {
    "audio_temperature": 1.5,
    "audio_top_p": 0.6,
    "audio_top_k": 50,
    "audio_repetition_penalty": 1.1,
    "max_new_tokens": 4096,
    "seed": DEFAULT_SEED,
}


def workspace_for(case: VoiceGeneratorCase, seed: int, max_new_tokens: int = 4096) -> dict[str, Any]:
    parameters = {**DEFAULT_PARAMETERS, "seed": seed, "max_new_tokens": max_new_tokens}
    return {
        "mode": "freeform",
        "text": case.text,
        "composer": {},
        "prompt_preview": "",
        "instruction": case.instruction,
        "parameters": parameters,
    }


def dry_run_plan(project_name: str, base_url: str, include_cancel_recovery: bool) -> dict[str, Any]:
    return {
        "tool": "voice_generator_acceptance",
        "dry_run": True,
        "project_name": project_name,
        "base_url": base_url,
        "module": MODULE_ID,
        "default_seed": DEFAULT_SEED,
        "technical_retry_seed": RETRY_SEED,
        "cases": [{**asdict(case), "workspace": workspace_for(case, DEFAULT_SEED)} for case in CASES],
        "cancel_recovery": include_cancel_recovery,
        "rules": {
            "a_gate_stops_remaining_cases": True,
            "single_technical_retry": True,
            "artifacts_downloaded_to_temporary_directory": True,
            "shared_voice_saved_through_api_only": True,
        },
    }


def precision_gate_passed(sample: dict[str, Any], runtime: dict[str, Any], expected_dtype: str = "float32") -> bool:
    if sample.get("task_status") != "completed" or not (sample.get("wav") or {}).get("passed"):
        return False
    device = str(runtime.get("device") or "").lower()
    dtype = str(runtime.get("dtype") or "").lower().replace("torch.", "")
    sampling_dtype = str(runtime.get("sampling_dtype") or "").lower().replace("torch.", "")
    projection_dtype = str(runtime.get("projection_dtype") or "").lower().replace("torch.", "")
    expected = expected_dtype.lower().replace("torch.", "")
    expected_sampling = "float32"
    expected_projection = "float32" if expected == "float16" else expected
    return (
        "cuda" in device
        and dtype == expected
        and sampling_dtype == expected_sampling
        and projection_dtype == expected_projection
    )


def _progress(task: dict[str, Any]) -> None:
    progress = float(task.get("progress") or 0.0) * 100.0
    print(f"[{task.get('status', '?'):>9}] {progress:6.1f}% {task.get('message', '')}", flush=True)


def _stage_timings(timeline: list[dict[str, Any]]) -> dict[str, float | None]:
    def first_at(progress: float) -> float | None:
        return next(
            (float(item["elapsed_seconds"]) for item in timeline if float(item.get("progress") or 0.0) >= progress),
            None,
        )

    loaded = first_at(0.676)
    generation_started = first_at(0.714)
    decode_started = first_at(0.883)
    completed = first_at(1.0)

    def delta(end: float | None, start: float | None) -> float | None:
        return round(end - start, 3) if end is not None and start is not None else None

    return {
        "load_seconds": loaded,
        "instruction_seconds": delta(generation_started, loaded),
        "generation_seconds": delta(decode_started, generation_started),
        "decode_and_write_seconds": delta(completed, decode_started),
        "total_seconds": completed,
    }


def _history_record(client: JsonHttpClient, project_id: str, output_id: str) -> dict[str, Any]:
    history = client.get(f"/projects/{project_id}/history", {"module": MODULE_ID})
    return next((record for record in history if record.get("id") == output_id), {})


def run_case(
    client: JsonHttpClient,
    project_id: str,
    case: VoiceGeneratorCase,
    seed: int,
    attempt: int,
    temporary_directory: Path,
    timeout: float,
    sampler: NvidiaSmiSampler | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    gpu_mark = sampler.mark() if sampler is not None else 0
    workspace = workspace_for(case, seed)
    result: dict[str, Any] = {
        "case_id": case.case_id,
        "title": case.title,
        "attempt": attempt,
        "seed": seed,
        "task_status": "not_started",
        "technical_passed": False,
        "failures": [],
        "workspace": workspace,
    }
    try:
        timeline: list[dict[str, Any]] = []

        def record_progress(task: dict[str, Any]) -> None:
            timeline.append({
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "status": task.get("status"),
                "progress": float(task.get("progress") or 0.0),
                "message": task.get("message"),
            })
            if float(task.get("progress") or 0.0) >= 0.676 and "runtime_loaded" not in result:
                try:
                    result["runtime_loaded"] = client.get("/runtime")
                except Exception as exc:
                    result["runtime_snapshot_error"] = f"{type(exc).__name__}: {exc}"
            _progress(task)

        saved_project = save_module_workspace(client, project_id, MODULE_ID, workspace)
        result["project_revision"] = saved_project["revision"]
        task = create_module_task(client, project_id, MODULE_ID, workspace)
        result["task_id"] = task["id"]
        terminal = poll_task(client, task["id"], timeout=timeout, interval=0.2, on_update=record_progress)
        result["timeline"] = timeline
        result["stage_timings"] = _stage_timings(timeline)
        result["task_status"] = terminal.get("status")
        result["task_error"] = terminal.get("error")
        result["task_message"] = terminal.get("message")
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if sampler is not None:
            result["gpu"] = sampler.summary_since(gpu_mark)
        if terminal.get("status") != "completed" or not terminal.get("result_id"):
            result["failures"] = ["task_not_completed"]
            return result
        output_id = str(terminal["result_id"])
        result["output_id"] = output_id
        result["output"] = _history_record(client, project_id, output_id)
        local_path = temporary_directory / f"{case.case_id.lower()}-attempt-{attempt}.wav"
        result["download"] = client.download(f"/artifacts/{output_id}", local_path, {"download": True})
        result["wav"] = inspect_wav(
            local_path,
            WavExpectations(
                format="WAV",
                subtype="PCM_24",
                sample_rate=24000,
                channels=1,
                maximum_duration=180.0,
                maximum_clipping_ratio=0.005,
            ),
        )
        result["technical_passed"] = bool(result["wav"]["passed"])
        result["failures"] = list(result["wav"]["failures"])
        return result
    except Exception as exc:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if sampler is not None:
            result["gpu"] = sampler.summary_since(gpu_mark)
        result["failures"] = ["exception"]
        result["exception"] = f"{type(exc).__name__}: {exc}"
        return result


def run_case_with_retry(
    client: JsonHttpClient,
    project_id: str,
    case: VoiceGeneratorCase,
    temporary_directory: Path,
    timeout: float,
    sampler: NvidiaSmiSampler | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    attempts = [run_case(client, project_id, case, DEFAULT_SEED, 1, temporary_directory, timeout, sampler)]
    retryable_technical_failure = (
        attempts[0].get("task_status") == "completed"
        and bool(attempts[0].get("wav"))
        and not attempts[0]["technical_passed"]
    )
    if retryable_technical_failure:
        attempts.append(run_case(client, project_id, case, RETRY_SEED, 2, temporary_directory, timeout, sampler))
    return attempts[-1], attempts


def run_cancel_recovery(
    client: JsonHttpClient,
    project_id: str,
    temporary_directory: Path,
    timeout: float,
) -> dict[str, Any]:
    long_case = replace(
        CASES[0],
        case_id="CANCEL",
        title="长任务取消",
        text="这是一段用于测试取消与工作进程恢复能力的长台词。" * 24,
        gate=False,
    )
    task = create_module_task(client, project_id, MODULE_ID, workspace_for(long_case, DEFAULT_SEED, max_new_tokens=8192))
    reached = wait_for_task_progress(client, task["id"], 0.75, timeout=min(timeout, 180.0))
    cancelled = cancel_task_and_wait(client, task["id"], timeout=min(timeout, 180.0)) if reached.get("status") == "running" else reached
    recovery_case = replace(CASES[0], case_id="RECOVERY", title="取消后的短句恢复", gate=False)
    recovered, attempts = run_case_with_retry(client, project_id, recovery_case, temporary_directory, timeout)
    return {
        "cancel_task_id": task["id"],
        "cancel_status": cancelled.get("status"),
        "cancel_message": cancelled.get("message"),
        "cancel_error": cancelled.get("error"),
        "cancel_passed": cancelled.get("status") == "cancelled",
        "recovery_passed": bool(recovered.get("technical_passed")),
        "recovery_attempts": attempts,
    }


def run_cancel_recovery_isolated(
    client: JsonHttpClient,
    project_name: str,
    temporary_directory: Path,
    timeout: float,
) -> dict[str, Any]:
    project, _ = get_or_create_project(client, project_name)
    try:
        return {"project_id": project["id"], **run_cancel_recovery(
            client, project["id"], temporary_directory, timeout
        )}
    finally:
        client.delete(f"/projects/{project['id']}")


def verify_shared_voice_in_speech(
    client: JsonHttpClient,
    project_id: str,
    voice_id: str,
    temporary_directory: Path,
    timeout: float,
) -> dict[str, Any]:
    project = client.get(f"/projects/{project_id}", {"begin_session": False})
    workspace = dict(project["workspaces"]["speech"])
    workspace.update({
        "text": "你好，这是一条使用新设计音色完成的语音合成链路验证。",
        "language": "Chinese",
        "style": "自然影视",
        "instruction": "自然、清晰、沉稳，保持参考音色特征，语速适中。",
        "reference_id": None,
        "voice_id": voice_id,
        "reference_trim_start": 0.0,
        "reference_trim_end": None,
    })
    workspace["output_profile"] = {
        **workspace["output_profile"],
        "format": "WAV",
        "sample_rate": 48000,
        "bit_depth": 24,
        "channels": 1,
    }
    saved = save_module_workspace(client, project_id, "speech", workspace)
    task = create_module_task(client, project_id, "speech", workspace)
    terminal = poll_task(client, task["id"], timeout=timeout, on_update=_progress)
    result: dict[str, Any] = {
        "task_id": task["id"],
        "project_revision": saved["revision"],
        "status": terminal.get("status"),
        "error": terminal.get("error"),
        "result_id": terminal.get("result_id"),
        "voice_id": voice_id,
    }
    if terminal.get("status") != "completed" or not terminal.get("result_id"):
        result["passed"] = False
        return result
    local_path = temporary_directory / "speech-link.wav"
    result["download"] = client.download(
        f"/artifacts/{terminal['result_id']}", local_path, {"download": True}
    )
    result["wav"] = inspect_wav(
        local_path,
        WavExpectations(format="WAV", subtype="PCM_24", sample_rate=48000, channels=1),
    )
    result["passed"] = bool(result["wav"]["passed"])
    return result


def execute_case_matrix(
    client: JsonHttpClient,
    project_id: str,
    temporary_directory: Path,
    timeout: float,
    expected_dtype: str,
    sampler: NvidiaSmiSampler | None = None,
    gate_only: bool = False,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    final_samples: list[dict[str, Any]] = []
    gate_runtime: dict[str, Any] | None = None
    gate_passed: bool | None = None
    for case in CASES:
        final, attempts = run_case_with_retry(client, project_id, case, temporary_directory, timeout, sampler)
        samples.extend(attempts)
        final_samples.append(final)
        if case.gate:
            gate_runtime = final.get("runtime_loaded") or client.get("/runtime")
            gate_passed = precision_gate_passed(final, gate_runtime, expected_dtype)
            if not gate_passed:
                break
            if gate_only:
                break
    return {
        "samples": samples,
        "final_samples": final_samples,
        "a_gate_runtime": gate_runtime,
        "a_gate_passed": gate_passed,
    }


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    report: dict[str, Any] = {
        "title": "MOSS-VoiceGenerator Acceptance Report",
        "tool": "voice_generator_acceptance",
        "status": "running",
        "started_at": started_at,
        "finished_at": "",
        "base_url": args.base_url,
        "project": {"name": args.project_name},
        "samples": [],
        "errors": [],
    }
    client = JsonHttpClient(args.base_url, timeout=args.http_timeout)
    sampler = NvidiaSmiSampler(interval=args.gpu_interval).start()
    project_id: str | None = None
    api_reachable = False
    try:
        health = client.get("/health")
        api_reachable = True
        report["health"] = health
        if not health.get("ok"):
            raise RuntimeError("VoiceGrid API is not ready")
        detect_started = time.monotonic()
        descriptor = client.post(f"/modules/{MODULE_ID}/detect")
        report["offline_detect_seconds"] = round(time.monotonic() - detect_started, 3)
        report["module"] = descriptor
        if not descriptor or not descriptor.get("installed") or not descriptor.get("engine_available"):
            raise RuntimeError("MOSS-VoiceGenerator module is not installed and ready")
        report["metrics_before"] = client.get("/system/metrics")
        project, created = get_or_create_project(client, args.project_name)
        project_id = str(project["id"])
        report["project"] = {"id": project["id"], "name": project["name"], "created": created}

        with tempfile.TemporaryDirectory(prefix="voicegrid-voice-generator-acceptance-") as temporary:
            temporary_directory = Path(temporary)
            matrix = execute_case_matrix(
                client,
                project["id"],
                temporary_directory,
                args.task_timeout,
                args.expected_dtype,
                sampler,
                args.a_gate_only,
            )
            report["samples"] = matrix["samples"]
            report["a_gate_runtime"] = matrix["a_gate_runtime"]
            report["a_gate_passed"] = matrix["a_gate_passed"]
            final_samples = matrix["final_samples"]
            if not report["a_gate_passed"]:
                report["status"] = "failed_at_a_gate"
            for sample in final_samples:
                if sample.get("case_id") != "A" and not sample.get("technical_passed"):
                    report["errors"].append(f"Case {sample.get('case_id')} failed after one technical retry")

            if report.get("a_gate_passed") and args.cancel_recovery:
                report["cancel_recovery"] = run_cancel_recovery_isolated(
                    client,
                    f"{args.project_name}_取消恢复",
                    temporary_directory,
                    args.task_timeout,
                )

            successful = [sample for sample in final_samples if sample.get("technical_passed") and sample.get("output_id")]
            if report.get("a_gate_passed") and args.save_voice_name and successful:
                selected = next(
                    (sample for sample in successful if sample.get("case_id") == args.save_voice_case),
                    successful[-1],
                )
                voice = client.post(
                    f"/voice-design/outputs/{selected['output_id']}/save-as-voice",
                    {"name": args.save_voice_name},
                )
                report["saved_voice"] = voice
                report["saved_voice_case"] = selected["case_id"]
                if args.verify_speech:
                    report["speech_link"] = verify_shared_voice_in_speech(
                        client,
                        project["id"],
                        voice["id"],
                        temporary_directory,
                        args.task_timeout,
                    )
                if args.remove_saved_voice:
                    client.delete(f"/voices/{voice['id']}", {"delete_file": True})
                    report["saved_voice_removed"] = True

        if report["status"] == "running":
            case_failures = [sample for sample in final_samples if not sample.get("technical_passed")]
            cancel_result = report.get("cancel_recovery") or {}
            cancel_failed = args.cancel_recovery and not (
                cancel_result.get("cancel_passed") and cancel_result.get("recovery_passed")
            )
            speech_failed = args.verify_speech and not (report.get("speech_link") or {}).get("passed")
            report["status"] = "failed" if case_failures or cancel_failed or speech_failed else "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if project_id is not None:
            try:
                client.post(f"/projects/{project_id}/close")
                report["project_closed"] = True
            except Exception as exc:
                report["errors"].append(f"Project close failed: {type(exc).__name__}: {exc}")
        if api_reachable and not args.keep_runtime:
            try:
                report["runtime_after_release"] = client.post("/runtime/release")
                time.sleep(2.0)
                report["metrics_after_release"] = client.get("/system/metrics")
            except Exception as exc:
                report["errors"].append(f"Runtime release failed: {type(exc).__name__}: {exc}")
        if report["errors"] and report["status"] == "passed":
            report["status"] = "failed"
        report["gpu"] = sampler.stop()
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MOSS-VoiceGenerator API acceptance runner")
    parser.add_argument("--base-url", default="http://127.0.0.1:7862", help="VoiceGrid server URL or /api/v2 base URL")
    parser.add_argument("--project-name", default="音色设计验收_20260812")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without calling the API")
    parser.add_argument("--cancel-recovery", action="store_true", help="Cancel a long task and verify a short recovery task")
    parser.add_argument("--save-voice-name", default="验收音色_20260812_纪录片", help="Save the selected successful output to the shared voice library")
    parser.add_argument("--save-voice-case", default="C", choices=("A", "B", "C", "D"))
    parser.add_argument("--verify-speech", action="store_true", help="Use the saved voice in a speech synthesis task")
    parser.add_argument("--remove-saved-voice", action="store_true", help="Delete the shared test voice through the API after validation")
    parser.add_argument("--expected-dtype", default="float32", choices=("float16", "bfloat16", "float32"))
    parser.add_argument("--task-timeout", type=float, default=3600.0)
    parser.add_argument("--http-timeout", type=float, default=30.0)
    parser.add_argument("--gpu-interval", type=float, default=1.0)
    parser.add_argument("--keep-runtime", action="store_true", help="Keep the optional model process after the run")
    parser.add_argument("--a-gate-only", action="store_true", help="Run only the precision technical gate sample")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.dry_run:
        print(json.dumps(dry_run_plan(args.project_name, args.base_url, args.cancel_recovery), ensure_ascii=False, indent=2))
        return 0
    report = run_acceptance(args)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path, markdown_path = write_report(report, args.report_dir, f"voice-generator-{stamp}")
    print(f"JSON report: {json_path.resolve()}")
    print(f"Markdown report: {markdown_path.resolve()}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
