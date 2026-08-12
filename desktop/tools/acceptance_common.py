from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import soundfile as sf


TERMINAL_TASK_STATES = {"completed", "failed", "cancelled", "interrupted"}


class ApiError(RuntimeError):
    def __init__(self, method: str, url: str, status: int | None, detail: str) -> None:
        self.method = method
        self.url = url
        self.status = status
        self.detail = detail
        label = f"HTTP {status}" if status is not None else "network error"
        super().__init__(f"{method} {url}: {label}: {detail}")


class JsonHttpClient:
    """Small UTF-8 JSON client for the local VoiceGrid API."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        normalized = base_url.rstrip("/")
        if not normalized.endswith("/api/v2"):
            normalized += "/api/v2"
        self.base_url = normalized
        self.timeout = timeout

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            values = {key: str(value).lower() if isinstance(value, bool) else value for key, value in query.items() if value is not None}
            url += "?" + urllib.parse.urlencode(values)
        return url

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        query: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        url = self._url(path, query)
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read()
                if response.status == 204 or not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            detail = raw.decode("utf-8", errors="replace")
            try:
                message = json.loads(detail)
                detail = str(message.get("detail") or message)
            except (json.JSONDecodeError, AttributeError):
                pass
            raise ApiError(method.upper(), url, exc.code, detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApiError(method.upper(), url, None, str(exc)) from exc

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, query=query)

    def post(self, path: str, payload: Any | None = None, query: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, payload=payload, query=query)

    def patch(self, path: str, payload: Any | None = None, query: dict[str, Any] | None = None) -> Any:
        return self.request("PATCH", path, payload=payload, query=query)

    def delete(self, path: str, query: dict[str, Any] | None = None) -> Any:
        return self.request("DELETE", path, query=query)

    def download(self, path: str, destination: Path, query: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self._url(path, query)
        request = urllib.request.Request(url, headers={"Accept": "audio/wav, application/octet-stream"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=max(self.timeout, 120.0)) as response:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as handle:
                    while chunk := response.read(1024 * 1024):
                        handle.write(chunk)
                return {
                    "url": url,
                    "bytes": destination.stat().st_size,
                    "content_type": response.headers.get("Content-Type", ""),
                    "content_disposition": response.headers.get("Content-Disposition", ""),
                }
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError("GET", url, exc.code, detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApiError("GET", url, None, str(exc)) from exc


def get_or_create_project(client: JsonHttpClient, name: str, language: str = "Chinese") -> tuple[dict[str, Any], bool]:
    matches = [project for project in client.get("/projects") if project.get("name") == name]
    if matches:
        selected = sorted(matches, key=lambda item: str(item.get("updated_at", "")), reverse=True)[0]
        return client.get(f"/projects/{selected['id']}", {"begin_session": False}), False
    return client.post("/projects", {"name": name, "language": language}), True


def create_module_task(client: JsonHttpClient, project_id: str, module: str, workspace: dict[str, Any]) -> dict[str, Any]:
    return client.post("/module-tasks", {"project_id": project_id, "module": module, "workspace": workspace})


def save_module_workspace(
    client: JsonHttpClient,
    project_id: str,
    module: str,
    workspace: dict[str, Any],
) -> dict[str, Any]:
    project = client.get(f"/projects/{project_id}", {"begin_session": False})
    return client.patch(
        f"/projects/{project_id}",
        {"revision": project["revision"], "module": module, "workspace": workspace},
    )


def poll_task(
    client: JsonHttpClient,
    task_id: str,
    timeout: float = 3600.0,
    interval: float = 1.0,
    on_update: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    previous: tuple[Any, ...] | None = None
    while True:
        task = client.get(f"/tasks/{task_id}")
        signature = (task.get("status"), task.get("progress"), task.get("message"), task.get("error"))
        if on_update is not None and signature != previous:
            on_update(task)
        previous = signature
        if task.get("status") in TERMINAL_TASK_STATES:
            return task
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Task {task_id} did not finish within {timeout:.0f} seconds")
        time.sleep(max(0.1, interval))


def cancel_task_and_wait(
    client: JsonHttpClient,
    task_id: str,
    timeout: float = 120.0,
    interval: float = 0.5,
) -> dict[str, Any]:
    client.post(f"/tasks/{task_id}/cancel")
    return poll_task(client, task_id, timeout=timeout, interval=interval)


def wait_for_task_status(
    client: JsonHttpClient,
    task_id: str,
    statuses: Iterable[str],
    timeout: float = 120.0,
    interval: float = 0.5,
) -> dict[str, Any]:
    expected = set(statuses)
    deadline = time.monotonic() + timeout
    while True:
        task = client.get(f"/tasks/{task_id}")
        if task.get("status") in expected or task.get("status") in TERMINAL_TASK_STATES:
            return task
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Task {task_id} did not reach {sorted(expected)}")
        time.sleep(max(0.1, interval))


def wait_for_task_progress(
    client: JsonHttpClient,
    task_id: str,
    minimum_progress: float,
    timeout: float = 120.0,
    interval: float = 0.5,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        task = client.get(f"/tasks/{task_id}")
        if float(task.get("progress") or 0.0) >= minimum_progress:
            return task
        if task.get("status") in TERMINAL_TASK_STATES:
            return task
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Task {task_id} did not reach progress {minimum_progress:.3f}")
        time.sleep(max(0.1, interval))


@dataclass(frozen=True)
class WavExpectations:
    format: str = "WAV"
    subtype: str = "PCM_24"
    sample_rate: int | None = None
    channels: int | None = None
    minimum_duration: float = 0.25
    maximum_duration: float | None = None
    maximum_clipping_ratio: float = 0.005
    minimum_rms_dbfs: float = -60.0
    maximum_silence_ratio: float = 0.85


def _frame_silence_ratio(audio: np.ndarray, sample_rate: int, threshold_dbfs: float = -45.0) -> float:
    mono = np.mean(audio, axis=1)
    frame_size = max(256, int(sample_rate * 0.05))
    hop = max(128, frame_size // 2)
    if mono.size == 0:
        return 1.0
    if mono.size < frame_size:
        frames = [mono]
    else:
        frames = [mono[start:start + frame_size] for start in range(0, mono.size - frame_size + 1, hop)]
    rms = np.asarray([math.sqrt(float(np.mean(np.square(frame), dtype=np.float64)) + 1e-12) for frame in frames])
    dbfs = 20.0 * np.log10(np.maximum(rms, 1e-12))
    return float(np.mean(dbfs < threshold_dbfs))


def inspect_wav(path: Path, expectations: WavExpectations | None = None) -> dict[str, Any]:
    expected = expectations or WavExpectations()
    info = sf.info(str(path))
    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    total_values = int(audio.size)
    finite_mask = np.isfinite(audio)
    nonfinite_count = int(total_values - int(np.count_nonzero(finite_mask)))
    finite_values = audio[finite_mask]
    peak = float(np.max(np.abs(finite_values))) if finite_values.size else 0.0
    clipping_ratio = float(np.mean(np.abs(finite_values) >= 0.999)) if finite_values.size else 0.0
    rms = math.sqrt(float(np.mean(np.square(finite_values), dtype=np.float64))) if finite_values.size else 0.0
    rms_dbfs = 20.0 * math.log10(max(rms, 1e-12))
    silence_ratio = _frame_silence_ratio(np.nan_to_num(audio), sample_rate)
    duration = float(info.frames / info.samplerate) if info.samplerate else 0.0

    checks = {
        "format": info.format.upper() == expected.format.upper(),
        "subtype": info.subtype.upper() == expected.subtype.upper(),
        "sample_rate": expected.sample_rate is None or info.samplerate == expected.sample_rate,
        "channels": expected.channels is None or info.channels == expected.channels,
        "duration_minimum": duration >= expected.minimum_duration,
        "duration_maximum": expected.maximum_duration is None or duration <= expected.maximum_duration,
        "finite_values": nonfinite_count == 0,
        "peak_range": 0.0 < peak <= 1.0,
        "clipping_ratio": clipping_ratio <= expected.maximum_clipping_ratio,
        "rms_level": rms_dbfs >= expected.minimum_rms_dbfs,
        "silence_ratio": silence_ratio <= expected.maximum_silence_ratio,
    }
    return {
        "path_name": path.name,
        "format": info.format,
        "format_info": info.format_info,
        "subtype": info.subtype,
        "subtype_info": info.subtype_info,
        "sample_rate": int(info.samplerate),
        "channels": int(info.channels),
        "frames": int(info.frames),
        "duration_seconds": round(duration, 6),
        "finite": nonfinite_count == 0,
        "nonfinite_count": nonfinite_count,
        "peak": round(peak, 8),
        "peak_dbfs": round(20.0 * math.log10(max(peak, 1e-12)), 3),
        "clipping_ratio": round(clipping_ratio, 8),
        "rms": round(rms, 8),
        "rms_dbfs": round(rms_dbfs, 3),
        "silence_ratio": round(silence_ratio, 8),
        "expectations": asdict(expected),
        "checks": checks,
        "passed": all(checks.values()),
        "failures": [name for name, passed in checks.items() if not passed],
    }


class NvidiaSmiSampler:
    QUERY = "timestamp,name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw"

    def __init__(self, interval: float = 1.0) -> None:
        self.interval = max(0.2, interval)
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "NvidiaSmiSampler":
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="acceptance-nvidia-smi", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval * 2))
        return self.summary()

    def _run(self) -> None:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        while not self._stop.is_set():
            try:
                result = subprocess.run(
                    ["nvidia-smi", f"--query-gpu={self.QUERY}", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    creationflags=creationflags,
                )
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or f"nvidia-smi exited with {result.returncode}")
                captured_at = datetime.now().isoformat(timespec="milliseconds")
                for index, line in enumerate(result.stdout.splitlines()):
                    columns = [column.strip() for column in line.split(",")]
                    if len(columns) < 7:
                        continue
                    self.samples.append({
                        "captured_at": captured_at,
                        "gpu_index": index,
                        "device_timestamp": columns[0],
                        "name": columns[1],
                        "memory_used_mib": _number(columns[2]),
                        "memory_total_mib": _number(columns[3]),
                        "utilization_percent": _number(columns[4]),
                        "temperature_c": _number(columns[5]),
                        "power_w": _number(columns[6]),
                    })
            except Exception as exc:
                message = str(exc)
                if not self.errors or self.errors[-1] != message:
                    self.errors.append(message)
            self._stop.wait(self.interval)

    def summary(self) -> dict[str, Any]:
        def maximum(field: str) -> float | None:
            values = [sample[field] for sample in self.samples if isinstance(sample.get(field), (int, float))]
            return max(values) if values else None

        return {
            "available": bool(self.samples),
            "sample_count": len(self.samples),
            "peak_memory_used_mib": maximum("memory_used_mib"),
            "peak_utilization_percent": maximum("utilization_percent"),
            "peak_temperature_c": maximum("temperature_c"),
            "peak_power_w": maximum("power_w"),
            "errors": self.errors,
            "samples": self.samples,
        }

    def mark(self) -> int:
        return len(self.samples)

    def summary_since(self, mark: int) -> dict[str, Any]:
        subset = self.samples[max(0, mark):]

        def maximum(field: str) -> float | None:
            values = [sample[field] for sample in subset if isinstance(sample.get(field), (int, float))]
            return max(values) if values else None

        return {
            "sample_count": len(subset),
            "peak_memory_used_mib": maximum("memory_used_mib"),
            "peak_utilization_percent": maximum("utilization_percent"),
            "peak_temperature_c": maximum("temperature_c"),
            "peak_power_w": maximum("power_w"),
        }

    def __enter__(self) -> "NvidiaSmiSampler":
        return self.start()

    def __exit__(self, *_: Any) -> None:
        self.stop()


def _number(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def write_report(report: dict[str, Any], output_directory: Path, stem: str) -> tuple[Path, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / f"{stem}.json"
    markdown_path = output_directory / f"{stem}.md"
    _atomic_text(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _atomic_text(markdown_path, render_markdown_report(report))
    return json_path, markdown_path


def _atomic_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# {report.get('title', 'VoiceGrid Acceptance Report')}",
        "",
        f"- Status: **{report.get('status', 'unknown')}**",
        f"- Started: `{report.get('started_at', '')}`",
        f"- Finished: `{report.get('finished_at', '')}`",
        f"- Project: `{(report.get('project') or {}).get('name', '')}`",
        f"- API: `{report.get('base_url', '')}`",
        "",
        "## Samples",
        "",
        "| Case | Attempt | Seed | Task | WAV | Duration | Failures |",
        "|---|---:|---:|---|---|---:|---|",
    ]
    for sample in report.get("samples", []):
        wav = sample.get("wav") or {}
        failures = ", ".join(wav.get("failures") or sample.get("failures") or [])
        lines.append(
            f"| {sample.get('case_id', '')} | {sample.get('attempt', '')} | {sample.get('seed', '')} | "
            f"{sample.get('task_status', '')} | {'pass' if wav.get('passed') else 'fail'} | "
            f"{wav.get('duration_seconds', '')} | {failures} |"
        )
    gpu = report.get("gpu") or {}
    lines.extend([
        "",
        "## GPU",
        "",
        f"- Samples: {gpu.get('sample_count', 0)}",
        f"- Peak VRAM: {gpu.get('peak_memory_used_mib', 'n/a')} MiB",
        f"- Peak utilization: {gpu.get('peak_utilization_percent', 'n/a')}%",
        "",
    ])
    if report.get("errors"):
        lines.extend(["## Errors", ""] + [f"- {error}" for error in report["errors"]] + [""])
    return "\n".join(lines)
