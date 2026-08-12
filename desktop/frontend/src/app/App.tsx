import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { AlertTriangle, Clock3, FolderOpen, RefreshCw } from "lucide-react";
import type {
  AppEvent,
  CoreBootstrap,
  HardwareMetrics,
  ProjectSummary,
  ResourceState,
  RuntimeSnapshot,
  StylePreset,
  ThemeId,
  VoiceAsset,
} from "../types";
import { api } from "../services/api";
import { subscribeEvents } from "../services/events";
import { continueWaiting, notifyFrontendReady, openLogFolder, reportStartupEvent, retryStartup, startupStatus, windowAction } from "../services/native";
import { applyTheme, loadTheme } from "../theme/themes";
import { TitleBar } from "../components/TitleBar";
import { Button, EmptyState } from "../components/UI";
import { ProjectCenter } from "../features/projects/ProjectCenter";
import styles from "./App.module.css";

const Workbench = lazy(() => import("../features/workbench/Workbench").then((module) => ({ default: module.Workbench })));

const EMPTY_METRICS: HardwareMetrics = { cpu_percent: 0, memory_used_gb: 0, memory_total_gb: 0, memory_percent: 0, gpu_name: "", gpu_percent: null, vram_used_gb: null, vram_total_gb: null, python_version: "--", platform: "Windows", timestamp: "" };
const EMPTY_RUNTIME: RuntimeSnapshot = { state: "idle", active_model: null, message: "模型未加载", device: "", dtype: "", attention: "", models: [] };

function initialResource<T>(data: T): ResourceState<T> {
  return { status: "idle", data, error: "", startedAt: null, resolvedAt: null };
}

function loadingResource<T>(current: ResourceState<T>): ResourceState<T> {
  return { ...current, status: "loading", error: "", startedAt: performance.now(), resolvedAt: null };
}

function readyResource<T>(data: T): ResourceState<T> {
  return { status: "ready", data, error: "", startedAt: null, resolvedAt: performance.now() };
}

function failedResource<T>(current: ResourceState<T>, reason: unknown): ResourceState<T> {
  return { ...current, status: "error", error: reason instanceof Error ? reason.message : "本地资源暂时不可用", resolvedAt: performance.now() };
}

function StartupDiagnostic({ title, detail, retry, onContinue }: { title: string; detail: string; retry: () => void; onContinue?: () => void }) {
  return (
    <section className={styles.diagnostic} role="status" aria-live="polite">
      <AlertTriangle size={22} />
      <div><strong>{title}</strong><span>{detail}</span></div>
      <div className={styles.diagnosticActions}>
        {onContinue && <Button variant="primary" icon={<Clock3 size={15} />} onClick={onContinue}>继续等待</Button>}
        <Button variant={onContinue ? "secondary" : "primary"} icon={<RefreshCw size={15} />} onClick={retry}>重试</Button>
        <Button variant="ghost" icon={<FolderOpen size={15} />} onClick={() => openLogFolder()}>打开日志</Button>
        <Button variant="ghost" onClick={() => windowAction("exit")}>退出</Button>
      </div>
    </section>
  );
}

