import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AudioLines, Download, FileAudio2, FolderOpen, Save, Sparkles, Square, Trash2, WandSparkles } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import type { AppEvent, HardwareMetrics, ModuleDescriptor, OutputRecord, ProjectDetail, RuntimeSnapshot, TaskRecord, ThemeId, VoiceAsset, VoiceDesignDraft, VoicePromptComposer } from "../../types";
import { api } from "../../services/api";
import { TitleBar } from "../../components/TitleBar";
import { Badge, Button, EmptyState, Field, IconButton, Modal, Progress, Section, Select, TextArea, TextInput } from "../../components/UI";
import { ModuleTabs } from "../modules/ModuleTabs";
import { ModuleInstallPanel } from "../modules/ModuleInstallPanel";
import { OptionalModuleColumn, OptionalModuleWorkbench } from "../modules/OptionalModuleWorkbench";
import { ModuleActivityActions, ModuleActivityTimeline, ModuleCurrentOutput, ModuleGenerateCard, ModuleParameterRail } from "../modules/ModuleWorkbenchShell";
import { VoiceAssetLibrary } from "../modules/VoiceAssetLibrary";
import styles from "./voiceDesign.module.css";

interface Props {
  modules: ModuleDescriptor[];
  voices: VoiceAsset[];
  runtime: RuntimeSnapshot;
  metrics: HardwareMetrics;
  event: AppEvent | null;
  theme: ThemeId;
  onTheme: (theme: ThemeId) => void;
  onModulesChanged: () => Promise<void>;
  onResourcesChanged: () => Promise<void>;
  onRuntime: (runtime: RuntimeSnapshot) => void;
  onMessage: (message: string, tone?: "success" | "error") => void;
}

const OPTIONS: Record<keyof VoicePromptComposer, string[]> = {
  role: ["纪录片旁白", "影视角色", "商业广告", "有声书讲述", "游戏角色", "智能助手"],
  age_gender: ["青年女性", "青年男性", "成熟女性", "成熟男性", "成熟中性", "少年感"],
  texture: ["清晰温润", "磁性沙哑", "明亮通透", "柔软气声", "厚实颗粒", "冷静疏离"],
  pitch_strength: ["中低音，力度克制", "中音，力度自然", "高音区，轻盈明亮", "低沉，力度饱满", "音高灵活，强弱变化明显"],
  pace_rhythm: ["自然语速，节奏从容", "慢速，留白充足", "较快，节奏利落", "速度多变，转折鲜明", "短句紧凑，长句舒展"],
  accent_language: ["标准普通话", "自然北方口音", "轻微南方口音", "标准美式英语", "标准英式英语", "中英双语自然切换"],
  emotion: ["沉稳可信", "温柔治愈", "轻松机敏", "冷峻神秘", "热情有感染力", "克制忧郁"],
  performance: ["情绪保持稳定，句尾自然收束", "情绪逐句推进，高潮适度增强", "有生活感，避免播音腔", "停连明确，重音克制", "表演变化丰富但保持音色一致"],
};

const LABELS: Record<keyof VoicePromptComposer, string> = {
  role: "角色定位", age_gender: "年龄 / 性别", texture: "音色质感", pitch_strength: "音高 / 力度",
  pace_rhythm: "语速 / 节奏", accent_language: "口音 / 语言", emotion: "核心情绪", performance: "表演变化",
};

function composePrompt(composer: VoicePromptComposer) {
  return `${composer.age_gender}的${composer.role}，声音${composer.texture}，${composer.pitch_strength}；${composer.pace_rhythm}，使用${composer.accent_language}。整体${composer.emotion}，${composer.performance}。`;
}

function statusTone(status: TaskRecord["status"]): "success" | "warning" | "danger" | "neutral" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "queued") return "warning";
  return "neutral";
}

