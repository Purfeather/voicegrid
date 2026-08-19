import { useRef, useState, type ReactNode } from "react";

const MAX_FILE_SIZE = 256 * 1024 * 1024;
const AUDIO_EXTENSIONS = new Set([".wav", ".flac", ".mp3", ".ogg", ".m4a"]);

interface Props {
  busy: boolean;
  disabled?: boolean;
  className: string;
  onFile: (file: File) => void | Promise<void>;
  onError: (message: string) => void;
  children: (dragActive: boolean) => ReactNode;
}

function isAudioFile(file: File): boolean {
  const extension = file.name.includes(".") ? file.name.slice(file.name.lastIndexOf(".")).toLowerCase() : "";
  return file.type.startsWith("audio/") || AUDIO_EXTENSIONS.has(extension);
}

export function AudioDropZone({ busy, disabled = false, className, onFile, onError, children }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [dragActive, setDragActive] = useState(false);
  const blocked = disabled || busy;

  function resetDrag() {
    dragDepth.current = 0;
    setDragActive(false);
  }

  function accept(file: File | undefined) {
    resetDrag();
    if (!file) return;
    if (file.size <= 0) {
      onError("上传文件为空，请重新选择音频。");
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      onError("音频文件不能超过 256 MB。");
      return;
    }
    if (!isAudioFile(file)) {
      onError("请选择 WAV、FLAC、MP3、OGG 或 M4A 音频文件。");
      return;
    }
    void onFile(file);
  }

  return (
    <>
      <button
        type="button"
        className={className}
        disabled={blocked}
        aria-busy={busy}
        onClick={() => inputRef.current?.click()}
        onDragEnter={(event) => {
          event.preventDefault();
          if (blocked) return;
          dragDepth.current += 1;
          setDragActive(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!blocked) event.dataTransfer.dropEffect = "copy";
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          if (blocked) return;
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (!dragDepth.current) setDragActive(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          if (blocked) {
            resetDrag();
            return;
          }
          const files = Array.from(event.dataTransfer.files);
          if (files.length > 1) {
            resetDrag();
            onError("一次只能上传一个参考音频。");
            return;
          }
          accept(files[0]);
        }}
      >
        {children(dragActive)}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="audio/*,.wav,.flac,.mp3,.ogg,.m4a"
        hidden
        onChange={(event) => {
          accept(event.target.files?.[0]);
          event.currentTarget.value = "";
        }}
      />
    </>
  );
}
