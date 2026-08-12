import { useMemo, useRef, useState, type ReactNode } from "react";
import { FileAudio2, Save, Upload } from "lucide-react";
import type { VoiceAsset, WorkspaceDraft } from "../../types";
import { api } from "../../services/api";
import { AudioWaveform } from "../../components/AudioWaveform";
import { Badge, Button, EmptyState, Section, TextInput } from "../../components/UI";
import { VoiceAssetLibrary } from "../modules/VoiceAssetLibrary";
import styles from "./workbench.module.css";

interface Props {
  voices: VoiceAsset[];
  workspace: WorkspaceDraft;
  onWorkspace: (patch: Partial<WorkspaceDraft>) => void;
  onVoicesChanged: () => Promise<void>;
  onMessage: (message: string, tone?: "success" | "error") => void;
  leading?: ReactNode;
  locked?: boolean;
}

export function VoicePanel({ voices, workspace, onWorkspace, onVoicesChanged, onMessage, leading, locked = false }: Props) {
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

  return (
    <div className={styles.columnScroll}>
      {leading}
      <div className={`${styles.columnContent} ${locked ? styles.previewLocked : ""}`} aria-disabled={locked} inert={locked}>
      <Section title="参考音色" eyebrow="Voice material" actions={<Badge tone={selected ? "accent" : "neutral"}>{selected ? "已启用" : "未选择"}</Badge>}>
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
          </> : <EmptyState title="等待参考音频" detail="可上传临时音频直接生成，或从下方音色库选择。" />}
        </div>
      </Section>

      <VoiceAssetLibrary voices={voices} selectedId={workspace.voice_id} onSelect={choose} onChanged={onVoicesChanged} onMessage={onMessage} onRemoved={(voice) => { if (selectedId === voice.id) onWorkspace({ voice_id: null, reference_id: null, reference_trim_start: 0, reference_trim_end: null }); }} />
      </div>
    </div>
  );
}
