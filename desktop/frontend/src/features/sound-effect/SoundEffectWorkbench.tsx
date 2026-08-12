import { useCallback, useEffect, useRef, useState } from "react";
import { AudioLines, Download, FileAudio2, FolderOpen, Heart, Pencil, Play, Square, Trash2 } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import type { HardwareMetrics, ModuleDescriptor, OutputRecord, ProjectDetail, RuntimeSnapshot, SoundEffectDraft, TaskRecord, ThemeId } from "../../types";
import { api } from "../../services/api";
import { TitleBar } from "../../components/TitleBar";
import { Badge, Button, EmptyState, Field, IconButton, Progress, Section, TextArea, TextInput } from "../../components/UI";
import { ModuleInstallPanel } from "../modules/ModuleInstallPanel";
import { ModuleTabs } from "../modules/ModuleTabs";
import { OptionalModuleColumn, OptionalModuleWorkbench } from "../modules/OptionalModuleWorkbench";
import { AssetLibrary, ModuleActivityActions, ModuleActivityTimeline, ModuleCurrentOutput, ModuleGenerateButton, ModuleGenerateCard, ModuleParameterRail } from "../modules/ModuleWorkbenchShell";
import styles from "./soundEffect.module.css";

interface Props {
  modules: ModuleDescriptor[];
  runtime: RuntimeSnapshot;
  metrics: HardwareMetrics;
  theme: ThemeId;
  onTheme: (theme: ThemeId) => void;
  onModulesChanged: () => Promise<void>;
  onRuntime: (runtime: RuntimeSnapshot) => void;
  onMessage: (message: string, tone?: "success" | "error") => void;
}

function statusTone(status: TaskRecord["status"]): "success" | "warning" | "danger" | "neutral" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "queued") return "warning";
  return "neutral";
}

