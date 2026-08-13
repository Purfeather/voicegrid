import { useMemo, useRef, useState, type ReactNode } from "react";
import { FileAudio2, Info, Save, Sparkles, Upload } from "lucide-react";
import type { VoiceAsset, WorkspaceDraft } from "../../types";
import { api } from "../../services/api";
import { AudioWaveform } from "../../components/AudioWaveform";
import { Badge, Button, Section, TextInput } from "../../components/UI";
import { VoiceAssetLibrary } from "../modules/VoiceAssetLibrary";
import styles from "./workbench.module.css";

interface Props {
  voices: VoiceAsset[];
  workspace: WorkspaceDraft;
  onWorkspace: (patch: Partial<WorkspaceDraft>) => void;
  onVoicesChanged: () => Promise<void>;
  onMessage: (message: string, tone?: "success" | "error") => void;
  onOpenVoiceDesign: () => void;
  leading?: ReactNode;
  locked?: boolean;
}

export function VoicePanel({ voices, workspace, onWorkspace, onVoicesChanged, onMessage, onOpenVoiceDesign, leading, locked = false }: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [saveName, setSaveName] = useState("");
  const selectedId = workspace.voice_id || workspace.reference_id;
  const selected = useMemo(() => voices.find((voice) => voice.id === selectedId) || null, [voices, selectedId]);

  async function upload(file?: File) {
    if (!file) return;
    setBusy(true);
    try {
      const voice = await api.uploadVoice(file);
      await onVoicesChanged();
      onWorkspace({ reference_id: voice.id, voice_id: null, reference_trim_start: 0, reference_trim_end: null });
      setSaveName(file.name.replace(/\.[^.]+$/, ""));
      onMessage("参考音频已上传并直接启用。", "success");
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "上传失败", "error");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function save() {
    if (!selected || selected.saved || !saveName.trim()) return;
    setBusy(true);
    try {
      const voice = await api.saveVoice(selected.id, saveName.trim());
      await onVoicesChanged();
      onWorkspace({ voice_id: voice.id, reference_id: null });
      onMessage("音色已保存到音色库。", "success");
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "保存失败", "error");
    } finally { setBusy(false); }
  }

  function choose(voice: VoiceAsset) {
    onWorkspace(voice.saved ? { voice_id: voice.id, reference_id: null, reference_trim_start: 0, reference_trim_end: null } : { reference_id: voice.id, voice_id: null, reference_trim_start: 0, reference_trim_end: null });
  }

  function toggleReference() {
    if (!selected) {
      onMessage("请上传真人参考音频，或从音色库选择音色。", "success");
      return;
    }
    onWorkspace({ voice_id: null, reference_id: null, reference_trim_start: 0, reference_trim_end: null });
    onMessage("已切换为无参考模式。", "success");
  }

  return (
    <div className={styles.columnScroll}>
      {leading}
      <div className={`${styles.columnContent} ${locked ? styles.previewLocked : ""}`} aria-disabled={locked} inert={locked}>
      <Section title="参考音色" eyebrow="Voice material" actions={
        <button
          type="button"
          className={`${styles.referenceSwitch} ${selected ? styles.referenceSwitchOn : styles.referenceSwitchOff}`}
          role="switch"
          aria-checked={Boolean(selected)}
          aria-label={selected ? "关闭参考音色，切换为无参考模式" : "当前为无参考模式，选择参考音色后开启"}
          onClick={toggleReference}
        >
          <span aria-hidden="true"><i /></span>
          <strong>{selected ? "参考开启" : "无参考"}</strong>
        </button>
      }>
        <div className={styles.sectionBody}>
          <button className={styles.uploadZone} onClick={() => fileInput.current?.click()} disabled={busy}>
            <span><Upload size={18} /></span><strong>{busy ? "正在分析音频…" : "上传参考音频"}</strong><small>上传后会直接用于生成，无需先保存</small>
          </button>
          <input ref={fileInput} type="file" accept="audio/*,.wav,.flac,.mp3,.ogg,.m4a" hidden onChange={(event) => upload(event.target.files?.[0])} />

          {selected ? <>
            <div className={styles.assetHeading}><div><FileAudio2 size={16} /><span><strong>{selected.name}</strong><small>{selected.saved ? "音色库资产" : "临时参考"}</small></span></div><Badge tone={selected.health.score >= 78 ? "success" : selected.health.score >= 55 ? "warning" : "danger"}>{selected.health.score} · {selected.health.suitability}</Badge></div>
            <AudioWaveform asset={selected} trimStart={workspace.reference_trim_start} trimEnd={workspace.reference_trim_end} onTrim={(start, end) => onWorkspace({ reference_trim_start: start, reference_trim_end: end })} />
            <div className={styles.healthFacts}><span>采样率<strong>{selected.health.sample_rate / 1000} kHz</strong></span><span>信噪比<strong>{selected.health.snr_db} dB</strong></span><span>静音占比<strong>{selected.health.silence_ratio}%</strong></span></div>
            <ul className={styles.findings}>{selected.health.findings.slice(0, 2).map((finding, index) => <li key={`${finding.message}-${index}`} data-level={finding.level}>{finding.message}</li>)}</ul>
            {!selected.saved && <div className={styles.saveVoice}><TextInput aria-label="保存的音色名称" value={saveName} onChange={(event) => setSaveName(event.target.value)} placeholder="输入音色名称" /><Button icon={<Save size={15} />} busy={busy} disabled={!saveName.trim()} onClick={save}>保存到音色库</Button></div>}
          </> : <aside className={styles.noReferenceNotice} aria-label="无参考模式说明">
            <Info size={17} aria-hidden="true" />
            <div>
              <strong>当前为无参考模式</strong>
              <p>模型将自行生成音色，不同任务之间的音色可能发生变化，稳定性和可复现性低于参考音色克隆。</p>
              <p className={styles.noReferenceRecommendation}>正式配音制作建议使用真人参考音频，或前往“音色设计”创建并保存专用音色。</p>
              <p>无参考模式适合快速试听、临时样片和寻找声音方向。</p>
              <button type="button" onClick={onOpenVoiceDesign}><Sparkles size={14} aria-hidden="true" />前往音色设计</button>
            </div>
          </aside>}
        </div>
      </Section>

      <VoiceAssetLibrary voices={voices} selectedId={workspace.voice_id} onSelect={choose} onChanged={onVoicesChanged} onMessage={onMessage} onRemoved={(voice) => { if (selectedId === voice.id) onWorkspace({ voice_id: null, reference_id: null, reference_trim_start: 0, reference_trim_end: null }); }} />
      </div>
    </div>
  );
}
