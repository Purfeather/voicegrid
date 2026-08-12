from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
LAB_PROFILE = Path(__file__).resolve().parent / "cache" / "webview2"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def request_json(port: int, path: str, method: str = "GET", timeout: float = .25) -> dict[str, Any] | None:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def create_projects(root: Path, count: int, recovery: bool = False) -> None:
    projects = root / "projects"
    projects.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    for index in range(count):
        project_id = f"{index + 1:032x}"
        project_root = projects / project_id
        project_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 2,
            "id": project_id,
            "name": f"Startup Lab Project {index + 1:03d}",
            "created_at": timestamp,
            "updated_at": timestamp,
            "revision": 1,
            "session_active": bool(recovery and index == 0),
            "recovery_available": False,
            "workspace": {"voice_id": None, "reference_id": None},
        }
        (project_root / "project.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")


def apphang_fingerprints() -> set[str]:
    query = "*[System[(EventID=1001 or EventID=1002)]]"
    try:
        result = subprocess.run(
            ["wevtutil", "qe", "Application", f"/q:{query}", "/f:xml", "/rd:true", "/c:80"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
    except Exception:
        return set()
    events = result.stdout.split("<Event ")
    return {
        hashlib.sha256(event.encode("utf-8", errors="replace")).hexdigest()
        for event in events
        if "AppHang" in event and ("pythonw.exe" in event.lower() or "python.exe" in event.lower())
    }


class WindowProbe:
    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        self.user32.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        self.user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        self.user32.IsWindowVisible.argtypes = (ctypes.c_void_p,)
        self.user32.IsWindowVisible.restype = ctypes.c_bool
        self.user32.GetWindowTextLengthW.argtypes = (ctypes.c_void_p,)
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.EnumWindows.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        self.user32.EnumWindows.restype = ctypes.c_bool
        self.user32.SendMessageTimeoutW.argtypes = (
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
            ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t),
        )
        self.user32.SendMessageTimeoutW.restype = ctypes.c_size_t
        self.user32.IsHungAppWindow.argtypes = (ctypes.c_void_p,)
        self.user32.IsHungAppWindow.restype = ctypes.c_bool
        self.user32.PostMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
        self.user32.PostMessageW.restype = ctypes.c_bool

    def find(self, pid: int, title: str = "") -> int | None:
        found: list[int] = []

        def callback(hwnd: int, _: int) -> bool:
            target = ctypes.c_ulong()
            self.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(target))
            length = self.user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
            buffer = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(ctypes.c_void_p(hwnd), buffer, length + 1)
            title_matches = bool(title and buffer.value == title)
            if (target.value == pid or title_matches) and self.user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
                found.append(int(hwnd))
                return False
            return True

        self.user32.EnumWindows(self.callback_type(callback), 0)
        return found[0] if found else None

    def responsive(self, hwnd: int) -> tuple[bool, float]:
        result = ctypes.c_size_t()
        started = time.perf_counter()
        responded = self.user32.SendMessageTimeoutW(ctypes.c_void_p(hwnd), 0, 0, 0, 0x0002, 250, ctypes.byref(result))
        latency_ms = (time.perf_counter() - started) * 1000
        hung = bool(self.user32.IsHungAppWindow(ctypes.c_void_p(hwnd)))
        return bool(responded) and not hung and latency_ms <= 250, latency_ms

    def close(self, hwnd: int) -> None:
        self.user32.PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)


