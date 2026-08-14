export type {
  ActivityClearResult,
  AppEvent,
  AudioHealth,
  BootstrapPayload,
  CoreBootstrap,
  GenerationSnapshot,
  HardwareMetrics,
  HealthSnapshot,
  ModelLock,
  ModuleDescriptor,
  ModuleId,
  ModuleInstallState,
  OutputProfile,
  OutputRecord,
  ProjectDetail,
  ProjectSummary,
  ProjectWorkspaces,
  RuntimeSnapshot,
  SoundEffectDraft,
  SoundEffectGenerationSnapshot,
  SoundEffectParameters,
  SpeedLevel,
  StylePreset,
  SynthesisParameters,
  TaskRecord,
  TaskRemovalResult,
  TaskStatus,
  VoiceAsset,
  VoiceDesignDraft,
  VoiceDesignGenerationSnapshot,
  VoiceDesignParameters,
  VoicePromptComposer,
  WorkspaceDraft,
} from "./api.generated";

export type ThemeId = "dark" | "light";
export type StartupPhase = "shell" | "backend_import" | "database" | "project_recovery" | "api" | "frontend" | "ready" | "slow" | "failed";
export type ResourceStatus = "idle" | "loading" | "ready" | "error";

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