export function SoundEffectWorkbench(props: Props) {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const module = props.modules.find((item) => item.id === "sound_effect");
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [draft, setDraft] = useState<SoundEffectDraft | null>(null);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [history, setHistory] = useState<OutputRecord[]>([]);
  const [selected, setSelected] = useState<OutputRecord | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [saveState, setSaveState] = useState("正在载入项目…");
  const dirty = useRef(false);
  const revision = useRef(0);
  const editVersion = useRef(0);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const interactive = Boolean(module?.installed && module.engine_available);

  const refresh = useCallback(async (preserveDraft = false) => {
    const [detail, taskList, outputs] = await Promise.all([
      api.openProject(projectId), api.tasks(projectId, "sound_effect"), api.history(projectId, "sound_effect"),
    ]);
    revision.current = Math.max(revision.current, detail.revision);
    setProject(detail);
    if (!preserveDraft || !dirty.current) setDraft(detail.workspaces.sound_effect);
    setTasks(taskList);
    setHistory(outputs);
    setSelected((current) => outputs.find((item) => item.id === current?.id) || outputs[0] || null);
    if (!preserveDraft || !dirty.current) {
      dirty.current = false;
      editVersion.current = 0;
      setSaveState(detail.recovery_available ? "已保留上次编辑进度" : "已自动保存");
    }
  }, [projectId]);

  const refreshActivity = useCallback(async () => {
    const [taskList, outputs] = await Promise.all([
      api.tasks(projectId, "sound_effect"), api.history(projectId, "sound_effect"),
    ]);
    setTasks(taskList);
    setHistory(outputs);
    setSelected((current) => outputs.find((item) => item.id === current?.id) || outputs[0] || null);
  }, [projectId]);

  const queueSave = useCallback((snapshot: SoundEffectDraft, version: number) => {
    if (!project) return Promise.resolve();
    const operation = saveQueue.current.then(async () => {
      const saved = await api.saveProject(project.id, revision.current, snapshot, "sound_effect");
      revision.current = saved.revision;
      setProject((current) => current ? { ...current, revision: saved.revision, updated_at: saved.updated_at } : current);
      if (editVersion.current === version) {
        dirty.current = false;
        setSaveState("已自动保存");
      }
    });
    saveQueue.current = operation.catch(() => undefined);
    return operation;
  }, [project]);

  useEffect(() => { refresh().catch((error) => setLoadError(error instanceof Error ? error.message : "项目载入失败")); }, [refresh]);
  useEffect(() => {
    if (!interactive) return;
    const hasActiveTask = tasks.some((task) => task.status === "running" || task.status === "queued");
    const timer = window.setInterval(() => void refreshActivity().catch(() => undefined), hasActiveTask ? 900 : 4000);
    return () => window.clearInterval(timer);
  }, [interactive, refreshActivity, tasks]);
  useEffect(() => {
    if (!dirty.current || !draft || !project || !interactive) return;
    setSaveState("保存中…");
    const version = editVersion.current;
    const snapshot = draft;
    const timer = window.setTimeout(async () => {
      if (!dirty.current || editVersion.current !== version) return;
      try { await queueSave(snapshot, version); }
      catch (error) {
        setSaveState("保存失败");
        props.onMessage(error instanceof Error ? error.message : "音效草稿保存失败", "error");
      }
    }, 650);
    return () => window.clearTimeout(timer);
  }, [draft, interactive, project, props.onMessage, queueSave]);

  function update(patch: Partial<SoundEffectDraft>) {
    if (!interactive) return;
    dirty.current = true;
    editVersion.current += 1;
    setDraft((current) => current ? { ...current, ...patch } : current);
    setSaveState("有未保存更改");
  }

  async function generate() {
    if (!project || !draft || !interactive) return;
    try {
      if (dirty.current) await queueSave(draft, editVersion.current);
      const task = await api.createModuleTask(project.id, "sound_effect", draft);
      setTasks((current) => [task, ...current]);
      props.onMessage("音效生成任务已加入全局队列。", "success");
    } catch (error) { props.onMessage(error instanceof Error ? error.message : "无法创建音效生成任务", "error"); }
  }

  async function closeProject() {
    try {
      if (project && draft && dirty.current && interactive) await queueSave(draft, editVersion.current);
      if (project) await api.closeProject(project.id);
    } catch { /* Recovery remains available. */ }
    navigate("/projects");
  }

  async function saveBeforeModuleSwitch() {
    if (!project || !draft || !dirty.current || !interactive) return;
    try { await queueSave(draft, editVersion.current); }
    catch (error) {
      setSaveState("保存失败");
      props.onMessage(error instanceof Error ? error.message : "切换模块前保存失败", "error");
      throw error;
    }
  }

  async function renameAsset(output: OutputRecord) {
    const currentName = output.filename.replace(/\.[^.]+$/, "");
    const name = window.prompt("输入新的音效名称", currentName)?.trim();
    if (!name || name === currentName) return;
    try { await api.updateSoundEffect(output.id, { name }); await refreshActivity(); props.onMessage("音效名称已更新。", "success"); }
    catch (error) { props.onMessage(error instanceof Error ? error.message : "音效重命名失败", "error"); }
  }

  async function toggleFavorite(output: OutputRecord) {
    try { await api.updateSoundEffect(output.id, { favorite: !output.favorite }); await refreshActivity(); }
    catch (error) { props.onMessage(error instanceof Error ? error.message : "收藏状态更新失败", "error"); }
  }

  async function deleteAsset(output: OutputRecord) {
    if (!window.confirm(`删除音效“${output.filename}”及其音频文件吗？`)) return;
    try { await api.deleteSoundEffect(output.id, true); await refreshActivity(); props.onMessage("音效已删除。", "success"); }
    catch (error) { props.onMessage(error instanceof Error ? error.message : "音效删除失败", "error"); }
  }

  const activeTask = tasks.find((task) => task.status === "running" || task.status === "queued");
  const visibleTasks = tasks.filter((task) => task.status !== "completed" || !history.some((output) => output.task_id === task.id));

  if (loadError || !project || !draft) return <><TitleBar runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={() => navigate("/projects")} onRelease={async () => props.onRuntime(await api.releaseRuntime())} /><ModuleTabs modules={props.modules} /><main className={styles.loading}><EmptyState title={loadError ? "项目无法打开" : "正在准备音效模块"} detail={loadError || "正在读取项目草稿与音效历史…"} /></main></>;

  return <>
    <TitleBar projectName={project.name} saveState={interactive ? saveState : "预览模式 · 未保存"} runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={closeProject} onRelease={async () => props.onRuntime(await api.releaseRuntime())} />
    <ModuleTabs modules={props.modules} beforeNavigate={saveBeforeModuleSwitch} />
    <OptionalModuleWorkbench label="音效生成工作台" parameterRail={<ModuleParameterRail open={advancedOpen} onOpen={setAdvancedOpen} title="高级生成参数" summary={`稳定模式 · ${draft.parameters.num_inference_steps} 步 · CFG ${draft.parameters.cfg_scale} · Sigma ${draft.parameters.sigma_shift}`} locked={!interactive}>
      <fieldset className={styles.railParameterGrid} disabled={!interactive}>
        <Field label="推理步数" help="默认 100，范围 10–150"><TextInput type="number" min="10" max="150" value={draft.parameters.num_inference_steps} onChange={(e) => update({ parameters: { ...draft.parameters, num_inference_steps: Number(e.target.value) } })} /></Field>
        <Field label="CFG" help="默认 4.0，范围 1–8"><TextInput type="number" min="1" max="8" step="0.1" value={draft.parameters.cfg_scale} onChange={(e) => update({ parameters: { ...draft.parameters, cfg_scale: Number(e.target.value) } })} /></Field>
        <Field label="Sigma Shift" help="默认 5.0，范围 0–10"><TextInput type="number" min="0" max="10" step="0.1" value={draft.parameters.sigma_shift} onChange={(e) => update({ parameters: { ...draft.parameters, sigma_shift: Number(e.target.value) } })} /></Field>
        <Field label="随机种子"><TextInput type="number" min="0" value={draft.parameters.seed} onChange={(e) => update({ parameters: { ...draft.parameters, seed: Number(e.target.value) } })} /></Field>
      </fieldset>
    </ModuleParameterRail>}>
      <OptionalModuleColumn label="音效模块状态">
        {module && <ModuleInstallPanel module={module} onDetect={async () => { await api.detectModule("sound_effect"); await props.onModulesChanged(); }} onInstall={async (repair) => { await api.installModule("sound_effect", repair); await props.onModulesChanged(); props.onMessage("音效模型安装已在后台开始。", "success"); }} />}
        <AssetLibrary title="项目音效素材库" eyebrow="Project SFX library" count={<Badge tone={history.length ? "accent" : "neutral"}>{history.length} 个</Badge>}>
          {interactive ? <div className={styles.assetRows}>
            {history.map((output) => <article key={output.id} className={`${styles.assetRow} ${selected?.id === output.id ? styles.assetRowActive : ""}`}>
              <button className={styles.assetSelect} onClick={() => setSelected(output)}><span className={styles.assetIcon}><AudioLines size={15} /></span><span><strong>{output.filename}</strong><small>{output.duration.toFixed(1)} 秒 · {output.sample_rate / 1000} kHz</small></span></button>
              <div className={styles.assetActions}>
                <IconButton label={`试听 ${output.filename}`} onClick={() => { setSelected(output); void new Audio(output.artifact_url).play(); }}><Play size={13} /></IconButton>
                <IconButton label={output.favorite ? "取消收藏" : "收藏"} onClick={() => toggleFavorite(output)}><Heart size={13} fill={output.favorite ? "currentColor" : "none"} /></IconButton>
                <IconButton label="重命名音效" onClick={() => renameAsset(output)}><Pencil size={13} /></IconButton>
                <IconButton label="删除音效" onClick={() => deleteAsset(output)}><Trash2 size={13} /></IconButton>
              </div>
            </article>)}
            {!history.length && <EmptyState title="项目素材库为空" detail="生成完成的音效会自动保存在这里。" />}
          </div> : <><div className={styles.assetList}>{["雨夜远处车辆驶过", "金属门缓慢开启", "林间风吹树叶"].map((name, index) => <article key={name}><span><AudioLines size={15} /></span><div><strong>{name}</strong><small>示例内容 · {8 + index * 3} 秒</small></div><Heart size={14} /><em>WAV</em></article>)}</div><EmptyState title="安装后建立项目素材库" detail="真实结果将自动进入当前项目，支持试听、收藏、重命名、下载和删除。" /></>}
        </AssetLibrary>
      </OptionalModuleColumn>

      <OptionalModuleColumn label="音效描述与参数">
        <Section title="声音场景" eyebrow="SOUND BRIEF" actions={<Badge tone="neutral">1–30 秒</Badge>}>
          <div className={styles.sectionBody}>
            <Field label="自由提示词" help="描述环境、声源、距离、动作、材质和时间变化。"><TextArea disabled={!interactive} rows={10} value={draft.prompt} onChange={(event) => update({ prompt: event.target.value })} /></Field>
            <Field label="生成时长"><div className={styles.durationField}><input disabled={!interactive} type="range" min="1" max="30" step="1" value={draft.parameters.seconds} onChange={(event) => update({ parameters: { ...draft.parameters, seconds: Number(event.target.value) } })} /><strong>{draft.parameters.seconds.toFixed(0)} 秒</strong></div></Field>
          </div>
        </Section>
      </OptionalModuleColumn>

      <OptionalModuleColumn label="音效生成与项目素材" output>
        <ModuleGenerateCard actions={<Badge tone={interactive ? "success" : "neutral"}>{interactive ? "准备就绪" : "预览"}</Badge>}>
          <div className={styles.generateBody}>
            <ModuleGenerateButton module="sound_effect" className={styles.generateButton} disabled={!interactive || Boolean(activeTask) || !draft.prompt.trim()} onClick={generate} />
            {activeTask && <div className={styles.activeTask}><Progress value={activeTask.progress} label="音效生成进度" /><span>{activeTask.message}</span><Button variant="ghost" icon={<Square size={13} />} onClick={() => api.cancelTask(activeTask.id)}>安全停止</Button></div>}
            {!interactive && <p>安装模型并通过引擎检测后，可创建真实音效生成任务。</p>}
          </div>
        </ModuleGenerateCard>
        <ModuleCurrentOutput actions={selected?.favorite ? <Badge tone="accent"><Heart size={11} fill="currentColor" /> 已收藏</Badge> : undefined}>
          {interactive && selected ? <div className={styles.currentOutput}><div><span className={styles.outputMark}><AudioLines size={15} /></span><div><strong>{selected.filename}</strong><small>{selected.duration.toFixed(1)} 秒 · {selected.sample_rate / 1000} kHz · {selected.channels === 1 ? "单声道" : `${selected.channels} 声道`}</small></div></div><audio controls src={selected.artifact_url} /><div className={styles.outputActions}><Button variant="secondary" icon={<FolderOpen size={14} />} onClick={() => api.openArtifact(selected.id)}>打开目录</Button><a href={api.artifactUrl(selected.id, true)} download><Download size={14} />下载</a></div></div> : interactive ? <EmptyState title="还没有音效输出" detail="生成完成后会先写入项目素材库，再显示在这里。" /> : <><div className={styles.previewAsset}><span><AudioLines size={20} /></span><div><strong>雨夜城市街道</strong><small>48 kHz · 单声道 · 10 秒</small></div></div><div className={styles.fakeWave}>{Array.from({ length: 72 }, (_, index) => <i key={index} style={{ height: `${12 + ((index * 17) % 48)}%` }} />)}</div><div className={styles.lockedActions}><Button variant="secondary" icon={<FolderOpen size={14} />} disabled>打开目录</Button><Button variant="primary" icon={<Download size={14} />} disabled>下载</Button></div></>}
        </ModuleCurrentOutput>
        <ModuleActivityTimeline actions={<ModuleActivityActions clearDisabled={!history.length && !tasks.length} onClear={async () => { if (!window.confirm("清除音效任务与历史记录吗？音频文件会保留。")) return; await api.clearActivity(project.id, false, "sound_effect"); await refreshActivity(); }} onOpenFolder={() => api.openProjectOutputFolder(project.id, "sound_effect")} />}>
          <div className={styles.historyList}>
            {visibleTasks.map((task) => <article key={task.id}><div><span>{task.message}</span><Badge tone={statusTone(task.status)}>{task.status}</Badge></div><Progress value={task.progress} label={task.message} />{(task.status === "running" || task.status === "queued") && <IconButton label="安全停止" onClick={() => api.cancelTask(task.id)}><Square size={13} /></IconButton>}<IconButton label="移除此任务" onClick={async () => { await api.removeTask(task.id); await refreshActivity(); }}><Trash2 size={13} /></IconButton></article>)}
            {history.map((output) => <button key={output.id} className={selected?.id === output.id ? styles.selectedHistory : ""} onClick={() => setSelected(output)}><FileAudio2 size={13} /><span><strong>{output.filename}</strong><small>{output.created_at.replace("T", " ")} · {output.duration.toFixed(1)} 秒</small></span>{output.favorite && <Heart size={11} fill="currentColor" />}<em>WAV</em></button>)}
            {!tasks.length && !history.length && <EmptyState title="暂无任务与输出" detail="生成任务和音效结果会按时间保存在当前项目。" />}
          </div>
        </ModuleActivityTimeline>
      </OptionalModuleColumn>
    </OptionalModuleWorkbench>
  </>;
}
