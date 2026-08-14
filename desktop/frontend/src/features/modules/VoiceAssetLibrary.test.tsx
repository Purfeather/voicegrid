import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { VoiceAsset } from "../../types";
import { MockAudio } from "../../test/mockAudio";
import { VoiceAssetLibrary } from "./VoiceAssetLibrary";

const makeVoice = (id: string, name: string): VoiceAsset => ({
  id, name, saved: true, created_at: "2026-08-13T10:00:00", artifact_url: `/voices/${id}.wav`,
  health: { duration: 5, sample_rate: 48000, channels: 1, peak_dbfs: -1, rms_dbfs: -18, clipping_ratio: 0, snr_db: 24, silence_ratio: 4, score: 90, suitability: "适合克隆", findings: [], waveform: [] },
});

beforeEach(() => MockAudio.install());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("VoiceAssetLibrary preview", () => {
  it("uses one stoppable preview for the shared speech and voice-design library", async () => {
    render(<VoiceAssetLibrary voices={[makeVoice("a", "旁白"), makeVoice("b", "角色")]} onChanged={async () => undefined} onMessage={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "试听 旁白" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "停止试听 旁白" })).toHaveAttribute("aria-pressed", "true"));
    fireEvent.click(screen.getByRole("button", { name: "试听 角色" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "停止试听 角色" })).toBeInTheDocument());
    expect(MockAudio.instances[0].pause).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "停止试听 角色" }));
    expect(screen.getByRole("button", { name: "试听 角色" })).toHaveAttribute("aria-pressed", "false");
    expect(MockAudio.instances[1].pause).toHaveBeenCalledOnce();
  });
});
