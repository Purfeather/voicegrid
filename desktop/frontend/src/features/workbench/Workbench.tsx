import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { AppEvent, HardwareMetrics, ModuleDescriptor, ProjectDetail, RuntimeSnapshot, StylePreset, TaskRecord, ThemeId, VoiceAsset, WorkspaceDraft } from "../../types";
import { api } from "../../services/api";
import { registerExitSaveHandler } from "../../services/exitCoordinator";
import { TitleBar } from "../../components/TitleBar";
import { EmptyState } from "../../components/UI";
import { VoicePanel } from "./VoicePanel";
import { ScriptPanel } from "./ScriptPanel";
import { OutputPanel } from "./OutputPanel";
import { ParameterRail } from "./ParameterRail";
import styles from "./workbench.module.css";
import { ModuleTabs } from "../modules/ModuleTabs";
import { ModuleInstallPanel } from "../modules/ModuleInstallPanel";
import { ModuleWorkbenchShell } from "../modules/ModuleWorkbenchShell";

interface Props {
  voices: VoiceAsset[];
  stylesList: StylePreset[];
  languages: Array<{ value: string; label: string }>;
  runtime: RuntimeSnapshot;
  metrics: HardwareMetrics;
  event: AppEvent | null;
  theme: ThemeId;
  onTheme: (theme: ThemeId) => void;
  onRefreshResources: () => Promise<void>;
  onRuntime: (runtime: RuntimeSnapshot) => void;
  onMessage: (message: string, tone?: "success" | "error") => void;
  modules: ModuleDescriptor[];
  onModulesChanged: () => Promise<void>;
}

