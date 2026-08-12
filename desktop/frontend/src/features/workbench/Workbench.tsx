import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { AppEvent, HardwareMetrics, ProjectDetail, RuntimeSnapshot, StylePreset, TaskRecord, ThemeId, VoiceAsset, WorkspaceDraft } from "../../types";
import { api } from "../../services/api";
import { TitleBar } from "../../components/TitleBar";
import { EmptyState } from "../../components/UI";
import { VoicePanel } from "./VoicePanel";
import { ScriptPanel } from "./ScriptPanel";
import { OutputPanel } from "./OutputPanel";
import { ParameterRail } from "./ParameterRail";
import styles from "./workbench.module.css";

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

  const refreshProject = useCallback(async () => {
    const [detail, taskList] = await Promise.all([api.openProject(projectId), api.tasks(projectId)]);
    revision.current = detail.revision;
    setProject(detail);
    setWorkspace(detail.workspace);
    setTasks(taskList);
    setSaveState(detail.recovery_available ? "已恢复上次进度" : "已自动保存");
  }, [projectId]);

  useEffect(() => {
    refreshProject().catch((error) => setLoadError(error instanceof Error ? error.message : "项目载入失败"));
  }, [refreshProject]);

  useEffect(() => {
    const event = props.event;
    if (!event) return;
    if (event.type === "task.updated") {
      const task = event.payload as TaskRecord;
      if (task.project_id !== projectId) return;
      setTasks((current) => [task, ...current.filter((item) => item.id !== task.id)].sort((a, b) => b.created_at.localeCompare(a.created_at)));
      if (task.status === "completed") refreshProject().catch(() => undefined);
    }
  }, [projectId, props.event, refreshProject]);

  useEffect(() => {
    if (!dirty.current || !workspace || !project) return;
    setSaveState("保存中…");
    const timer = window.setTimeout(async () => {
      try {
        const saved = await api.saveProject(project.id, revision.current, workspace);
        revision.current = saved.revision;
        setProject((current) => current ? { ...current, revision: saved.revision, updated_at: saved.updated_at } : current);
        dirty.current = false;
        setSaveState("已自动保存");
      } catch (error) {
        setSaveState("保存失败");
        props.onMessage(error instanceof Error ? error.message : "项目保存失败", "error");
      }
    }, 650);
    return () => window.clearTimeout(timer);
  }, [workspace, project, props.onMessage]);

  function updateWorkspace(patch: Partial<WorkspaceDraft>) {
    dirty.current = true;
    setWorkspace((current) => current ? { ...current, ...patch } : current);
    setSaveState("有未保存更改");
  }

  async function generate() {
    if (!project || !workspace) return;
    try {
      if (dirty.current) {
        const saved = await api.saveProject(project.id, revision.current, workspace);
        revision.current = saved.revision;
        dirty.current = false;
      }
      const task = await api.createTask(project.id, workspace);
      setTasks((current) => [task, ...current]);
      props.onMessage("任务已加入队列。", "success");
    } catch (error) { props.onMessage(error instanceof Error ? error.message : "无法创建任务", "error"); }
  }

  async function back() {
    if (project && workspace) {
      try {
        if (dirty.current) await api.saveProject(project.id, revision.current, workspace);
        await api.closeProject(project.id);
      } catch { /* The local autosave remains available for recovery. */ }
    }
    navigate("/projects");
  }

  if (loadError) return <><TitleBar runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={() => navigate("/projects")} onRelease={async () => props.onRuntime(await api.releaseRuntime())} /><main id="main-content" className={styles.workbench}><EmptyState title="项目无法打开" detail={loadError} /></main></>;
  if (!project || !workspace) return <><TitleBar runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={() => navigate("/projects")} onRelease={async () => props.onRuntime(await api.releaseRuntime())} /><main id="main-content" className={styles.workbench}><EmptyState title="正在准备工作台" detail="正在读取项目、音色和运行环境…" /></main></>;

  const generating = tasks.some((task) => task.status === "queued" || task.status === "running");
  return <>
    <TitleBar projectName={project.name} saveState={saveState} runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={back} onRelease={async () => props.onRuntime(await api.releaseRuntime())} />
    <main id="main-content" className={styles.workbench}>
      <div className={styles.workbenchMain}>
        <VoicePanel voices={props.voices} workspace={workspace} onWorkspace={updateWorkspace} onVoicesChanged={props.onRefreshResources} onMessage={props.onMessage} />
        <ScriptPanel workspace={workspace} stylesList={props.stylesList} languages={props.languages} onWorkspace={updateWorkspace} onStylesChanged={props.onRefreshResources} onMessage={props.onMessage} />
        <OutputPanel projectId={project.id} workspace={workspace} tasks={tasks} history={project.history} generating={generating} onWorkspace={updateWorkspace} onGenerate={generate} onCancel={async (id) => { const task = await api.cancelTask(id); setTasks((current) => [task, ...current.filter((item) => item.id !== id)]); }} onClearTasks={async () => { await api.clearTasks(project.id); setTasks((current) => current.filter((task) => task.status === "queued" || task.status === "running")); }} onClearHistory={async () => { if (!window.confirm("清空历史记录列表吗？音频文件会保留。")) return; await api.clearHistory(project.id, false); setProject((current) => current ? { ...current, history: [], output_count: 0 } : current); }} />
      </div>
      <ParameterRail open={parameterOpen} workspace={workspace} onOpen={setParameterOpen} onWorkspace={updateWorkspace} />
    </main>
  </>;
}
