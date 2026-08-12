import type { ReactNode } from "react";
import { BrushCleaning, ChevronDown, ChevronUp, FolderOpen, SlidersHorizontal } from "lucide-react";
import type { ModuleId } from "../../types";
import { Button, IconButton, Section } from "../../components/UI";
import { MODULE_VISUALS } from "./moduleVisuals";
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
  return <Section title="生成与交付" eyebrow="Output engineering" actions={actions}>{children}</Section>;
}

export function ModuleGenerateButton({ module, className = "", disabled = false, onClick }: { module: ModuleId; className?: string; disabled?: boolean; onClick?: () => void | Promise<void> }) {
  const Icon = MODULE_VISUALS[module].icon;
  return <Button className={className} variant="primary" icon={<Icon size={17} />} disabled={disabled} onClick={() => onClick?.()}>开始生成</Button>;
}

export function ModuleCurrentOutput({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return <Section title="当前输出" eyebrow="Monitor" actions={actions}>{children}</Section>;
}

export function ModuleActivityTimeline({ children, actions, className = "" }: { children: ReactNode; actions?: ReactNode; className?: string }) {
  return <Section title="任务与输出" eyebrow="Activity" actions={actions} className={className}>{children}</Section>;
}

export function ModuleActivityActions({ onClear, onOpenFolder, clearDisabled = false, folderDisabled = false }: { onClear?: () => void | Promise<void>; onOpenFolder?: () => void | Promise<void>; clearDisabled?: boolean; folderDisabled?: boolean }) {
  return <div className={styles.activityActions}>
    <IconButton label="清除全部记录" disabled={clearDisabled || !onClear} onClick={() => onClear?.()}><BrushCleaning size={14} /></IconButton>
    <IconButton label="打开输出文件夹" disabled={folderDisabled || !onOpenFolder} onClick={() => onOpenFolder?.()}><FolderOpen size={14} /></IconButton>
  </div>;
}

export function AssetLibrary({ children, count, title = "资源库", eyebrow = "Asset library" }: { children: ReactNode; count?: ReactNode; title?: string; eyebrow?: string }) {
  return <Section title={title} eyebrow={eyebrow} actions={count}>{children}</Section>;
}

export function ModuleParameterRail({ open, onOpen, title, summary, actions, children, locked = false }: { open: boolean; onOpen: (open: boolean) => void; title: string; summary: string; actions?: ReactNode; children: ReactNode; locked?: boolean }) {
  return <section className={`${styles.parameterRail} ${open ? styles.parameterOpen : ""}`}>
    <button className={styles.parameterSummary} disabled={locked} onClick={() => onOpen(!open)} aria-expanded={open}>
      <span className={styles.railIcon}><SlidersHorizontal size={17} /></span><span><strong>{title}</strong><small>{summary}</small></span>{actions}<span>{open ? <>收起<ChevronDown size={15} /></> : <>展开<ChevronUp size={15} /></>}</span>
    </button>
    {open && <div className={styles.parameterBody}>{children}</div>}
  </section>;
}
