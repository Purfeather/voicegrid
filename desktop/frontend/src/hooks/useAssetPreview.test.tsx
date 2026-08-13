import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MockAudio } from "../test/mockAudio";
import { useAssetPreview } from "./useAssetPreview";

function PreviewHarness({ ids = ["a", "b"], onError = vi.fn() }: { ids?: string[]; onError?: (message: string) => void }) {
  const preview = useAssetPreview({ assetIds: ids, onError });
  return <>
    {ids.map((id) => <button key={id} onClick={() => void preview.toggle(id, `/${id}.wav`)}>{preview.playingId === id ? `停止 ${id}` : `播放 ${id}`}</button>)}
  </>;
}

beforeEach(() => MockAudio.install());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("useAssetPreview", () => {
  it("stops and rewinds the previous asset before playing another", async () => {
    render(<PreviewHarness />);
    fireEvent.click(screen.getByRole("button", { name: "播放 a" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "停止 a" })).toBeInTheDocument());
    const first = MockAudio.instances[0];
    first.currentTime = 2.5;

    fireEvent.click(screen.getByRole("button", { name: "播放 b" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "停止 b" })).toBeInTheDocument());
    expect(first.pause).toHaveBeenCalledOnce();
    expect(first.currentTime).toBe(0);
    expect(MockAudio.instances[1].play).toHaveBeenCalledOnce();
  });

  it("stops the active asset on a second click and restarts from zero next time", async () => {
    render(<PreviewHarness ids={["a"]} />);
    fireEvent.click(screen.getByRole("button", { name: "播放 a" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "停止 a" })).toBeInTheDocument());
    const first = MockAudio.instances[0];
    first.currentTime = 1.25;

    fireEvent.click(screen.getByRole("button", { name: "停止 a" }));
    expect(screen.getByRole("button", { name: "播放 a" })).toBeInTheDocument();
    expect(first.pause).toHaveBeenCalledOnce();
    expect(first.currentTime).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: "播放 a" }));
    expect(MockAudio.instances).toHaveLength(2);
    expect(MockAudio.instances[1].currentTime).toBe(0);
  });

  it("clears playback after natural completion, disappearance, failure, or unmount", async () => {
    const onError = vi.fn();
    const view = render(<PreviewHarness onError={onError} />);
    fireEvent.click(screen.getByRole("button", { name: "播放 a" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "停止 a" })).toBeInTheDocument());
    MockAudio.instances[0].onended?.();
    await waitFor(() => expect(screen.getByRole("button", { name: "播放 a" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "播放 b" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "停止 b" })).toBeInTheDocument());
    const second = MockAudio.instances[1];
    view.rerender(<PreviewHarness ids={["a"]} onError={onError} />);
    expect(second.pause).toHaveBeenCalledOnce();
    expect(second.currentTime).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: "播放 a" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "停止 a" })).toBeInTheDocument());
    MockAudio.instances[2].onerror?.();
    await waitFor(() => expect(onError).toHaveBeenCalledWith("音频试听失败，请检查素材文件。"));
    expect(screen.getByRole("button", { name: "播放 a" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "播放 a" }));
    const last = MockAudio.instances[3];
    view.unmount();
    expect(last.pause).toHaveBeenCalledOnce();
    expect(last.currentTime).toBe(0);
  });
});
