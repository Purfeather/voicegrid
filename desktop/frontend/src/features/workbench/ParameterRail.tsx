import { ChevronDown, ChevronUp, Gauge, Info, SlidersHorizontal } from "lucide-react";
import { PARAMETER_HELP, PARAMETER_PRESETS } from "../../data";
import type { SynthesisParameters, WorkspaceDraft } from "../../types";
import { Badge, Field, Select, TextInput } from "../../components/UI";
import styles from "./workbench.module.css";

interface Props {
  open: boolean;
  workspace: WorkspaceDraft;
  onOpen: (open: boolean) => void;
  onWorkspace: (patch: Partial<WorkspaceDraft>) => void;
  locked?: boolean;
}

const fields: Array<{ key: keyof SynthesisParameters; label: string; min: number; max: number; step: number }> = [
  { key: "temperature", label: "Temperature", min: .1, max: 3, step: .1 },
  { key: "top_p", label: "Top-P", min: .1, max: 1, step: .05 },
  { key: "top_k", label: "Top-K", min: 1, max: 200, step: 1 },
  { key: "repetition_penalty", label: "重复惩罚", min: .5, max: 2, step: .05 },
  { key: "max_seconds", label: "每段最大秒数", min: 5, max: 300, step: 5 },
  { key: "segment_chars", label: "每段最大字符", min: 20, max: 1000, step: 10 },
  { key: "pause_ms", label: "段间停顿（ms）", min: 0, max: 2000, step: 20 },
  { key: "seed", label: "随机种子", min: 0, max: 2147483647, step: 1 },
];

export function ParameterRail({ open, workspace, onOpen, onWorkspace, locked = false }: Props) {
  function choosePreset(preset: "标准" | "兼容") {
    onWorkspace({ preset, parameters: { ...PARAMETER_PRESETS[preset] } });
  }

  function update(key: keyof SynthesisParameters, value: number) {
    onWorkspace({ parameters: { ...workspace.parameters, [key]: value } });
  }

  return (
    <section className={`${styles.parameterRail} ${open ? styles.parameterOpen : ""}`}>
      <button className={styles.parameterSummary} disabled={locked} onClick={() => onOpen(!open)} aria-expanded={open}>
        <span className={styles.railIcon}><SlidersHorizontal size={17} /></span>
        <span><strong>高级生成参数</strong><small>{workspace.preset} · {workspace.parameters.segment_chars} 字 · {workspace.parameters.max_seconds} 秒 · Top-K {workspace.parameters.top_k}</small></span>
        <div className={styles.presetToggle} role="group" aria-label="高级参数预设" onClick={(event) => event.stopPropagation()}>
          {(["标准", "兼容"] as const).map((preset) => <button key={preset} className={workspace.preset === preset ? styles.presetActive : ""} onClick={() => choosePreset(preset)}>{preset}</button>)}
        </div>
        <span className={styles.expandLabel}>{open ? "收起" : "展开"}{open ? <ChevronDown size={15} /> : <ChevronUp size={15} />}</span>
      </button>
      {open && <div className={styles.parameterBody} inert={locked}>
        <div className={styles.parameterGrid}>
          {fields.map((field) => <Field key={field.key} label={field.label} help={PARAMETER_HELP[field.key]} compact><TextInput type="number" min={field.min} max={field.max} step={field.step} value={workspace.parameters[field.key]} onChange={(event) => update(field.key, Number(event.target.value))} /></Field>)}
        </div>
        <aside className={styles.memoryGuide}>
          <header><Info size={15} /><div><strong>每段字符建议</strong><span>MOSS-TTS 1.5 · 4B 保守起点</span></div></header>
          <table><tbody><tr><th>12GB</th><td>200 字</td></tr><tr><th>16GB</th><td>400 字</td></tr><tr><th>24GB</th><td>600 字</td></tr><tr><th>32GB 以上</th><td>800 字</td></tr></tbody></table>
          <p>8GB 以下不建议运行本模型。长文本仍受内容、参考音频和驱动环境影响。</p>
        </aside>
      </div>}
    </section>
  );
}
