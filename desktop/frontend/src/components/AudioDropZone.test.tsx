import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AudioDropZone } from "./AudioDropZone";

afterEach(cleanup);

describe("AudioDropZone", () => {
  it("accepts one dragged audio file and exposes the active state", async () => {
    const onFile = vi.fn();
    const onError = vi.fn();
    const file = new File(["audio"], "参考 音频.mp3", { type: "audio/mpeg" });
    render(
      <AudioDropZone busy={false} className="drop-zone" onFile={onFile} onError={onError}>
        {(active) => <span>{active ? "松开以上传" : "上传参考音频"}</span>}
      </AudioDropZone>,
    );
    const zone = screen.getByRole("button", { name: "上传参考音频" });
    fireEvent.dragEnter(zone, { dataTransfer: { files: [file] } });
    expect(screen.getByText("松开以上传")).toBeInTheDocument();
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
    await waitFor(() => expect(onFile).toHaveBeenCalledWith(file));
    expect(onError).not.toHaveBeenCalled();
  });

  it("rejects empty and multi-file drops before upload", () => {
    const onFile = vi.fn();
    const onError = vi.fn();
    const empty = new File([], "empty.wav", { type: "audio/wav" });
    const second = new File(["audio"], "second.wav", { type: "audio/wav" });
    render(
      <AudioDropZone busy={false} className="drop-zone" onFile={onFile} onError={onError}>
        {() => <span>上传参考音频</span>}
      </AudioDropZone>,
    );
    const zone = screen.getByRole("button", { name: "上传参考音频" });
    fireEvent.drop(zone, { dataTransfer: { files: [empty] } });
    fireEvent.drop(zone, { dataTransfer: { files: [second, second] } });
    expect(onFile).not.toHaveBeenCalled();
    expect(onError).toHaveBeenNthCalledWith(1, "上传文件为空，请重新选择音频。");
    expect(onError).toHaveBeenNthCalledWith(2, "一次只能上传一个参考音频。");
  });
});