def read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def run_case(
    name: str,
    project_count: int,
    profile: Path | None = None,
    fault: str = "",
    corrupt_database: bool = False,
    recovery: bool = False,
    test_wake: bool = False,
    timeout: float = 15.0,
) -> dict[str, Any]:
    if not PYTHONW.is_file():
        raise FileNotFoundError(PYTHONW)
    with tempfile.TemporaryDirectory(prefix="moss-startup-lab-", ignore_cleanup_errors=True) as temporary:
        runtime_root = Path(temporary)
        create_projects(runtime_root, project_count, recovery=recovery)
        data_dir = runtime_root / "data"
        logs_dir = runtime_root / "logs"
        data_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        if corrupt_database:
            (data_dir / "app.db").write_bytes(b"startup-lab-corrupt-database")
        port = free_port()
        trace_path = logs_dir / "trace.jsonl"
        profile_path = profile or runtime_root / "webview-profile"
        window_title = f"LongRong Startup Lab {port}"
        env = os.environ.copy()
        env.update({
            "MOSS_TTS_RUNTIME_ROOT": str(runtime_root),
            "MOSS_TTS_DATA_DIR": str(data_dir),
            "MOSS_TTS_PROJECTS_DIR": str(runtime_root / "projects"),
            "MOSS_TTS_OUTPUTS_DIR": str(runtime_root / "outputs"),
            "MOSS_TTS_REFERENCES_DIR": str(runtime_root / "references"),
            "MOSS_TTS_LOGS_DIR": str(logs_dir),
            "MOSS_TTS_WEBVIEW_PROFILE": str(profile_path),
            "MOSS_TTS_TRACE_PATH": str(trace_path),
            "MOSS_TTS_PORT": str(port),
            "MOSS_TTS_MUTEX_NAME": rf"Local\LongRongStartupLab{port}",
            "MOSS_TTS_WINDOW_TITLE": window_title,
            "MOSS_TTS_STARTUP_WATCHDOG": "1",
        })
        if fault:
            env["MOSS_TTS_FAULT"] = fault
        held_port = None
        if fault == "port_occupied":
            held_port = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            held_port.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            held_port.bind(("127.0.0.1", port))
            held_port.listen(1)
        before_wer = apphang_fingerprints()
        started = time.perf_counter()
        process = subprocess.Popen([str(PYTHONW), "-m", "desktop.host"], cwd=ROOT, env=env)
        probe = WindowProbe()
        window_seen_ms: float | None = None
        ready_ms: float | None = None
        max_latency_ms = 0.0
        hung_samples = 0
        status: dict[str, Any] | None = None
        hwnd: int | None = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and process.poll() is None:
            hwnd = probe.find(process.pid, window_title)
            if hwnd is not None:
                if window_seen_ms is None:
                    window_seen_ms = (time.perf_counter() - started) * 1000
                responsive, latency = probe.responsive(hwnd)
                max_latency_ms = max(max_latency_ms, latency)
                if not responsive:
                    hung_samples += 1
            status = request_json(port, "/api/v2/desktop/status")
            if status and status.get("ready"):
                ready_ms = (time.perf_counter() - started) * 1000
                break
            trace = read_trace(trace_path)
            if any(record.get("phase") == "failed" for record in trace):
                # Fast failures can be reported before the helper splash has
                # finished creating its HWND. Keep probing long enough to
                # verify that the diagnostic window itself is responsive.
                if hwnd is not None:
                    break
            time.sleep(.1)

        wake_ms = None
        health_latency_ms: list[float] = []
        health_ok = False
        if ready_ms is not None:
            for _ in range(10):
                health_started = time.perf_counter()
                health = request_json(port, "/api/v2/health", timeout=.25)
                health_latency_ms.append((time.perf_counter() - health_started) * 1000)
                health_ok = health_ok or bool(health and health.get("api") == "ready")
        if ready_ms is not None and test_wake:
            wake_started = time.perf_counter()
            duplicate = subprocess.Popen([str(PYTHONW), "-m", "desktop.host"], cwd=ROOT, env=env)
            try:
                duplicate.wait(timeout=2)
                wake_ms = (time.perf_counter() - wake_started) * 1000
            except subprocess.TimeoutExpired:
                duplicate.terminate()
                duplicate.wait(timeout=2)
                wake_ms = 2000.0

        if held_port is not None:
            held_port.close()
        if process.poll() is None:
            if ready_ms is not None:
                request_json(port, "/api/v2/desktop/action/exit", method="POST", timeout=.6)
            elif hwnd is not None:
                probe.close(hwnd)
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            if hwnd is not None:
                probe.close(hwnd)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=3)
        time.sleep(.5)
        port_released = True
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_check:
                port_check.bind(("127.0.0.1", port))
        except OSError:
            port_released = False
        after_wer = apphang_fingerprints()
        trace = read_trace(trace_path)
        startup_log_path = logs_dir / "desktop-startup.log"
        startup_log_tail = startup_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-12:] if startup_log_path.is_file() else []
        thread_stack_tail: list[str] = []
        for record in trace:
            if record.get("event") != "thread_dump" or not record.get("path"):
                continue
            stack_path = Path(str(record["path"]))
            if stack_path.is_file():
                thread_stack_tail = stack_path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
        internal_max = max((float(record.get("max_latency_ms", 0)) for record in trace if record.get("event") == "watchdog_complete"), default=0.0)
        result = {
            "name": name,
            "projects": project_count,
            "fault": fault or None,
            "window_seen_ms": round(window_seen_ms, 2) if window_seen_ms is not None else None,
            "ready_ms": round(ready_ms, 2) if ready_ms is not None else None,
            "wake_ms": round(wake_ms, 2) if wake_ms is not None else None,
            "health_max_ms": round(max(health_latency_ms), 2) if health_latency_ms else None,
            "health_ok": health_ok,
            "external_max_latency_ms": round(max_latency_ms, 2),
            "internal_max_latency_ms": round(internal_max, 2),
            "hung_samples": hung_samples,
            "apphang_events_added": len(after_wer - before_wer),
            "port_released": port_released,
            "exit_code": process.returncode,
            "trace_phases": [record.get("phase") for record in trace if record.get("event") == "phase"],
            "trace_events": [
                {"event": record.get("event"), "phase": record.get("phase"), "elapsed_ms": record.get("elapsed_ms"), "message": record.get("message")}
                for record in trace[-20:]
            ],
            "startup_log_tail": startup_log_tail,
            "thread_stack_tail": thread_stack_tail,
            "thread_dumps": sum(record.get("event") == "thread_dump" for record in trace),
        }
        normal_case = not fault or fault in {"hardware_failure", "tray_failure"}
        result["passed"] = bool(
            window_seen_ms is not None
            and window_seen_ms <= 1500
            and hung_samples == 0
            and max_latency_ms <= 250
            and result["apphang_events_added"] == 0
            and port_released
            and (ready_ms is not None and ready_ms <= 5000 if normal_case else True)
            and (health_ok and max(health_latency_ms) <= 50 if normal_case else True)
            and (wake_ms is None or wake_ms <= 500)
        )
        return result


