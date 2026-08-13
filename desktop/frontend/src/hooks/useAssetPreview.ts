import { useCallback, useEffect, useRef, useState } from "react";

interface AssetPreviewOptions {
  assetIds: string[];
  onError?: (message: string) => void;
}

export function useAssetPreview({ assetIds, onError }: AssetPreviewOptions) {
  const [playingId, setPlayingId] = useState<string | null>(null);
  const playingIdRef = useRef<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const requestRef = useRef(0);
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const stop = useCallback((assetId?: string) => {
    if (assetId && playingIdRef.current !== assetId) return;
    requestRef.current += 1;
    const audio = audioRef.current;
    audioRef.current = null;
    if (audio) {
      audio.onended = null;
      audio.onerror = null;
      audio.pause();
      audio.currentTime = 0;
    }
    playingIdRef.current = null;
    setPlayingId(null);
  }, []);

  const toggle = useCallback(async (assetId: string, source: string) => {
    if (playingIdRef.current === assetId) {
      stop(assetId);
      return;
    }

    stop();
    const request = requestRef.current;
    const audio = new Audio(source);
    audioRef.current = audio;
    playingIdRef.current = assetId;
    setPlayingId(assetId);

    const finish = () => {
      if (requestRef.current !== request || audioRef.current !== audio) return;
      stop(assetId);
    };
    audio.onended = finish;
    audio.onerror = () => {
      finish();
      onErrorRef.current?.("音频试听失败，请检查素材文件。");
    };

    try {
      await audio.play();
      if (requestRef.current !== request || audioRef.current !== audio) {
        audio.pause();
        audio.currentTime = 0;
      }
    } catch (error) {
      if (requestRef.current === request && audioRef.current === audio) {
        finish();
        onErrorRef.current?.(error instanceof Error ? error.message : "音频试听失败，请检查素材文件。");
      }
    }
  }, [stop]);

  useEffect(() => {
    if (playingIdRef.current && !assetIds.includes(playingIdRef.current)) stop();
  }, [assetIds, stop]);

  useEffect(() => () => stop(), [stop]);

  return { playingId, stop, toggle };
}