export function App() {
  const navigate = useNavigate();
  const [core, setCore] = useState<ResourceState<CoreBootstrap | null>>(() => initialResource(null));
  const [projects, setProjects] = useState<ResourceState<ProjectSummary[]>>(() => initialResource([]));
  const [voices, setVoices] = useState<ResourceState<VoiceAsset[]>>(() => initialResource([]));
  const [stylePresets, setStylePresets] = useState<ResourceState<StylePreset[]>>(() => initialResource([]));
  const [runtime, setRuntime] = useState<ResourceState<RuntimeSnapshot>>(() => initialResource(EMPTY_RUNTIME));
  const [metrics, setMetrics] = useState<ResourceState<HardwareMetrics>>(() => initialResource(EMPTY_METRICS));
  const [theme, setTheme] = useState<ThemeId>(loadTheme);
  const [toast, setToast] = useState<{ message: string; tone: "success" | "error" } | null>(null);
  const [lastEvent, setLastEvent] = useState<AppEvent | null>(null);
  const [slowCritical, setSlowCritical] = useState(false);
  const [slowReset, setSlowReset] = useState(0);
  const readyReported = useRef(false);

  const refreshProjects = useCallback(async () => {
    setProjects(loadingResource);
    try { setProjects(readyResource(await api.projects())); }
    catch (reason) { setProjects((current) => failedResource(current, reason)); }
  }, []);

  const loadCritical = useCallback(async () => {
    setCore(loadingResource);
    setProjects(loadingResource);
    const [coreResult, projectResult] = await Promise.allSettled([api.core(), api.projects()]);
    if (coreResult.status === "fulfilled") setCore(readyResource(coreResult.value));
    else setCore((current) => failedResource(current, coreResult.reason));
    if (projectResult.status === "fulfilled") setProjects(readyResource(projectResult.value));
    else setProjects((current) => failedResource(current, projectResult.reason));
  }, []);

  const loadSecondary = useCallback(async () => {
    setVoices(loadingResource);
    setStylePresets(loadingResource);
    setRuntime(loadingResource);
    setMetrics(loadingResource);
    const [voiceResult, styleResult, runtimeResult, metricsResult] = await Promise.allSettled([
      api.voices(), api.styles(), api.runtime(), api.metrics(),
    ]);
    if (voiceResult.status === "fulfilled") setVoices(readyResource(voiceResult.value));
    else setVoices((current) => failedResource(current, voiceResult.reason));
    if (styleResult.status === "fulfilled") setStylePresets(readyResource(styleResult.value));
    else setStylePresets((current) => failedResource(current, styleResult.reason));
    if (runtimeResult.status === "fulfilled") setRuntime(readyResource(runtimeResult.value));
    else setRuntime((current) => failedResource(current, runtimeResult.reason));
    if (metricsResult.status === "fulfilled") setMetrics(readyResource(metricsResult.value));
    else setMetrics((current) => failedResource(current, metricsResult.reason));
  }, []);

  const refreshVoicesAndStyles = useCallback(async () => {
    const [voiceResult, styleResult] = await Promise.allSettled([api.voices(), api.styles()]);
    if (voiceResult.status === "fulfilled") setVoices(readyResource(voiceResult.value));
    else setVoices((current) => failedResource(current, voiceResult.reason));
    if (styleResult.status === "fulfilled") setStylePresets(readyResource(styleResult.value));
    else setStylePresets((current) => failedResource(current, styleResult.reason));
  }, []);

  useEffect(() => { applyTheme(theme); }, [theme]);
  useEffect(() => { void reportStartupEvent("react_mounted", "React 应用已挂载"); }, []);
  useEffect(() => { void loadCritical(); }, [loadCritical]);
  useEffect(() => {
    if (core.status === "ready") void reportStartupEvent("core_ready", "核心 Bootstrap 已载入");
    if (core.status === "error") void reportStartupEvent("core_failed", core.error);
  }, [core.status, core.error]);
  useEffect(() => {
    if (projects.status === "ready") void reportStartupEvent("projects_ready", `项目索引已载入：${projects.data.length} 个项目`);
    if (projects.status === "error") void reportStartupEvent("projects_failed", projects.error);
  }, [projects.status, projects.error, projects.data.length]);
  useEffect(() => {
    if (core.status !== "ready" || (projects.status !== "ready" && projects.status !== "error")) return;
    void loadSecondary();
  }, [core.status, projects.status, loadSecondary]);
  useEffect(() => {
    if (core.status !== "ready" || (projects.status !== "ready" && projects.status !== "error") || readyReported.current) return;
    readyReported.current = true;
    window.setTimeout(() => {
      void reportStartupEvent("project_cards_ready", "项目中心首屏已完成渲染");
      void notifyFrontendReady();
    }, 0);
  }, [core.status, projects.status]);
  useEffect(() => subscribeEvents((event) => {
    if (event.type === "metrics.updated") setMetrics(readyResource(event.payload as HardwareMetrics));
    if (event.type === "runtime.updated") setRuntime(readyResource(event.payload as RuntimeSnapshot));
    setLastEvent(event);
  }), []);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3800);
    return () => window.clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    const pending = core.status === "idle" || core.status === "loading" || projects.status === "idle" || projects.status === "loading";
    if (!pending) { setSlowCritical(false); return; }
    let cancelled = false;
    let timer = 0;
    startupStatus().then((status) => {
      const delay = Math.max(0, 5000 - (status?.elapsed_ms || 0));
      timer = window.setTimeout(() => { if (!cancelled) setSlowCritical(true); }, delay);
    });
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [core.status, projects.status, slowReset]);

  const message = useCallback((text: string, tone: "success" | "error" = "success") => setToast({ message: text, tone }), []);

  async function createProject(name: string, language: string) {
    const project = await api.createProject(name, language);
    await refreshProjects();
    navigate(`/projects/${project.id}`);
  }

  async function releaseRuntime() {
    setRuntime(readyResource(await api.releaseRuntime()));
  }

  async function keepWaiting() {
    await continueWaiting();
    setSlowCritical(false);
    setSlowReset((value) => value + 1);
  }

  async function retryCritical() {
    await retryStartup();
    setSlowCritical(false);
    readyReported.current = false;
    await loadCritical();
  }

  const criticalPending = core.status === "idle" || core.status === "loading" || projects.status === "idle" || projects.status === "loading";

  if (core.status === "error") return <>
    <TitleBar runtime={runtime.data} metrics={metrics.data} theme={theme} onTheme={setTheme} startupMode onRelease={async () => undefined} />
    <main id="main-content" className={styles.fatal}>
      <StartupDiagnostic title="本地核心服务未准备完成" detail={`${core.error}。项目、音色和模型文件均未被修改。`} retry={() => { void retryCritical(); }} />
    </main>
  </>;

  return <div className={styles.app}>
    <Routes>
      <Route path="/projects" element={<>
        <TitleBar runtime={runtime.data} metrics={metrics.data} theme={theme} onTheme={setTheme} startupMode={criticalPending} onRelease={releaseRuntime} />
        <ProjectCenter
          projects={projects.data}
          loading={projects.status === "idle" || projects.status === "loading"}
          error={projects.error}
          onRetry={() => { void refreshProjects(); }}
          onCreate={createProject}
          onOpen={async (id) => navigate(`/projects/${id}`)}
          startupNotice={slowCritical ? <StartupDiagnostic title="启动时间超出预期" detail="项目索引仍在准备，窗口与新建入口保持可用。可以继续等待、重试或查看日志。" retry={() => { void retryCritical(); }} onContinue={() => { void keepWaiting(); }} /> : null}
        />
      </>} />
      <Route path="/projects/:projectId" element={
        <Suspense fallback={<><TitleBar runtime={runtime.data} metrics={metrics.data} theme={theme} onTheme={setTheme} onRelease={releaseRuntime} /><main id="main-content" className={styles.fatal}><EmptyState title="正在准备工作台" detail="项目中心保持可用，正在按需载入编辑器组件。" /></main></>}>
          <Workbench
            voices={voices.data}
            stylesList={stylePresets.data}
            languages={core.data?.languages || []}
            runtime={runtime.data}
            metrics={metrics.data}
            event={lastEvent}
            theme={theme}
            onTheme={setTheme}
            onRefreshResources={refreshVoicesAndStyles}
            onRuntime={(value) => setRuntime(readyResource(value))}
            onMessage={message}
          />
        </Suspense>
      } />
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
    {toast && <div className={`${styles.toast} ${toast.tone === "error" ? styles.toastError : ""}`} role="status">{toast.message}</div>}
  </div>;
}
