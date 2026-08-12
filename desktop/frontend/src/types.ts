export type ThemeId = "dark" | "light";
export type ModuleId = "speech" | "voice_design" | "sound_effect";

export type StartupPhase = "shell" | "backend_import" | "database" | "project_recovery" | "api" | "frontend" | "ready" | "slow" | "failed";

export interface StartupStatus {
  phase: StartupPhase;
  active_phase: StartupPhase;
  message: string;
  detail: string;
  error: string;
  elapsed_ms: number;
  ready: boolean;
  retry_allowed: boolean;
  trace_path: string;
}

export type ResourceStatus = "idle" | "loading" | "ready" | "error";

export interface ResourceState<T> {
  status: ResourceStatus;
  data: T;
  error: string;
  startedAt: number | null;
  resolvedAt: number | null;
}

export interface ThemeDefinition {
  id: ThemeId;
  name: string;
  colorScheme: "dark" | "light";
}

export interface SynthesisParameters {
  temperature: number;
  top_p: number;
  top_k: number;
  repetition_penalty: number;
  max_seconds: number;
  segment_chars: number;
  pause_ms: number;
  seed: number;
}

export interface OutputProfile {
  format: "WAV" | "FLAC";
  sample_rate: 24000 | 44100 | 48000;
  bit_depth: 16 | 24 | 32;
  channels: 1 | 2;
  loudness_lufs: number | null;
  output_directory: string;
}

export interface AudioHealth {
  duration: number;
  sample_rate: number;
  channels: number;
  peak_dbfs: number;
  rms_dbfs: number;
  clipping_ratio: number;
  snr_db: number;
  silence_ratio: number;
  score: number;
  suitability: string;
  findings: Array<{ level: "success" | "warning" | "error"; message: string }>;
  waveform: number[];
}

export interface VoiceAsset {
  id: string;
  name: string;
  saved: boolean;
  created_at: string;
  artifact_url: string;
  health: AudioHealth;
  role?: string;
  language_accent?: string;
  gender_age?: string;
  description?: string;
}

export interface StylePreset {
  name: string;
  instruction: string;
  built_in: boolean;
  updated_at: string;
}

export interface WorkspaceDraft {
  text: string;
  language: string;
  style: string;
  instruction: string;
  manual_speed_enabled: boolean;
  manual_speed_level: SpeedLevel;
  preset: "标准" | "兼容";
  parameters: SynthesisParameters;
  reference_id: string | null;
  voice_id: string | null;
  reference_trim_start: number;
  reference_trim_end: number | null;
  output_profile: OutputProfile;
}

export interface ProjectSummary {
  id: string;
  name: string;
  updated_at: string;
  recovery_available: boolean;
  output_count: number;
  voice: string;
  status: string;
}

export interface ProjectDetail extends ProjectSummary {
  created_at: string;
  revision: number;
  workspace: WorkspaceDraft;
  workspaces: ProjectWorkspaces;
  history: OutputRecord[];
}

export interface VoicePromptComposer {
  role: string;
  age_gender: string;
  texture: string;
  pitch_strength: string;
  pace_rhythm: string;
  accent_language: string;
  emotion: string;
  performance: string;
}

export interface VoiceDesignParameters {
  audio_temperature: number;
  audio_top_p: number;
  audio_top_k: number;
  audio_repetition_penalty: number;
  max_new_tokens: number;
  seed: number;
}

export interface VoiceDesignDraft {
  mode: "composer" | "freeform";
  text: string;
  composer: VoicePromptComposer;
  prompt_preview: string;
  instruction: string;
  parameters: VoiceDesignParameters;
}

export interface SoundEffectParameters {
  seconds: number;
  num_inference_steps: number;
  cfg_scale: number;
  sigma_shift: number;
  seed: number;
}

export interface SoundEffectDraft {
  prompt: string;
  parameters: SoundEffectParameters;
}

export interface ProjectWorkspaces {
  speech: WorkspaceDraft;
  voice_design: VoiceDesignDraft;
  sound_effect: SoundEffectDraft;
}

