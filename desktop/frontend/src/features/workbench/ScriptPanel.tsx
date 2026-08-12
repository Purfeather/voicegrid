import { useEffect, useMemo, useState } from "react";
import { AlignLeft, BookmarkPlus, Languages, Lock, Scissors, Sparkles, Trash2, X } from "lucide-react";
import type { StylePreset, WorkspaceDraft } from "../../types";
import { api } from "../../services/api";
import { splitText } from "../../utils/text";
import { Badge, Button, Field, IconButton, Section, Select, TextArea, TextInput } from "../../components/UI";
import styles from "./workbench.module.css";

interface Props {
  workspace: WorkspaceDraft;
  stylesList: StylePreset[];
  languages: Array<{ value: string; label: string }>;
  onWorkspace: (patch: Partial<WorkspaceDraft>) => void;
  onStylesChanged: () => Promise<void>;
  onMessage: (message: string, tone?: "success" | "error") => void;
}

export function ScriptPanel({ workspace, stylesList, languages, onWorkspace, onStylesChanged, onMessage }: Props) {
  const [customName, setCustomName] = useState("");
  const segments = useMemo(() => splitText(workspace.text, workspace.parameters.segment_chars), [workspace.text, workspace.parameters.segment_chars]);
  const selectedStyle = stylesList.find((style) => style.name === workspace.style);
  const count = workspace.text.trim().length;

  useEffect(() => {
    if (workspace.target_duration_enabled && segments.length !== 1) {
      onWorkspace({ target_duration_enabled: false });
      onMessage("目标时长仅支持单段文本，已自动关闭。", "error");
    }
  }, [segments.length, workspace.target_duration_enabled]);

  function selectStyle(name: string) {
    const style = stylesList.find((item) => item.name === name);
    onWorkspace({ style: name, instruction: style?.instruction || workspace.instruction });
  }

  async function saveStyle() {
    if (!customName.trim() || !workspace.instruction.trim()) return;
    try {
      const saved = await api.saveStyle(customName.trim(), workspace.instruction.trim());
      await onStylesChanged();
      onWorkspace({ style: saved.name });
      setCustomName("");
      onMessage("自定义风格已保存。", "success");
    } catch (error) { onMessage(error instanceof Error ? error.message : "保存失败", "error"); }
  }

  async function deleteStyle() {
    if (!selectedStyle || selectedStyle.built_in) return;
    if (!window.confirm(`删除自定义风格“${selectedStyle.name}”吗？`)) return;
    try {
      await api.deleteStyle(selectedStyle.name);
      await onStylesChanged();
      const fallback = stylesList.find((item) => item.built_in);
      if (fallback) onWorkspace({ style: fallback.name, instruction: fallback.instruction });
      onMessage("自定义风格已删除。", "success");
    } catch (error) { onMessage(error instanceof Error ? error.message : "删除失败", "error"); }
  }

  return (
    <div className={styles.scriptColumn}>
      <Section title="表演设定" eyebrow="Direction" className={styles.directionSection}>
        <div className={styles.directionGrid}>
          <Field label="语言" compact><Select value={workspace.language} onChange={(event) => onWorkspace({ language: event.target.value })}>{languages.map((language) => <option key={language.value} value={language.value}>{language.label}</option>)}</Select></Field>
          <Field label="风格 / 情感预设" compact><Select value={workspace.style} onChange={(event) => selectStyle(event.target.value)}>{stylesList.map((style) => <option key={style.name} value={style.name}>{style.name}{style.built_in ? "" : " · 自定义"}</option>)}</Select></Field>
          <Field label="目标时长" compact>
            <div className={styles.durationField}>
              <button
                type="button"
                className={`${styles.durationSwitch} ${workspace.target_duration_enabled ? styles.durationSwitchOn : ""}`}
                role="switch"
                aria-checked={workspace.target_duration_enabled}
                aria-label="启用目标时长"
                disabled={segments.length !== 1}
                title={segments.length !== 1 ? "目标时长仅支持单段文本" : ""}
                onClick={() => onWorkspace({ target_duration_enabled: !workspace.target_duration_enabled })}
              ><span /></button>
              <input
                type="number"
                min={1}
                max={120}
                step={1}
                disabled={!workspace.target_duration_enabled}
                value={workspace.target_duration_enabled ? workspace.target_duration_seconds : ""}
                placeholder="自动"
                aria-label="目标时长（秒）"
                onChange={(event) => onWorkspace({ target_duration_seconds: Math.max(1, Math.min(120, Number(event.target.value) || 1)) })}
              />
              <strong>秒</strong>
            </div>
          </Field>
        </div>
        <div className={styles.instructionRow}>
          <TextArea aria-label="风格和情感提示" rows={3} value={workspace.instruction} onChange={(event) => onWorkspace({ instruction: event.target.value })} placeholder="描述声音状态、语气、节奏、情绪推进和停顿方式…" />
          <div className={styles.styleActions}>
            <TextInput aria-label="自定义风格名称" value={customName} onChange={(event) => setCustomName(event.target.value)} placeholder="保存为新风格" />
            <Button icon={<BookmarkPlus size={15} />} disabled={!customName.trim() || !workspace.instruction.trim()} onClick={saveStyle}>保存</Button>
            <IconButton label={selectedStyle?.built_in ? "无法删除初始预设" : "删除自定义风格"} disabled={!selectedStyle || selectedStyle.built_in} onClick={deleteStyle}><Trash2 size={15} /></IconButton>
          </div>
          {selectedStyle?.built_in && <span className={styles.protectedNote}><Lock size={12} />无法删除初始预设</span>}
        </div>
      </Section>

      <Section title="配音文本" eyebrow="Script" className={styles.editorSection} actions={<div className={styles.editorMeta}><Badge tone={count > workspace.parameters.segment_chars ? "warning" : "neutral"}>{count} 字</Badge><IconButton label="清空配音文本" disabled={!workspace.text} onClick={() => onWorkspace({ text: "" })}><X size={16} /></IconButton></div>}>
        <div className={styles.editorWrap}>
          <TextArea className={styles.scriptEditor} aria-label="配音文本" spellCheck={false} value={workspace.text} onChange={(event) => onWorkspace({ text: event.target.value })} placeholder="输入或粘贴需要配音的文本…" />
        </div>
      </Section>

      <Section title="切分预览" eyebrow="Live segmentation" className={styles.segmentSection} actions={<Badge tone="accent"><Scissors size={12} />{segments.length} 段</Badge>}>
        <div className={styles.segmentList} aria-live="polite">
          {segments.length ? segments.map((segment, index) => <article key={`${index}-${segment.slice(0, 16)}`}><span>{String(index + 1).padStart(2, "0")}</span><p>{segment}</p><strong>{segment.length} 字</strong></article>) : <div className={styles.segmentEmpty}><AlignLeft size={18} /><span>输入文本后会立即显示切分结果。</span></div>}
        </div>
      </Section>
    </div>
  );
}
