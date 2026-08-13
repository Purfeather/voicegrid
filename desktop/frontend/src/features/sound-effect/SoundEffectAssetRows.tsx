import { AudioLines, Heart, Pencil, Play, Square, Trash2 } from "lucide-react";
import type { OutputRecord } from "../../types";
import { useAssetPreview } from "../../hooks/useAssetPreview";
import { EmptyState, IconButton } from "../../components/UI";
import styles from "./soundEffect.module.css";

export function SoundEffectAssetRows({ outputs, selectedId, onSelect, onFavorite, onRename, onDelete, onMessage }: {
  outputs: OutputRecord[];
  selectedId?: string | null;
  onSelect: (output: OutputRecord) => void;
  onFavorite: (output: OutputRecord) => void | Promise<void>;
  onRename: (output: OutputRecord) => void | Promise<void>;
  onDelete: (output: OutputRecord) => void | Promise<void>;
  onMessage: (message: string, tone?: "success" | "error") => void;
}) {
  const preview = useAssetPreview({
    assetIds: outputs.map((output) => output.id),
    onError: (message) => onMessage(message, "error"),
  });

  function remove(output: OutputRecord) {
    if (!window.confirm(`删除音效“${output.filename}”及其音频文件吗？`)) return;
    preview.stop(output.id);
    void onDelete(output);
  }

  return <div className={styles.assetRows}>
    {outputs.map((output) => <article key={output.id} className={`${styles.assetRow} ${selectedId === output.id ? styles.assetRowActive : ""}`}>
      <button className={styles.assetSelect} onClick={() => onSelect(output)}>
        <span className={styles.assetIcon}><AudioLines size={15} /></span>
        <span><strong>{output.filename}</strong><small>{output.duration.toFixed(1)} 秒 · {output.sample_rate / 1000} kHz</small></span>
      </button>
      <div className={styles.assetActions}>
        <IconButton
          className={preview.playingId === output.id ? styles.assetPreviewActive : ""}
          label={`${preview.playingId === output.id ? "停止试听" : "试听"} ${output.filename}`}
          aria-pressed={preview.playingId === output.id}
          onClick={() => {
            onSelect(output);
            void preview.toggle(output.id, output.artifact_url);
          }}
        >
          {preview.playingId === output.id ? <Square size={12} fill="currentColor" /> : <Play size={13} />}
        </IconButton>
        <IconButton label={output.favorite ? "取消收藏" : "收藏"} onClick={() => onFavorite(output)}><Heart size={13} fill={output.favorite ? "currentColor" : "none"} /></IconButton>
        <IconButton label="重命名音效" onClick={() => onRename(output)}><Pencil size={13} /></IconButton>
        <IconButton label="删除音效" onClick={() => remove(output)}><Trash2 size={13} /></IconButton>
      </div>
    </article>)}
    {!outputs.length && <EmptyState title="项目素材库为空" detail="生成完成的音效会自动保存在这里。" />}
  </div>;
}