export function Workbench(props: Props) {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceDraft | null>(null);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [parameterOpen, setParameterOpen] = useState(false);
  const [saveState, setSaveState] = useState("正在载入项目…");
  const [loadError, setLoadError] = useState("");
  const dirty = useRef(false);
  const revision = useRef(0);
  const editVersion = useRef(0);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const exitInProgress = useRef(false);

  const refreshProject = useCallback(async (preserveWorkspace = false) => {
    const [detail, taskList] = await Promise.all([api.openProject(projectId), api.tasks(projectId, "speech")]);
    revision.current = Math.max(revision.current, detail.revision);
    setProject(detail);
    if (!preserveWorkspace || !dirty.current) setWorkspace(detail.workspace);
    setTasks(taskList);
    if (!preserveWorkspace || !dirty.current) {
      dirty.current = false;
      editVersion.current = 0;
      setSaveState(detail.recovery_available ? "已恢复最近自动保存" : "项目已保存");
      if (detail.recovery_available) void api.confirmProjectRecovery(detail.id).then((confirmed) => {
        setProject(confirmed);
        setSaveState("项目已保存");
      }).catch(() => undefined);
    }
  }, [projectId]);

  const queueSave = useCallback((snapshot: WorkspaceDraft, version: number) => {
    if (!project) return Promise.resolve();
    const operation = saveQueue.current.then(async () => {
      const saved = await api.saveProject(project.id, revision.current, snapshot, "speech");
      revision.current = saved.revision;
      setProject((current) => current ? { ...current, revision: saved.revision, updated_at: saved.updated_at } : current);
      if (editVersion.current === version) {
        dirty.current = false;
        setSaveState("项目已保存");
      }
    });
    saveQueue.current = operation.catch(() => undefined);
    return operation;
  }, [project]);

  useEffect(() => {
    refreshProject().catch((error) => setLoadError(error instanceof Error ? error.message : "项目载入失败"));
  }, [refreshProject]);

  useEffect(() => {
    const event = props.event;
    if (!event) return;
    if (event.type === "task.updated") {
      const task = event.payload as TaskRecord;
      if (task.project_id !== projectId || task.module !== "speech") return;
      setTasks((current) => [task, ...current.filter((item) => item.id !== task.id)].sort((a, b) => b.created_at.localeCompare(a.created_at)));
      if (task.status === "completed") refreshProject(true).catch(() => undefined);
    }
    if (event.type === "task.removed") {
      const removed = event.payload as { id: string; project_id: string; module?: string };
      if (removed.project_id === projectId && (!removed.module || removed.module === "speech")) setTasks((current) => current.filter((task) => task.id !== removed.id));
    }
  }, [projectId, props.event, refreshProject]);

  useEffect(() => {
    if (!dirty.current || !workspace || !project) return;
    setSaveState("保存中…");
    const version = editVersion.current;
    const snapshot = workspace;
    const timer = window.setTimeout(async () => {
      if (exitInProgress.current || !dirty.current || editVersion.current !== version) return;
      try {
        await queueSave(snapshot, version);
      } catch (error) {
        setSaveState("保存失败");
        props.onMessage(error instanceof Error ? error.message : "项目保存失败", "error");
      }
    }, 650);
    return () => window.clearTimeout(timer);
  }, [workspace, project, props.onMessage, queueSave]);

  useEffect(() => registerExitSaveHandler(async () => {
    if (!project) return;
    exitInProgress.current = true;
    await saveQueue.current;
    if (workspace && dirty.current) await queueSave(workspace, editVersion.current);
    await api.closeProject(project.id);
  }), [project, queueSave, workspace]);

  function updateWorkspace(patch: Partial<WorkspaceDraft>) {
    dirty.current = true;
    editVersion.current += 1;
    setWorkspace((current) => current ? { ...current, ...patch } : current);
    setSaveState("有未保存更改");
  }

  async function generate() {
    if (!project || !workspace) return;
    try {
      if (dirty.current) {
        await queueSave(workspace, editVersion.current);
      }
      const task = await api.createModuleTask(project.id, "speech", workspace);
      setTasks((current) => [task, ...current]);
      props.onMessage("任务已加入队列。", "success");
    } catch (error) { props.onMessage(error instanceof Error ? error.message : "无法创建任务", "error"); }
  }

  async function back() {
    if (project && workspace) {
      try {
        if (dirty.current) await queueSave(workspace, editVersion.current);
        await api.closeProject(project.id);
      } catch { /* The local autosave remains available for recovery. */ }
    }
    navigate("/projects");
  }

  async function saveBeforeModuleSwitch() {
    if (!project || !workspace || !dirty.current) return;
    try {
      await queueSave(workspace, editVersion.current);
    } catch (error) {
      setSaveState("保存失败");
      props.onMessage(error instanceof Error ? error.message : "切换模块前保存失败", "error");
      throw error;
    }
  }

  if (loadError) return <><TitleBar runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={() => navigate("/projects")} onRelease={async () => props.onRuntime(await api.releaseRuntime())} /><ModuleTabs modules={props.modules} /><main id="main-content" className={styles.workbench}><EmptyState title="项目无法打开" detail={loadError} /></main></>;
  if (!project || !workspace) return <><TitleBar runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={() => navigate("/projects")} onRelease={async () => props.onRuntime(await api.releaseRuntime())} /><ModuleTabs modules={props.modules} /><main id="main-content" className={styles.workbench}><EmptyState title="正在准备工作台" detail="正在读取项目、音色和运行环境…" /></main></>;

  const generating = tasks.some((task) => task.status === "queued" || task.status === "running");
  const module = props.modules.find((item) => item.id === "speech");
  const canEdit = Boolean(module?.installed);
  return <>
    <TitleBar projectName={project.name} saveState={canEdit ? saveState : "预览模式 · 未保存"} runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={back} onRelease={async () => props.onRuntime(await api.releaseRuntime())} />
    <ModuleTabs modules={props.modules} beforeNavigate={saveBeforeModuleSwitch} />
    <ModuleWorkbenchShell label="语音合成工作台" parameterRail={<ParameterRail open={parameterOpen} workspace={workspace} onOpen={setParameterOpen} onWorkspace={updateWorkspace} locked={!canEdit} />}>
        <VoicePanel leading={module && <ModuleInstallPanel module={module} onDetect={async () => { await api.detectModule("speech"); await props.onModulesChanged(); }} onInstall={async (repair) => { await api.installModule("speech", repair); await props.onModulesChanged(); props.onMessage("语音模型安装已在后台开始，可以继续预览其他模块。", "success"); }} />} locked={!canEdit} voices={props.voices} workspace={workspace} onWorkspace={updateWorkspace} onVoicesChanged={props.onRefreshResources} onMessage={props.onMessage} />
        <ScriptPanel locked={!canEdit} workspace={workspace} stylesList={props.stylesList} languages={props.languages} onWorkspace={updateWorkspace} onStylesChanged={props.onRefreshResources} onMessage={props.onMessage} />
        <OutputPanel
          locked={!canEdit}
          workspace={workspace}
          tasks={tasks}
          history={project.history}
          generating={generating}
          onWorkspace={updateWorkspace}
          onGenerate={generate}
          onCancel={async (id) => { const task = await api.cancelTask(id); setTasks((current) => [task, ...current.filter((item) => item.id !== id)]); }}
          onRemoveTask={async (id) => {
            const result = await api.removeTask(id);
            if (result.pending && result.task) setTasks((current) => [result.task!, ...current.filter((item) => item.id !== id)]);
            else setTasks((current) => current.filter((item) => item.id !== id));
          }}
          onClearActivity={async () => {
            if (!window.confirm("清除全部任务与输出记录吗？已生成的音频文件和进行中任务会保留。")) return;
            await api.clearActivity(project.id, false, "speech");
            setTasks((current) => current.filter((task) => task.status === "queued" || task.status === "running"));
            setProject((current) => current ? { ...current, history: [], output_count: 0 } : current);
            props.onMessage("活动记录已清除，音频文件已保留。", "success");
          }}
          onOpenOutputFolder={async () => {
            try { await api.openProjectOutputFolder(project.id, "speech"); }
            catch (error) { props.onMessage(error instanceof Error ? error.message : "无法打开当前输出目录。", "error"); }
          }}
          onReuse={(snapshot) => {
            const styleExists = props.stylesList.some((style) => style.name === snapshot.style);
            const reference = snapshot.reference_audio;
            const voiceExists = !reference || props.voices.some((voice) => voice.id === reference.id);
            updateWorkspace({
              instruction: snapshot.instruction,
              manual_speed_enabled: Boolean(snapshot.speed && snapshot.speed !== "自动"),
              ...(snapshot.speed && snapshot.speed !== "自动" ? { manual_speed_level: snapshot.speed } : {}),
              ...(styleExists ? { style: snapshot.style } : {}),
              ...(voiceExists ? reference
                ? reference.saved
                  ? { voice_id: reference.id, reference_id: null, reference_trim_start: 0, reference_trim_end: null }
                  : { reference_id: reference.id, voice_id: null, reference_trim_start: 0, reference_trim_end: null }
                : { voice_id: null, reference_id: null, reference_trim_start: 0, reference_trim_end: null }
                : {}),
            });
            if (!styleExists && !voiceExists) props.onMessage("原风格和参考音频已不存在，已复用情感提示与语速。", "success");
            else if (!styleExists) props.onMessage("原风格已不存在，已复用情感提示、参考音频与语速。", "success");
            else if (!voiceExists) props.onMessage("原参考音频已不存在，已复用风格、情感提示与语速。", "success");
            else props.onMessage("生成设定已复用。", "success");
          }}
        />
    </ModuleWorkbenchShell>
  </>;
}
