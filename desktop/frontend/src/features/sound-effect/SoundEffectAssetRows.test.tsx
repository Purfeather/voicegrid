import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OutputRecord } from "../../types";
import { MockAudio } from "../../test/mockAudio";
import { SoundEffectAssetRows } from "./SoundEffectAssetRows";

const makeOutput = (id: string, filename: string): OutputRecord => ({
  id, task_id: `task-${id}`, filename, created_at: "2026-08-13T10:00:00", duration: 5, sample_rate: 48000,
  channels: 1, bit_depth: 24, format: "WAV", voice: "", text: "", artifact_url: `/effects/${id}.wav`,
  module: "sound_effect", kind: "sound_effect_output",
});

beforeEach(() => MockAudio.install());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("SoundEffectAssetRows preview", () => {
  it("selects the asset without starting the current-output player and prevents overlap", async () => {
    const onSelect = vi.fn();
    render(<SoundEffectAssetRows outputs={[makeOutput("a", "雨声.wav"), makeOutput("b", "风声.wav")]} onSelect={onSelect} onFavorite={vi.fn()} onRename={vi.fn()} onDelete={vi.fn()} onMessage={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "试听 雨声.wav" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "停止试听 雨声.wav" })).toBeInTheDocument());
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "a" }));
    expect(MockAudio.instances).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "试听 风声.wav" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "停止试听 风声.wav" })).toBeInTheDocument());
    expect(MockAudio.instances[0].pause).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "停止试听 风声.wav" }));
    expect(MockAudio.instances[1].pause).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "试听 风声.wav" })).toBeInTheDocument();
  });

  it("stops a preview before deleting the active asset", async () => {
    const onDelete = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SoundEffectAssetRows outputs={[makeOutput("a", "雨声.wav")]} onSelect={vi.fn()} onFavorite={vi.fn()} onRename={vi.fn()} onDelete={onDelete} onMessage={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "试听 雨声.wav" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "停止试听 雨声.wav" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "删除音效" }));
    expect(MockAudio.instances[0].pause).toHaveBeenCalledOnce();
    expect(MockAudio.instances[0].currentTime).toBe(0);
    expect(onDelete).toHaveBeenCalledWith(expect.objectContaining({ id: "a" }));
  });
});
