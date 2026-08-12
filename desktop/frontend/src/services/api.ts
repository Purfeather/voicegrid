import type {
  BootstrapPayload,
  ActivityClearResult,
  CoreBootstrap,
  HealthSnapshot,
  HardwareMetrics,
  OutputRecord,
  ProjectDetail,
  ProjectSummary,
  RuntimeSnapshot,
  StylePreset,
  TaskRecord,
  TaskRemovalResult,
  VoiceAsset,
  WorkspaceDraft,
} from "../types";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v2${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      // Keep the HTTP fallback.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthSnapshot>("/health"),
  core: () => request<CoreBootstrap>("/bootstrap/core"),
  bootstrap: () => request<BootstrapPayload>("/bootstrap"),
  projects: () => request<ProjectSummary[]>("/projects"),
  createProject: (name: string, language = "Chinese") => request<ProjectDetail>("/projects", {
    method: "POST",
    body: JSON.stringify({ name, language }),
  }),
  openProject: (id: string) => request<ProjectDetail>(`/projects/${id}?begin_session=true`),
  saveProject: (id: string, revision: number, workspace: WorkspaceDraft) => request<ProjectDetail>(`/projects/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ revision, workspace }),
  }),
  closeProject: (id: string) => request<void>(`/projects/${id}/close`, { method: "POST", keepalive: true }),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  uploadVoice: async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<VoiceAsset>("/voices/uploads", { method: "POST", body });
  },
  voices: () => request<VoiceAsset[]>("/voices"),
  styles: () => request<StylePreset[]>("/styles"),
  saveVoice: (id: string, name: string) => request<VoiceAsset>(`/voices/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ saved: true, name }),
  }),
  renameVoice: (id: string, name: string) => request<VoiceAsset>(`/voices/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  }),
  deleteVoice: (id: string, deleteFile = true) => request<void>(`/voices/${id}?delete_file=${deleteFile}`, { method: "DELETE" }),
  saveStyle: (name: string, instruction: string) => request<StylePreset>("/styles", {
    method: "POST",
    body: JSON.stringify({ name, instruction }),
  }),
  deleteStyle: (name: string) => request<void>(`/styles/${encodeURIComponent(name)}`, { method: "DELETE" }),
  createTask: (projectId: string, workspace: WorkspaceDraft) => request<TaskRecord>("/tasks", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, workspace }),
  }),
  tasks: (projectId: string) => request<TaskRecord[]>(`/tasks?project_id=${encodeURIComponent(projectId)}`),
  cancelTask: (id: string) => request<TaskRecord>(`/tasks/${id}/cancel`, { method: "POST" }),
  removeTask: (id: string) => request<TaskRemovalResult>(`/tasks/${id}`, { method: "DELETE" }),
  clearTasks: (projectId: string) => request<void>(`/tasks?project_id=${encodeURIComponent(projectId)}`, { method: "DELETE" }),
  clearActivity: (projectId: string, deleteFiles = false) => request<ActivityClearResult>(`/projects/${projectId}/activity?delete_files=${deleteFiles}`, { method: "DELETE" }),
  clearHistory: (projectId: string, deleteFiles = false) => request<void>(`/projects/${projectId}/history?delete_files=${deleteFiles}`, { method: "DELETE" }),
  history: (projectId: string) => request<OutputRecord[]>(`/projects/${projectId}/history`),
  runtime: () => request<RuntimeSnapshot>("/runtime"),
  releaseRuntime: () => request<RuntimeSnapshot>("/runtime/release", { method: "POST" }),
  metrics: () => request<HardwareMetrics>("/system/metrics"),
  openArtifact: (id: string) => request<void>(`/artifacts/${id}/open`, { method: "POST" }),
  artifactUrl: (id: string, download = false) => `/api/v2/artifacts/${id}${download ? "?download=true" : ""}`,
};
