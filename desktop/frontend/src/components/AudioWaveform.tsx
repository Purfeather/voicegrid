import { useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, RotateCcw, Scissors, Volume2 } from "lucide-react";
import type { VoiceAsset } from "../types";
import { formatDuration } from "../utils/text";
import { IconButton } from "./UI";
import styles from "./audioWaveform.module.css";

interface Props {
  asset: VoiceAsset;
  trimStart: number;
  trimEnd: number | null;
  onTrim: (start: number, end: number | null) => void;
}

export function AudioWaveform({ asset, trimStart, trimEnd, onTrim }: Props) {
  const player = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const duration = asset.health.duration || 0;
  const resolvedEnd = trimEnd == null ? duration : Math.min(duration, trimEnd);
  const points = useMemo(() => asset.health.waveform.length ? asset.health.waveform : Array.from({ length: 80 }, () => 0.1), [asset.health.waveform]);

  useEffect(() => {
    const audio = player.current;
    if (!audio) return;
    const update = () => setPosition(audio.currentTime);
    const ended = () => setPlaying(false);
    audio.addEventListener("timeupdate", update);
    audio.addEventListener("ended", ended);
    return () => { audio.removeEventListener("timeupdate", update); audio.removeEventListener("ended", ended); };
  }, [asset.id]);

  async function toggle() {
    const audio = player.current;
    if (!audio) return;
    if (playing) audio.pause();
    else {
      if (audio.currentTime < trimStart || audio.currentTime >= resolvedEnd) audio.currentTime = trimStart;
      await audio.play();
    }
    setPlaying(!playing);
  }

  function seek(value: number) {
    if (player.current) player.current.currentTime = value;
    setPosition(value);
  }

  return (
    <div className={styles.player}>
      <audio ref={player} src={asset.artifact_url} preload="metadata" />
      <div className={styles.waveform} aria-label="参考音频波形">
        <svg viewBox={`0 0 ${points.length} 100`} preserveAspectRatio="none" role="img" aria-label={`${asset.name} 的波形`}>
          {points.map((point, index) => {
            const height = Math.max(4, Math.min(94, point * 92));
            const time = duration ? index / points.length * duration : 0;
            const active = time >= trimStart && time <= resolvedEnd;
            return <line key={index} x1={index + .5} x2={index + .5} y1={50 - height / 2} y2={50 + height / 2} className={active ? styles.waveActive : styles.waveMuted} />;
          })}
          <line x1={duration ? position / duration * points.length : 0} x2={duration ? position / duration * points.length : 0} y1="0" y2="100" className={styles.playhead} />
        </svg>
      </div>

      <div className={styles.timeRow}><span>{formatDuration(position)}</span><span>{formatDuration(duration)}</span></div>
      <input className={styles.scrubber} aria-label="播放位置" type="range" min={0} max={Math.max(.01, duration)} step={.01} value={Math.min(position, duration)} onChange={(event) => seek(Number(event.target.value))} />

      <div className={styles.transport}>
        <Volume2 size={16} aria-hidden="true" />
        <IconButton label={playing ? "暂停" : "播放"} onClick={toggle}>{playing ? <Pause size={18} /> : <Play size={18} />}</IconButton>
        <IconButton label="回到裁剪起点" onClick={() => seek(trimStart)}><RotateCcw size={17} /></IconButton>
      </div>

      <div className={styles.trimHeader}><span><Scissors size={14} />裁剪范围</span><strong>{formatDuration(trimStart)} — {formatDuration(resolvedEnd)}</strong></div>
      <div className={styles.trimControls}>
        <label>起点<input aria-label="裁剪起点" type="range" min={0} max={Math.max(0, resolvedEnd - .1)} step={.05} value={trimStart} onChange={(event) => onTrim(Math.min(Number(event.target.value), resolvedEnd - .1), trimEnd)} /></label>
        <label>终点<input aria-label="裁剪终点" type="range" min={Math.min(duration, trimStart + .1)} max={Math.max(.1, duration)} step={.05} value={resolvedEnd} onChange={(event) => onTrim(trimStart, Number(event.target.value))} /></label>
      </div>
    </div>
  );
}
