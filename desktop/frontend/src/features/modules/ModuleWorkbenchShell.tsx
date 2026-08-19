import { useState, type ReactNode } from "react";
import { BrushCleaning, ChevronDown, ChevronUp, Download, FolderOpen, LoaderCircle, SlidersHorizontal, Trash2 } from "lucide-react";
import type { ModuleId, OutputRecord, TaskRecord } from "../../types";
import { Badge, Button, EmptyState, IconButton, Progress, Section } from "../../components/UI";
import { MODULE_VISUALS } from "./moduleVisuals";
import { errorMessage } from "../../services/errors";
import { saveArtifact } from "../../services/native";
import styles from "./moduleWorkbenchShell.module.css";

export function ModuleWorkbenchShell({ children, parameterRail, label }: { children: ReactNode; parameterRail?: ReactNode; label: string }) {
  return <main className={styles.workspace} aria-label={label}><div className={styles.columns}>{children}</div>{parameterRail}</main>;
}

export function ModuleWorkbenchColumn({ children, label, output = false }: { children: ReactNode; label: string; output?: boolean }) {
  return <div className={`${styles.column} ${output ? styles.outputColumn : ""}`} aria-label={label}>{children}</div>;
}

export function ModulePreviewSurface({ children, locked }: { children: ReactNode; locked: boolean }) {
  return <div className={`${styles.previewSurface} ${locked ? styles.previewLocked : ""}`} aria-disabled={locked} inert={locked}>{children}</div>;
}

export function ModuleGenerateCard({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return <Section title="生成与交付" eyebrow="OUTPUT ENGINEERING" actions={actions}>{children}</Section>;
}

export function ModuleGenerateButton({ module, className = "", disabled = false, onClick }: { module: ModuleId; className?: string; disabled?: boolean; onClick?: () => void | Promise<void> }) {
  const Icon = MODULE_VISUALS[module].icon;
  return <Button className={className} variant="primary" icon={<Icon size={17} />} disabled={disabled} onClick={() => onClick?.()}>开始生成</Button>;
}

export function ModuleCurrentOutput({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return <Section title="当前输出" eyebrow="MONITOR" actions={actions}>{children}</Section>;
}

export function ModuleActivityTimeline({ children, actions, className = "" }: { children: ReactNode; actions?: ReactNode; className?: string }) {
  return <Section title="任务与输出" eyebrow="ACTIVITY" actions={actions} className={className}>{children}</Section>;
}

export function ModuleActivityActions({ onClear, onOpenFolder, clearDisabled = false, folderDisabled = false }: { onClear?: () => void | Promise<void>; onOpenFolder?: () => void | Promise<void>; clearDisabled?: boolean; folderDisabled?: boolean }) {
  return <div className={styles.activityActions}>
    <IconButton label="清除全部记录" disabled={clearDisabled || !onClear} onClick={() => onClear?.()}><BrushCleaning size={14} /></IconButton>
    <IconButton label="打开输出文件夹" disabled={folderDisabled || !onOpenFolder} onClick={() => onOpenFolder?.()}><FolderOpen size={14} /></IconButton>
  </div>;
}

export function AssetLibrary({ children, count, title = "资源库", eyebrow = "ASSET LIBRARY" }: { children: ReactNode; count?: ReactNode; title?: string; eyebrow?: string }) {
  return <Section title={title} eyebrow={eyebrow.toUpperCase()} actions={count}>{children}</Section>;
}

export function ModuleStatusHeader({ module, title, detail, actions }: { module: ModuleId; title: string; detail?: string; actions?: ReactNode }) {
  const visual = MODULE_VISUALS[module];
  const Icon = visual.icon;
  return <header className={styles.moduleStatusHeader}><span className={styles.moduleStatusIcon}><Icon size={15} /></span><div><small>{visual.installEyebrow}</small><strong>{title}</strong>{detail && <span>{detail}</span>}</div>{actions && <div className={styles.moduleStatusActions}>{actions}</div>}</header>;
}

export function ModuleOutputPlayer({ module, output, emptyDetail, onOpen, detail, onMessage }: {
  module: ModuleId;
  output: OutputRecord | null;
  emptyDetail: string;
  onOpen?: (output: OutputRecord) => void | Promise<void>;
  detail?: (output: OutputRecord) => ReactNode;
  onMessage?: (message: string, tone?: "success" | "error") => void;
}) {
  const visual = MODULE_VISUALS[module];
  const Icon = visual.icon;
  const [downloading, setDownloading] = useState(false);

  async function download() {
    if (!output || downloading) return;
    setDownloading(true);
    try {
      const result = await saveArtifact(output.id, output.filename);
      if (result.status === "saved") onMessage?.("文件已保存。", "success");
    } catch (error) {
      onMessage?.(errorMessage(error, "下载失败，请稍后重试。"), "error");
    } finally {
      setDownloading(false);
    }
  }

  if (!output) return <EmptyState title={visual.emptyOutputTitle} detail={emptyDetail} />;
  return <div className={styles.currentOutput}>
    <div><span className={styles.outputIcon}><Icon size={15} /></span><div><strong title={output.filename}>{output.filename}</strong><small>{detail?.(output) || <>{output.duration.toFixed(1)} 秒 · {output.sample_rate / 1000} kHz · {output.channels === 1 ? "单声道" : `${output.channels} 声道`}</>}</small></div></div>
    <audio controls src={output.artifact_url} />
    <div className={styles.outputActions}>
      <Button variant="secondary" icon={<FolderOpen size={14} />} onClick={() => onOpen?.(output)}>打开目录</Button>
      <Button variant="primary" busy={downloading} disabled={downloading} icon={<Download size={14} />} onClick={download}>下载</Button>
    </div>
  </div>;
}

function activityTone(status: TaskRecord["status"]): "success" | "warning" | "danger" | "neutral" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "queued") return "warning";
  return "neutral";
}