export interface OutputRecord {
  id: string;
  task_id: string;
  filename: string;
  created_at: string;
  duration: number;
  sample_rate: number;
  channels: number;
  bit_depth: number;
  format: string;
  voice: string;
  text: string;
  artifact_url: string;
  module: ModuleId;
  kind: "speech_output" | "voice_design_output" | "sound_effect_output";
  instruction?: string;
  generation_snapshot?: GenerationSnapshot | VoiceDesignGenerationSnapshot;
}

export interface GenerationSnapshot {
  style: string;
  instruction: string;
  reference_audio?: {
    id: string;
    name: string;
    saved: boolean;
  } | null;
  speed?: "自动" | SpeedLevel;
}

export interface VoiceDesignGenerationSnapshot {
  mode: "composer" | "freeform";
  composer: VoicePromptComposer;
  prompt_preview: string;
  instruction: string;
  text: string;
  parameters: VoiceDesignParameters;
  model: string;
  codec: string;
}

export type SpeedLevel = "慢" | "较慢" | "中等" | "较快" | "快";

export type TaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";

export interface TaskRecord {
  id: string;
  project_id: string;
  module: ModuleId;
  status: TaskStatus;
  progress: number;
  message: string;
  created_at: string;
  updated_at: string;
  result_id: string | null;
  error: string | null;
  remove_after_stop: boolean;
}

export interface TaskRemovalResult {
  task_id: string;
  pending: boolean;
  task: TaskRecord | null;
}

export interface ActivityClearResult {
  tasks_removed: number;
  outputs_removed: number;
}

export interface HardwareMetrics {
  cpu_percent: number;
  memory_used_gb: number;
  memory_total_gb: number;
  memory_percent: number;
  gpu_name: string;
  gpu_percent: number | null;
  vram_used_gb: number | null;
  vram_total_gb: number | null;
  python_version: string;
  platform: string;
  timestamp: string;
}

export interface RuntimeSnapshot {
  state: "idle" | "loading" | "loaded" | "running" | "releasing" | "error";
  active_model: string | null;
  active_module?: ModuleId | null;
  message: string;
  device: string;
  dtype: string;
  attention: string;
  models: Array<{ key: string; name: string; version: string; installed: boolean; enabled: boolean }>;
}

export type ModuleInstallState = "not_installed" | "installing" | "repair_required" | "ready" | "failed";

export interface ModelLock {
  model_id: string;
  revision: string;
  file_count: number;
  total_bytes: number;
  manifest_sha256: string;
}

export interface ModuleDescriptor {
  id: ModuleId;
  name: string;
  model_name: string;
  model_id: string;
  codec_id?: string;
  description: string;
  disk_gb: number;
  download_gb: number;
  required_disk_gb: number;
  runtime_python: string;
  runtime_mode: "host" | "isolated";
  installed: boolean;
  model_ready: boolean;
  runtime_ready: boolean;
  install_state: ModuleInstallState;
  install_phase: string;
  install_progress: number;
  install_message: string;
  error: string;
  missing: string[];
  manual_paths: string[];
  preview_available: boolean;
  engine_available: boolean;
  engine_message?: string;
  model_locks: ModelLock[];
}

export interface CoreBootstrap {
  brand: string;
  product: string;
  version: string;
  languages: Array<{ value: string; label: string }>;
  model_capabilities: {
    key: string;
    name: string;
    version: string;
    offline: boolean;
    lazy_load: boolean;
  };
  defaults: {
    preset: "标准" | "兼容";
    parameters: SynthesisParameters;
  };
}

export interface HealthSnapshot {
  ok: boolean;
  api: string;
  database: Record<string, unknown>;
  project_index: Record<string, unknown>;
  version: string;
}

export interface BootstrapPayload {
  brand: string;
  product: string;
  version: string;
  projects: ProjectSummary[];
  voices: VoiceAsset[];
  styles: StylePreset[];
  runtime: RuntimeSnapshot;
  metrics: HardwareMetrics;
  languages: Array<{ value: string; label: string }>;
  modules: ModuleDescriptor[];
}

export interface AppEvent {
  type: "task.updated" | "task.removed" | "activity.cleared" | "runtime.updated" | "metrics.updated" | "project.saved" | "module.updated" | "voice.updated";
  payload: unknown;
}