def run_quick() -> list[dict[str, Any]]:
    return [run_case(f"projects-{count}", count, recovery=count == 1, test_wake=count == 1) for count in (0, 1, 50, 200)]


def run_faults() -> list[dict[str, Any]]:
    return [
        run_case("database-recovery", 1, corrupt_database=True),
        run_case("port-occupied", 1, fault="port_occupied"),
        run_case("backend-import", 1, fault="backend_import"),
        run_case("hardware-failure", 1, fault="hardware_failure"),
        run_case("tray-failure", 1, fault="tray_failure"),
        run_case("webview-missing", 0, fault="webview_missing"),
    ]


def run_acceptance() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="moss-startup-profile-", ignore_cleanup_errors=True) as profile_root:
        shared_profile = Path(profile_root) / "profile"
        for index in range(20):
            results.append(run_case(f"cold-{index + 1:02d}", 1, test_wake=False))
        for index in range(20):
            results.append(run_case(f"warm-{index + 1:02d}", 1, profile=shared_profile, test_wake=False))
        for index in range(20):
            results.append(run_case(f"wake-{index + 1:02d}", 1, profile=shared_profile, test_wake=True))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="LongRong AI Studio startup responsiveness lab")
    parser.add_argument("--suite", choices=("single", "quick", "faults", "acceptance"), default="quick")
    parser.add_argument("--projects", type=int, default=1)
    parser.add_argument("--reuse-profile", action="store_true")
    args = parser.parse_args()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now().isoformat(timespec="seconds")
    if args.suite == "single":
        cases = [run_case(f"projects-{args.projects}", max(0, args.projects), profile=LAB_PROFILE if args.reuse_profile else None, test_wake=True)]
    elif args.suite == "quick":
        cases = run_quick()
    elif args.suite == "faults":
        cases = run_faults()
    else:
        cases = run_acceptance()
    payload = {
        "suite": args.suite,
        "started_at": started,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "passed": all(case["passed"] for case in cases),
        "cases": cases,
    }
    target = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{args.suite}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    print(f"Result: {target}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
