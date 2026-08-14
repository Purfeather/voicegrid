import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Pause, Play, RotateCcw, Scissors } from "lucide-react";
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

type DragMode = "move" | "start" | "end";

interface DragState {
  mode: DragMode;
  pointerTime: number;
  start: number;
  end: number;
}

const MIN_SELECTION_SECONDS = 0.1;

export function AudioWaveform({ asset, trimStart, trimEnd, onTrim }: Props) {
  const player = useRef<HTMLAudioElement>(null);
  const waveform = useRef<HTMLDivElement>(null);
  const drag = useRef<DragState | null>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [trimVisible, setTrimVisible] = useState(false);
  const duration = asset.health.duration || 0;
  const safeStart = Math.max(0, Math.min(trimStart, Math.max(0, duration - MIN_SELECTION_SECONDS)));
  const resolvedEnd = Math.max(safeStart + Math.min(MIN_SELECTION_SECONDS, duration), trimEnd == null ? duration : Math.min(duration, trimEnd));
  const points = useMemo(() => asset.health.waveform.length ? asset.health.waveform : Array.from({ length: 80 }, () => 0.1), [asset.health.waveform]);

  useEffect(() => {
    const audio = player.current;
    if (!audio) return;
    const update = () => {
      if (audio.currentTime >= resolvedEnd && !audio.paused) {
        audio.pause();
        audio.currentTime = safeStart;
        setPlaying(false);
        setPosition(safeStart);
        return;
      }
      setPosition(audio.currentTime);
    };
    const ended = () => setPlaying(false);
    audio.addEventListener("timeupdate", update);
    audio.addEventListener("ended", ended);
    return () => { audio.removeEventListener("timeupdate", update); audio.removeEventListener("ended", ended); };
  }, [asset.id, resolvedEnd, safeStart]);

  async function toggle() {
    const audio = player.current;
    if (!audio) return;
    if (playing) audio.pause();
    else {
      if (audio.currentTime < safeStart || audio.currentTime >= resolvedEnd) audio.currentTime = safeStart;
      await audio.play();
    }
    setPlaying(!playing);
  }

  function seek(value: number) {
    if (player.current) player.current.currentTime = value;
    setPosition(value);
  }

  function timeFromPointer(clientX: number) {
    const bounds = waveform.current?.getBoundingClientRect();
    if (!bounds || !duration) return 0;
    return Math.max(0, Math.min(duration, (clientX - bounds.left) / bounds.width * duration));
  }

  function beginDrag(mode: DragMode, event: ReactPointerEvent<HTMLElement>) {
    if (!duration) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { mode, pointerTime: timeFromPointer(event.clientX), start: safeStart, end: resolvedEnd };
  }

  function updateDrag(event: ReactPointerEvent<HTMLElement>) {
    const state = drag.current;
    if (!state || !duration) return;
    const pointerTime = timeFromPointer(event.clientX);
    const minimum = Math.min(MIN_SELECTION_SECONDS, duration);
    let start = state.start;
    let end = state.end;

    if (state.mode === "start") {
      start = Math.min(Math.max(0, pointerTime), end - minimum);
    } else if (state.mode === "end") {
      end = Math.max(Math.min(duration, pointerTime), start + minimum);
    } else {
      const width = state.end - state.start;
      start = Math.max(0, Math.min(duration - width, state.start + pointerTime - state.pointerTime));
      end = start + width;
    }

    start = Math.round(start * 100) / 100;
    end = Math.round(end * 100) / 100;
    onTrim(start, end >= duration - 0.01 ? null : end);
  }

  function endDrag(event: ReactPointerEvent<HTMLElement>) {
    if (drag.current && event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    drag.current = null;
  }

  const selectionLeft = duration ? safeStart / duration * 100 : 0;
  const selectionWidth = duration ? (resolvedEnd - safeStart) / duration * 100 : 100;

  return (
    <div className={styles.player}>
      <audio ref={player} src={asset.artifact_url} preload="metadata" />
      <div ref={waveform} className={styles.waveform} aria-label="参考音频波形">
        <svg viewBox={`0 0 ${points.length} 100`} preserveAspectRatio="none" role="img" aria-label={`${asset.name} 的波形`}>
          {points.map((point, index) => {
            const height = Math.max(4, Math.min(94, point * 92));
            const time = duration ? index / points.length * duration : 0;
            const active = time >= safeStart && time <= resolvedEnd;
            return <line key={index} x1={index + .5} x2={index + .5} y1={50 - height / 2} y2={50 + height / 2} className={active ? styles.waveActive : styles.waveMuted} />;
          })}
          <line x1={duration ? position / duration * points.length : 0} x2={duration ? position / duration * points.length : 0} y1="0" y2="100" className={styles.playhead} />
        </svg>
        {trimVisible && duration > 0 && <>
          <span className={styles.trimShade} style={{ insetInlineStart: 0, width: `${selectionLeft}%` }} />
          <span className={styles.trimShade} style={{ insetInlineEnd: 0, width: `${Math.max(0, 100 - selectionLeft - selectionWidth)}%` }} />
          <div
            className={styles.trimSelection}
            style={{ insetInlineStart: `${selectionLeft}%`, width: `${selectionWidth}%` }}
            onPointerDown={(event) => beginDrag("move", event)}
            onPointerMove={updateDrag}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
          >
            <button className={styles.trimHandleStart} aria-label="拖动裁剪起点" onPointerDown={(event) => beginDrag("start", event)} />
            <span className={styles.trimGrip}><Scissors size={12} />拖动选区</span>
            <button className={styles.trimHandleEnd} aria-label="拖动裁剪终点" onPointerDown={(event) => beginDrag("end", event)} />
          </div>
        </>}
      </div>

      <div className={styles.timeRow}><span>{formatDuration(position)}</span><span>{formatDuration(duration)}</span></div>
      <input className={styles.scrubber} aria-label="播放位置" type="range" min={0} max={Math.max(.01, duration)} step={.01} value={Math.min(position, duration)} onChange={(event) => seek(Number(event.target.value))} />

      <div className={styles.transport}>
        <button className={trimVisible ? styles.trimToggleActive : styles.trimToggle} onClick={() => setTrimVisible((visible) => !visible)}>
          <Scissors size={14} />{trimVisible ? "收起裁剪框" : "裁剪"}
        </button>
        <div className={styles.transportControls}>
          <IconButton className={styles.playButton} label={playing ? "暂停" : "播放"} onClick={toggle}>{playing ? <Pause size={18} /> : <Play size={18} />}</IconButton>
          <IconButton className={styles.resetButton} label="回到裁剪起点" onClick={() => seek(safeStart)}><RotateCcw size={15} /></IconButton>
        </div>
        <strong>{formatDuration(safeStart)} — {formatDuration(resolvedEnd)}</strong>
      </div>
    </div>
  );
}
