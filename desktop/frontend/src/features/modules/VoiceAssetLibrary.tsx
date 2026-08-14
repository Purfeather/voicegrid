import { Check, Pencil, Play, Square, Trash2, Waves } from "lucide-react";
import type { VoiceAsset } from "../../types";
import { api } from "../../services/api";
import { useAssetPreview } from "../../hooks/useAssetPreview";
import { Badge, EmptyState, IconButton } from "../../components/UI";
import { AssetLibrary } from "./ModuleWorkbenchShell";
import styles from "./moduleWorkbenchShell.module.css";

export function VoiceAssetLibrary({ voices, selectedId, onSelect, onChanged, onMessage, onRemoved, locked = false }: {
  voices: VoiceAsset[];
  selectedId?: string | null;
  onSelect?: (voice: VoiceAsset) => void;
  onChanged: () => Promise<void>;
  onMessage: (message: string, tone?: "success" | "error") => void;
  onRemoved?: (voice: VoiceAsset) => void;
  locked?: boolean;
}) {
  const saved = voices.filter((voice) => voice.saved);
  const preview = useAssetPreview({
    assetIds: saved.map((voice) => voice.id),
    onError: (message) => onMessage(message, "error"),
  });
  async function rename(voice: VoiceAsset) {
    const name = window.prompt("输入新的音色名称", voice.name)?.trim();
    if (!name || name === voice.name) return;
    try { await api.renameVoice(voice.id, name); await onChanged(); onMessage("音色名称已更新。", "success"); }
    catch (error) { onMessage(error instanceof Error ? error.message : "重命名失败", "error"); }
  }
  async function remove(voice: VoiceAsset) {
    if (!window.confirm(`确定删除音色“${voice.name}”及其本地音频文件吗？`)) return;
    preview.stop(voice.id);
    try { await api.deleteVoice(voice.id, true); onRemoved?.(voice); await onChanged(); onMessage("音色已删除。", "success"); }
    catch (error) { onMessage(error instanceof Error ? error.message : "删除失败", "error"); }
  }
  return <AssetLibrary title="音色库" eyebrow="SAVED VOICES" count={<Badge>{saved.length} 个</Badge>}>
    <div className={styles.assetRows} aria-disabled={locked} inert={locked}>
      {saved.length ? saved.map((voice) => <div key={voice.id} className={`${styles.assetRow} ${selectedId === voice.id ? styles.assetRowActive : ""}`}>
        <button className={styles.assetSelect} disabled={!onSelect || voice.available === false} onClick={() => onSelect?.(voice)}>
          <span className={styles.assetIcon}>{selectedId === voice.id ? <Check size={15} /> : <Waves size={15} />}</span>
          <span><strong>{voice.name}</strong><small>{voice.available === false ? "音频文件不可用" : voice.health.suitability + " · " + voice.health.duration.toFixed(1) + " 秒"}</small></span>
        </button>
        <div className={styles.assetActions}>
          <IconButton className={preview.playingId === voice.id ? styles.assetPreviewActive : ""} label={`${preview.playingId === voice.id ? "停止试听" : "试听"} ${voice.name}`} aria-pressed={preview.playingId === voice.id} disabled={voice.available === false} onClick={() => void preview.toggle(voice.id, voice.artifact_url)}>{preview.playingId === voice.id ? <Square size={13} fill="currentColor" /> : <Play size={14} />}</IconButton>
          <IconButton label={`重命名 ${voice.name}`} onClick={() => rename(voice)}><Pencil size={14} /></IconButton>
          <IconButton label={`删除 ${voice.name}`} onClick={() => remove(voice)}><Trash2 size={14} /></IconButton>
        </div>
      </div>) : <EmptyState title="音色库为空" detail="保存参考音频或设计音色后，会统一显示在这里。" />}
    </div>
  </AssetLibrary>;
}