export function VoiceDesignWorkbench(props: Props) {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const module = props.modules.find((item) => item.id === "voice_design");
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [draft, setDraft] = useState<VoiceDesignDraft | null>(null);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [history, setHistory] = useState<OutputRecord[]>([]);
  const [selected, setSelected] = useState<OutputRecord | null>(null);
  const [saveState, setSaveState] = useState("正在载入项目…");
  const [loadError, setLoadError] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [saveVoiceOpen, setSaveVoiceOpen] = useState(false);
  const [voiceName, setVoiceName] = useState("");
  const dirty = useRef(false);
  const revision = useRef(0);
  const editVersion = useRef(0);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());

  const refresh = useCallback(async (preserveDraft = false) => {
    const [detail, taskList, outputs] = await Promise.all([
      api.openProject(projectId), api.tasks(projectId, "voice_design"), api.history(projectId, "voice_design"),
    ]);
    revision.current = Math.max(revision.current, detail.revision);
    const workspace = detail.workspaces.voice_design;
    const promptPreview = composePrompt(workspace.composer);
    setProject(detail);
    if (!preserveDraft || !dirty.current) setDraft({ ...workspace, prompt_preview: promptPreview });
    setTasks(taskList);
    setHistory(outputs);
    setSelected((current) => outputs.find((item) => item.id === current?.id) || outputs[0] || null);
    if (!preserveDraft || !dirty.current) {
      dirty.current = false;
      editVersion.current = 0;
      setSaveState(detail.recovery_available ? "已保留上次编辑进度" : "已自动保存");
    }
  }, [projectId]);

  const queueSave = useCallback((snapshot: VoiceDesignDraft, version: number) => {
    if (!project) return Promise.resolve();
    const operation = saveQueue.current.then(async () => {
      const saved = await api.saveProject(project.id, revision.current, snapshot, "voice_design");
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
    const event = props.event;
    if (!event) return;
    if (event.type === "task.updated") {
      const task = event.payload as TaskRecord;
      if (task.project_id !== projectId || task.module !== "voice_design") return;
      setTasks((current) => [task, ...current.filter((item) => item.id !== task.id)].sort((a, b) => b.created_at.localeCompare(a.created_at)));
      if (task.status === "completed") void refresh(true);
    }
    if (event.type === "task.removed") {
      const removed = event.payload as { id: string; project_id: string; module?: string };
      if (removed.project_id === projectId && removed.module === "voice_design") setTasks((current) => current.filter((item) => item.id !== removed.id));
    }
  }, [projectId, props.event, refresh]);

  useEffect(() => {
    if (!dirty.current || !draft || !project || !module?.installed) return;
    setSaveState("保存中…");
    const version = editVersion.current;
    const snapshot = draft;
    const timer = window.setTimeout(async () => {
      if (!dirty.current || editVersion.current !== version) return;
      try {
        await queueSave(snapshot, version);
      } catch (error) {
        setSaveState("保存失败");
        props.onMessage(error instanceof Error ? error.message : "音色设计草稿保存失败", "error");
      }
    }, 650);
    return () => window.clearTimeout(timer);
  }, [draft, module?.installed, project, props.onMessage, queueSave]);

  function update(patch: Partial<VoiceDesignDraft>) {
    if (!module?.installed) return;
    dirty.current = true;
    editVersion.current += 1;
    setDraft((current) => current ? { ...current, ...patch } : current);
    setSaveState("有未保存更改");
  }

  function updateComposer(key: keyof VoicePromptComposer, value: string) {
    if (!draft || !module?.installed) return;
    const composer = { ...draft.composer, [key]: value };
    update({ composer, prompt_preview: composePrompt(composer) });
  }

  async function generate() {
    if (!project || !draft || !module?.installed) return;
    try {
      if (dirty.current) {
        await queueSave(draft, editVersion.current);
      }
      const task = await api.createModuleTask(project.id, "voice_design", draft);
      setTasks((current) => [task, ...current]);
      props.onMessage("音色设计任务已加入全局队列。", "success");
    } catch (error) { props.onMessage(error instanceof Error ? error.message : "无法创建音色设计任务", "error"); }
  }

  async function closeProject() {
    try {
      if (project && draft && dirty.current && module?.installed) await queueSave(draft, editVersion.current);
      if (project) await api.closeProject(project.id);
    } catch { /* Recovery remains available. */ }
    navigate("/projects");
  }

  async function saveBeforeModuleSwitch() {
    if (!project || !draft || !dirty.current || !module?.installed) return;
    try {
      await queueSave(draft, editVersion.current);
    } catch (error) {
      setSaveState("保存失败");
      props.onMessage(error instanceof Error ? error.message : "切换模块前保存失败", "error");
      throw error;
    }
  }

  const activeTask = tasks.find((task) => task.status === "running" || task.status === "queued");
  const canEdit = Boolean(module?.installed);
  const composerPreview = useMemo(() => draft ? composePrompt(draft.composer) : "", [draft]);

  if (loadError || !project || !draft) return <><TitleBar runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={() => navigate("/projects")} onRelease={async () => props.onRuntime(await api.releaseRuntime())} /><ModuleTabs modules={props.modules} /><main className={styles.loading}><EmptyState title={loadError ? "项目无法打开" : "正在准备音色设计"} detail={loadError || "正在读取项目草稿与音色设计历史…"} /></main></>;

  return <>
    <TitleBar projectName={project.name} saveState={canEdit ? saveState : "预览模式 · 未保存"} runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={closeProject} onRelease={async () => props.onRuntime(await api.releaseRuntime())} />
    <ModuleTabs modules={props.modules} beforeNavigate={saveBeforeModuleSwitch} />
    <OptionalModuleWorkbench label="音色设计工作台" parameterRail={<ModuleParameterRail open={advancedOpen} onOpen={setAdvancedOpen} title="高级生成参数" summary={`官方推荐 · Temperature ${draft.parameters.audio_temperature} · Top-P ${draft.parameters.audio_top_p} · Top-K ${draft.parameters.audio_top_k}`} locked={!canEdit}>
      <fieldset className={styles.railParameterGrid} disabled={!canEdit}>
        <Field label="Temperature"><TextInput type="number" step="0.1" min="0.1" max="3" value={draft.parameters.audio_temperature} onChange={(e) => update({ parameters: { ...draft.parameters, audio_temperature: Number(e.target.value) } })} /></Field>
        <Field label="Top-P"><TextInput type="number" step="0.05" min="0.1" max="1" value={draft.parameters.audio_top_p} onChange={(e) => update({ parameters: { ...draft.parameters, audio_top_p: Number(e.target.value) } })} /></Field>
        <Field label="Top-K"><TextInput type="number" min="1" max="200" value={draft.parameters.audio_top_k} onChange={(e) => update({ parameters: { ...draft.parameters, audio_top_k: Number(e.target.value) } })} /></Field>
        <Field label="重复惩罚"><TextInput type="number" step="0.05" min="0.5" max="2" value={draft.parameters.audio_repetition_penalty} onChange={(e) => update({ parameters: { ...draft.parameters, audio_repetition_penalty: Number(e.target.value) } })} /></Field>
        <Field label="最大 Tokens"><TextInput type="number" min="256" max="8192" step="128" value={draft.parameters.max_new_tokens} onChange={(e) => update({ parameters: { ...draft.parameters, max_new_tokens: Number(e.target.value) } })} /></Field>
        <Field label="随机种子"><TextInput type="number" min="0" value={draft.parameters.seed} onChange={(e) => update({ parameters: { ...draft.parameters, seed: Number(e.target.value) } })} /></Field>
      </fieldset>
    </ModuleParameterRail>}>
      <OptionalModuleColumn label="音色设计模块状态">
        {module && <ModuleInstallPanel module={module} onDetect={async () => { await api.detectModule("voice_design"); await props.onModulesChanged(); }} onInstall={async (repair) => { await api.installModule("voice_design", repair); await props.onModulesChanged(); props.onMessage("安装已在后台开始，可以继续使用其他模块。", "success"); }} />}
        <VoiceAssetLibrary voices={props.voices} onChanged={props.onResourcesChanged} onMessage={props.onMessage} locked={!canEdit} />
      </OptionalModuleColumn>

      <OptionalModuleColumn label="音色提示词与试听台词">
        <Section title="设计方法" eyebrow="VOICE BLUEPRINT">
          <div className={styles.sectionBody}>
            <div className={styles.modeSwitch}>
              <button className={draft.mode === "composer" ? styles.active : ""} disabled={!canEdit} onClick={() => update({ mode: "composer" })}>模块组合</button>
              <button className={draft.mode === "freeform" ? styles.active : ""} disabled={!canEdit} onClick={() => update({ mode: "freeform" })}>自由描述</button>
            </div>
            <p>组合器只生成预览，只有点击“应用到提示词”才会覆盖最终提示词。</p>
          </div>
        </Section>
        <Section title="音色提示词组合器" eyebrow="PROMPT COMPOSER" actions={<Badge tone="accent">8 个维度</Badge>}>
          <fieldset className={styles.composerGrid} disabled={!canEdit || draft.mode !== "composer"}>
            {(Object.keys(OPTIONS) as Array<keyof VoicePromptComposer>).map((key) => <Field key={key} label={LABELS[key]} compact><Select value={draft.composer[key]} onChange={(event) => updateComposer(key, event.target.value)}>{OPTIONS[key].map((option) => <option key={option}>{option}</option>)}</Select></Field>)}
          </fieldset>
          <div className={styles.promptPreview}><span>组合预览</span><p>{composerPreview}</p><Button variant="secondary" icon={<WandSparkles size={15} />} disabled={!canEdit || draft.mode !== "composer"} onClick={() => update({ instruction: composerPreview, prompt_preview: composerPreview })}>应用到提示词</Button></div>
        </Section>
        <Section title="最终音色提示词" eyebrow="FINAL INSTRUCTION" actions={<Badge tone={draft.mode === "freeform" ? "accent" : "neutral"}>{draft.mode === "freeform" ? "自由描述" : "已独立编辑"}</Badge>}>
          <div className={styles.editorBody}><TextArea rows={6} disabled={!canEdit} value={draft.instruction} onChange={(event) => update({ instruction: event.target.value })} /><small>生成时只使用这里的完整文本；组合器不会在后台自动覆盖。</small></div>
        </Section>
        <Section title="试听台词" eyebrow="AUDITION SCRIPT">
          <div className={styles.editorBody}><TextArea rows={5} disabled={!canEdit} value={draft.text} onChange={(event) => update({ text: event.target.value })} /><span className={styles.counter}>{draft.text.length} 字</span></div>
        </Section>
      </OptionalModuleColumn>

      <OptionalModuleColumn label="音色生成与设计历史" output>
        <ModuleGenerateCard actions={<Badge tone={module?.installed ? "success" : "neutral"}>{module?.installed ? "准备就绪" : "预览"}</Badge>}>
          <div className={styles.generateBody}>
            <Button className={styles.generateButton} variant="primary" icon={<Sparkles size={17} />} disabled={!canEdit || Boolean(activeTask) || !draft.text.trim() || !draft.instruction.trim()} onClick={generate}>{activeTask ? "任务进行中" : "生成试听音色"}</Button>
            {activeTask && <div className={styles.activeTask}><Progress value={activeTask.progress} label="音色设计进度" /><span>{activeTask.message}</span><Button variant="ghost" icon={<Square size={13} />} onClick={() => api.cancelTask(activeTask.id)}>安全停止</Button></div>}
          </div>
        </ModuleGenerateCard>
        <ModuleCurrentOutput actions={selected && <Button className={styles.compactButton} variant="ghost" icon={<Save size={13} />} onClick={() => { setVoiceName(""); setSaveVoiceOpen(true); }}>保存为音色</Button>}>
          {selected ? <div className={styles.currentOutput}><div><span className={styles.outputMark}><AudioLines size={15} /></span><div><strong>{selected.filename}</strong><small>{selected.duration.toFixed(1)} 秒 · {selected.sample_rate / 1000} kHz · 原生 WAV</small></div></div><audio controls src={selected.artifact_url} /><div className={styles.outputActions}><Button variant="secondary" icon={<FolderOpen size={14} />} onClick={() => api.openArtifact(selected.id)}>打开目录</Button><a href={api.artifactUrl(selected.id, true)} download><Download size={14} />下载</a></div></div> : <EmptyState title="还没有试听结果" detail="生成完成后会先写入项目历史，再显示在这里。" />}
        </ModuleCurrentOutput>
        <ModuleActivityTimeline actions={<ModuleActivityActions clearDisabled={!history.length && !tasks.length} folderDisabled={!selected} onClear={async () => { if (!window.confirm("清除音色设计任务与历史记录吗？音频文件会保留。")) return; await api.clearActivity(project.id, false, "voice_design"); await refresh(); }} onOpenFolder={async () => { if (selected) await api.openArtifact(selected.id); }} />}>
          <div className={styles.historyList}>
            {tasks.filter((task) => task.status !== "completed" || !history.some((output) => output.task_id === task.id)).map((task) => <article key={task.id}><button onClick={() => task.status === "running" || task.status === "queued" ? undefined : undefined}><span>{task.message}</span><Badge tone={statusTone(task.status)}>{task.status}</Badge></button><Progress value={task.progress} label={task.message} /><IconButton label="移除此任务" onClick={() => api.removeTask(task.id)}><Trash2 size={13} /></IconButton></article>)}
            {history.map((output) => <button key={output.id} className={selected?.id === output.id ? styles.selectedHistory : ""} onClick={() => setSelected(output)}><FileAudio2 size={13} /><span><strong>{output.filename}</strong><small>{output.created_at.replace("T", " ")} · {output.duration.toFixed(1)} 秒</small></span><em>WAV</em></button>)}
            {!tasks.length && !history.length && <EmptyState title="暂无设计历史" detail="生成任务和试听结果会按时间保存在当前项目。" />}
          </div>
        </ModuleActivityTimeline>
      </OptionalModuleColumn>
    </OptionalModuleWorkbench>
    <Modal open={saveVoiceOpen} title="保存到共享音色库" onClose={() => setSaveVoiceOpen(false)} footer={<><Button variant="ghost" onClick={() => setSaveVoiceOpen(false)}>取消</Button><Button variant="primary" icon={<Save size={15} />} disabled={!voiceName.trim()} onClick={async () => { if (!selected) return; await api.saveDesignedVoice(selected.id, voiceName.trim()); await props.onResourcesChanged(); setSaveVoiceOpen(false); props.onMessage("设计音色已保存到共享音色库。", "success"); }}>保存音色</Button></>}><Field label="音色名称" help="保存后可立即在语音合成模块中选择。"><TextInput autoFocus value={voiceName} onChange={(event) => setVoiceName(event.target.value)} placeholder="例如：沉稳纪录片男声" /></Field></Modal>
  </>;
}
