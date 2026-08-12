import { useEffect, useMemo, useState } from "react";
import { AudioLines, Ban, CircleAlert, Download, FileAudio2, FolderOpen, LoaderCircle, Trash2, WandSparkles } from "lucide-react";
import type { OutputProfile, OutputRecord, TaskRecord, WorkspaceDraft } from "../../types";
import { api } from "../../services/api";
import { selectFolder } from "../../services/native";
import { Badge, Button, EmptyState, Field, IconButton, Progress, Section, Select, TextInput } from "../../components/UI";
import { formatDuration } from "../../utils/text";
import styles from "./workbench.module.css";

interface Props {
  projectId: string;
  workspace: WorkspaceDraft;
  tasks: TaskRecord[];
  history: OutputRecord[];
  generating: boolean;
  onWorkspace: (patch: Partial<WorkspaceDraft>) => void;
  onGenerate: () => Promise<void>;
  onCancel: (id: string) => Promise<void>;
  onClearTasks: () => Promise<void>;
  onClearHistory: () => Promise<void>;
}

type ActivityFilter = "all" | "active" | "completed" | "exception";
type ActivityItem =
  | { kind: "task"; id: string; createdAt: string; task: TaskRecord }
  | { kind: "output"; id: string; createdAt: string; output: OutputRecord };

