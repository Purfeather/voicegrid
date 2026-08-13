from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "desktop" / "frontend"
OUTPUT = FRONTEND / "src" / "api.generated.ts"

sys.path.insert(0, str(ROOT))

from desktop.backend import schemas  # noqa: E402


MODELS = (
    schemas.SynthesisParameters,
    schemas.OutputProfile,
    schemas.WorkspaceDraft,
    schemas.VoicePromptComposer,
    schemas.VoiceDesignParameters,
    schemas.VoiceDesignDraft,
    schemas.SoundEffectParameters,
    schemas.SoundEffectDraft,
    schemas.ProjectWorkspaces,
)


def ts_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(value, ensure_ascii=False) for value in schema["enum"])
    if "anyOf" in schema:
        return " | ".join(ts_type(item) for item in schema["anyOf"])
    kind = schema.get("type")
    if kind == "array":
        return f"Array<{ts_type(schema.get('items', {}))}>"
    if kind == "object":
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            return f"Record<string, {ts_type(additional)}>"
        return "Record<string, unknown>"
    return {"string": "string", "integer": "number", "number": "number", "boolean": "boolean", "null": "null"}.get(kind, "unknown")


def render_model(model: type[Any]) -> str:
    model_schema = model.model_json_schema(ref_template="#/$defs/{model}")
    lines = [f"export interface {model.__name__} {{"]
    for name, field in model_schema.get("properties", {}).items():
        lines.append(f"  {name}: {ts_type(field)};")
    lines.append("}")
    return "\n".join(lines)


SUPPLEMENTAL_CONTRACTS = r'''
export type ModuleId = "speech" | "voice_design" | "sound_effect";
export type SpeedLevel = "慢" | "较慢" | "中等" | "较快" | "快";
export type TaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
export type ModuleInstallState = "not_installed" | "installing" | "repair_required" | "ready" | "failed";

export interface AudioHealth {
  duration: number; sample_rate: number; channels: number; peak_dbfs: number; rms_dbfs: number;
  clipping_ratio: number; snr_db: number; silence_ratio: number; score: number; suitability: string;
  findings: Array<{ level: "success" | "warning" | "error"; message: string }>; waveform: number[];
}
export interface VoiceAsset { id: string; name: string; saved: boolean; created_at: string; artifact_url: string; health: AudioHealth; role?: string; language_accent?: string; gender_age?: string; description?: string; }
export interface StylePreset { name: string; instruction: string; built_in: boolean; updated_at: string; }
export interface ProjectSummary { id: string; name: string; updated_at: string; recovery_available: boolean; output_count: number; voice: string; status: string; }
export interface ProjectDetail extends ProjectSummary { created_at: string; revision: number; workspace: WorkspaceDraft; workspaces: ProjectWorkspaces; history: OutputRecord[]; }
export interface GenerationSnapshot { style: string; instruction: string; reference_audio?: { id: string; name: string; saved: boolean } | null; speed?: "自动" | SpeedLevel; }
export interface VoiceDesignGenerationSnapshot { mode: "composer" | "freeform"; composer: VoicePromptComposer; prompt_preview: string; instruction: string; text: string; parameters: VoiceDesignParameters; model: string; codec: string; }
export interface SoundEffectGenerationSnapshot { prompt: string; seconds: number; num_inference_steps: number; cfg_scale: number; sigma_shift: number; seed: number; model: string; runtime_precision: "float16"; low_vram: true; }
export interface OutputRecord { id: string; task_id: string; filename: string; created_at: string; duration: number; sample_rate: number; channels: number; bit_depth: number; format: string; voice: string; text: string; artifact_url: string; module: ModuleId; kind: "speech_output" | "voice_design_output" | "sound_effect_output"; instruction?: string; favorite?: boolean; generation_snapshot?: GenerationSnapshot | VoiceDesignGenerationSnapshot | SoundEffectGenerationSnapshot; }
export interface TaskRecord { id: string; project_id: string; module: ModuleId; status: TaskStatus; progress: number; message: string; created_at: string; updated_at: string; result_id: string | null; error: string | null; remove_after_stop: boolean; }
export interface TaskRemovalResult { task_id: string; pending: boolean; task: TaskRecord | null; }
export interface ActivityClearResult { tasks_removed: number; outputs_removed: number; }
export interface HardwareMetrics { cpu_percent: number; memory_used_gb: number; memory_total_gb: number; memory_percent: number; gpu_name: string; gpu_percent: number | null; vram_used_gb: number | null; vram_total_gb: number | null; python_version: string; platform: string; timestamp: string; }
export interface RuntimeSnapshot { state: "idle" | "loading" | "loaded" | "running" | "releasing" | "error"; active_model: string | null; active_module?: ModuleId | null; message: string; device: string; dtype: string; attention: string; models: Array<{ key: string; name: string; version: string; installed: boolean; enabled: boolean }>; }
export interface ModelLock { model_id: string; revision: string; file_count: number; total_bytes: number; manifest_sha256: string; }
export interface ModuleDescriptor { id: ModuleId; name: string; model_name: string; model_id: string; codec_id?: string; description: string; disk_gb: number; download_gb: number; required_disk_gb: number; runtime_python: string; runtime_mode: "host" | "isolated"; installed: boolean; model_ready: boolean; runtime_ready: boolean; install_state: ModuleInstallState; install_phase: string; install_progress: number; install_message: string; error: string; missing: string[]; manual_paths: string[]; preview_available: boolean; engine_available: boolean; engine_message?: string; model_locks: ModelLock[]; }
export interface CoreBootstrap { product: string; version: string; languages: Array<{ value: string; label: string }>; model_capabilities: { key: string; name: string; version: string; offline: boolean; lazy_load: boolean }; defaults: { preset: "标准" | "兼容"; parameters: SynthesisParameters }; }
export interface HealthSnapshot { ok: boolean; api: string; database: Record<string, unknown>; project_index: Record<string, unknown>; version: string; }
export interface BootstrapPayload { product: string; version: string; projects: ProjectSummary[]; voices: VoiceAsset[]; styles: StylePreset[]; runtime: RuntimeSnapshot; metrics: HardwareMetrics; languages: Array<{ value: string; label: string }>; modules: ModuleDescriptor[]; }
export interface AppEvent { type: "task.updated" | "task.removed" | "activity.cleared" | "runtime.updated" | "metrics.updated" | "project.saved" | "module.updated" | "voice.updated"; payload: unknown; }
'''.strip()


def generate() -> str:
    source = "\n\n".join(render_model(model) for model in MODELS)
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    return (
        "// AUTO-GENERATED by desktop/tools/generate_api_types.py. DO NOT EDIT.\n"
        f"// Pydantic schema digest: {digest}. Response contracts supplement untyped FastAPI responses.\n\n"
        + source
        + "\n\n"
        + SUPPLEMENTAL_CONTRACTS
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = generate()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != generated:
            print(f"Generated API types are stale: {OUTPUT}", file=sys.stderr)
            return 1
        print(f"Generated API types are current: {OUTPUT}")
        return 0
    OUTPUT.write_text(generated, encoding="utf-8", newline="\n")
    print(f"Generated {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