export function ModuleActivityTaskRow({ task, onCancel, onRemove }: { task: TaskRecord; onCancel?: (task: TaskRecord) => void | Promise<void>; onRemove: (task: TaskRecord) => void | Promise<void> }) {
  const active = task.status === "running" || task.status === "queued";
  return <article className={styles.activityTaskRow}><header><span>{active && <LoaderCircle className={styles.spin} size={13} />}<strong>{task.message}</strong></span><Badge tone={activityTone(task.status)}>{task.remove_after_stop ? "等待移除" : task.status}</Badge></header><Progress value={task.progress} label={task.message} />{task.error && <p>{task.error}</p>}<div>{active && onCancel && <Button variant="ghost" onClick={() => onCancel(task)}>安全停止</Button>}<IconButton label="移除此任务" disabled={task.remove_after_stop} onClick={() => onRemove(task)}><Trash2 size={13} /></IconButton></div></article>;
}

export function ModuleActivityOutputRow({ module, output, selected = false, onSelect, trailing }: { module: ModuleId; output: OutputRecord; selected?: boolean; onSelect: (output: OutputRecord) => void; trailing?: ReactNode }) {
  const Icon = MODULE_VISUALS[module].icon;
  return <button className={`${styles.activityOutputRow} ${selected ? styles.activityOutputSelected : ""}`} onClick={() => onSelect(output)}><span className={styles.activityOutputIcon}><Icon size={13} /></span><span><strong>{output.filename}</strong><small>{output.created_at.replace("T", " ")} · {output.duration.toFixed(1)} 秒</small></span>{trailing || <em>{output.format || "WAV"}</em>}</button>;
}

export function ModuleParameterRail({ open, onOpen, title, summary, actions, children, locked = false }: { open: boolean; onOpen: (open: boolean) => void; title: string; summary: string; actions?: ReactNode; children: ReactNode; locked?: boolean }) {
  return <section className={`${styles.parameterRail} ${open ? styles.parameterOpen : ""}`}>
    <button className={styles.parameterSummary} disabled={locked} onClick={() => onOpen(!open)} aria-expanded={open}>
      <span className={styles.railIcon}><SlidersHorizontal size={17} /></span><span><strong>{title}</strong><small>{summary}</small></span>{actions}<span>{open ? <>收起<ChevronDown size={15} /></> : <>展开<ChevronUp size={15} /></>}</span>
    </button>
    {open && <div className={styles.parameterBody}>{children}</div>}
  </section>;
}