export function OutputPanel({ workspace, tasks, history, generating, onWorkspace, onGenerate, onCancel, onClearTasks, onClearHistory }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const profile = workspace.output_profile;
  const current = useMemo(() => history.find((item) => item.id === selectedId) || history[0] || null, [history, selectedId]);
  useEffect(() => { if (!selectedId && history[0]) setSelectedId(history[0].id); }, [history, selectedId]);

  const activity = useMemo<ActivityItem[]>(() => {
    const outputTaskIds = new Set(history.map((record) => record.task_id));
    const taskItems: ActivityItem[] = tasks
      .filter((task) => !(task.status === "completed" && outputTaskIds.has(task.id)))
      .map((task) => ({ kind: "task", id: task.id, createdAt: task.created_at, task }));
    const outputItems: ActivityItem[] = history.map((output) => ({ kind: "output", id: output.id, createdAt: output.created_at, output }));
    return [...taskItems, ...outputItems].sort((left, right) => {
      const leftActive = left.kind === "task" && (left.task.status === "queued" || left.task.status === "running");
      const rightActive = right.kind === "task" && (right.task.status === "queued" || right.task.status === "running");
      if (leftActive !== rightActive) return leftActive ? -1 : 1;
      return right.createdAt.localeCompare(left.createdAt);
    });
  }, [history, tasks]);

  const filteredActivity = activity.filter((item) => {
    if (filter === "all") return true;
    if (filter === "completed") return item.kind === "output";
    if (filter === "active") return item.kind === "task" && (item.task.status === "queued" || item.task.status === "running");
    return item.kind === "task" && ["failed", "cancelled", "interrupted"].includes(item.task.status);
  });

  function updateProfile(patch: Partial<OutputProfile>) {
    onWorkspace({ output_profile: { ...profile, ...patch } });
  }

  async function chooseOutputDirectory() {
    const result = await selectFolder(profile.output_directory);
    if (result) updateProfile({ output_directory: result });
  }

  return (
    <div className={`${styles.columnScroll} ${styles.outputColumn}`}>
      <Section title="生成与交付" eyebrow="Output engineering" actions={<Badge tone={generating ? "accent" : "neutral"}>{generating ? "生成中" : "准备就绪"}</Badge>}>
        <div className={styles.sectionBody}>
          <Button className={styles.generateButton} variant="primary" icon={<WandSparkles size={17} />} busy={generating} disabled={!workspace.text.trim() || generating} onClick={onGenerate}>{generating ? "正在生成音频" : "开始生成"}</Button>
          <div className={styles.outputGrid}>
            <Field label="格式" compact><Select value={profile.format} onChange={(event) => updateProfile({ format: event.target.value as "WAV" | "FLAC" })}><option>WAV</option><option>FLAC</option></Select></Field>
            <Field label="采样率" compact><Select value={profile.sample_rate} onChange={(event) => updateProfile({ sample_rate: Number(event.target.value) as OutputProfile["sample_rate"] })}><option value={24000}>24 kHz</option><option value={44100}>44.1 kHz</option><option value={48000}>48 kHz</option></Select></Field>
            <Field label="位深" compact><Select value={profile.bit_depth} onChange={(event) => updateProfile({ bit_depth: Number(event.target.value) as OutputProfile["bit_depth"] })}><option value={16}>16 bit</option><option value={24}>24 bit</option><option value={32}>32 bit</option></Select></Field>
            <Field label="声道" compact><Select value={profile.channels} onChange={(event) => updateProfile({ channels: Number(event.target.value) as 1 | 2 })}><option value={1}>单声道</option><option value={2}>立体声</option></Select></Field>
          </div>
          <Field label="目标响度" compact><div className={styles.rangeWithValue}><input type="range" min={-30} max={-12} step={1} value={profile.loudness_lufs ?? -23} onChange={(event) => updateProfile({ loudness_lufs: Number(event.target.value) })} /><strong>{profile.loudness_lufs ?? "关闭"} LUFS</strong></div></Field>
          <Field label="文件名模板" compact><TextInput value={profile.filename_template} onChange={(event) => updateProfile({ filename_template: event.target.value })} /></Field>
          <Field label="输出目录" compact><div className={styles.pathField}><TextInput readOnly value={profile.output_directory} title={profile.output_directory} /><IconButton label="选择输出目录" onClick={chooseOutputDirectory}><FolderOpen size={16} /></IconButton></div></Field>
        </div>
      </Section>

      <Section title="当前输出" eyebrow="Monitor">
        {current ? <div className={styles.currentOutput}>
          <div><span className={styles.outputIcon}><AudioLines size={14} /></span><div><strong title={current.filename}>{current.filename}</strong><span>{current.format} · {current.sample_rate / 1000} kHz · {current.bit_depth} bit · {formatDuration(current.duration)}</span></div></div>
          <audio controls src={current.artifact_url} />
          {current.generation_snapshot && <details className={styles.generationDetails}>
            <summary>生成设定</summary>
            <dl>
              <div><dt>风格</dt><dd>{current.generation_snapshot.style || "未命名"}</dd></div>
              <div><dt>语言</dt><dd>{current.generation_snapshot.language || "自动"}</dd></div>
              <div><dt>参数预设</dt><dd>{current.generation_snapshot.preset}</dd></div>
              <div><dt>目标时长</dt><dd>{current.generation_snapshot.target_duration_enabled ? `${current.generation_snapshot.target_duration_seconds} 秒 · ${current.generation_snapshot.target_tokens} tokens` : "自动"}</dd></div>
            </dl>
            <strong>风格 / 情感提示</strong><p>{current.generation_snapshot.instruction || "未设置"}</p>
            <strong>生成片段</strong><ol>{current.generation_snapshot.segments.map((segment) => <li key={segment.index}>{segment.text}</li>)}</ol>
          </details>}
          <div className={styles.outputActions}><Button icon={<FolderOpen size={15} />} onClick={() => api.openArtifact(current.id)}>打开目录</Button><a className={styles.downloadButton} href={api.artifactUrl(current.id, true)} download><Download size={15} />下载</a></div>
        </div> : <EmptyState title="尚未生成音频" detail="生成完成后会先保存到活动记录，再自动出现在这里。" />}
      </Section>

      <Section
        title="任务与输出"
        eyebrow="Activity"
        className={styles.activitySection}
        actions={<div className={styles.activityActions}>
          {tasks.length > 0 && <IconButton label="清理已结束任务" onClick={onClearTasks}><Trash2 size={14} /></IconButton>}
          {history.length > 0 && <IconButton label="清空输出历史" onClick={onClearHistory}><FileAudio2 size={14} /></IconButton>}
        </div>}
      >
        <div className={styles.activityFilters} role="group" aria-label="活动记录筛选">
          {([['all', '全部'], ['active', '进行中'], ['completed', '已完成'], ['exception', '异常']] as Array<[ActivityFilter, string]>).map(([value, label]) => <button key={value} className={filter === value ? styles.activityFilterActive : ""} onClick={() => setFilter(value)}>{label}</button>)}
        </div>
        <div className={styles.activityList}>
          {filteredActivity.length ? filteredActivity.map((item) => item.kind === "output" ? (
            <button key={`output-${item.id}`} className={`${styles.activityOutput} ${current?.id === item.output.id ? styles.historyActive : ""}`} onClick={() => setSelectedId(item.output.id)}>
              <span className={styles.historyAsset}><FileAudio2 size={14} /></span>
              <span><strong>{item.output.filename}</strong><small>{new Date(item.output.created_at).toLocaleString("zh-CN")} · {formatDuration(item.output.duration)}</small></span>
              <Badge tone="success">已完成</Badge>
            </button>
          ) : (
            <article key={`task-${item.id}`} className={styles.activityTask}>
              <header><span>{item.task.status === "running" ? <LoaderCircle className={styles.spin} size={14} /> : <CircleAlert size={14} />}<strong>{item.task.message}</strong></span><Badge tone={item.task.status === "failed" ? "danger" : item.task.status === "running" ? "accent" : "neutral"}>{item.task.status}</Badge></header>
              <Progress value={item.task.progress} label={item.task.message} />
              {item.task.error && <p>{item.task.error}</p>}
              {(item.task.status === "running" || item.task.status === "queued") && <Button variant="ghost" icon={<Ban size={14} />} onClick={() => onCancel(item.task.id)}>安全停止</Button>}
            </article>
          )) : <EmptyState title="没有匹配的活动" detail="生成任务和已保存的输出会统一显示在这里。" />}
        </div>
      </Section>
    </div>
  );
}
