import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { VoiceAsset, WorkspaceDraft } from "../../types";
import { VoicePanel } from "./VoicePanel";

const workspace: WorkspaceDraft = {
  text: "测试台词",
  language: "Chinese",
  style: "自然影视",
  instruction: "自然表达",
  manual_speed_enabled: false,
  manual_speed_level: "中等",
  preset: "标准",
  parameters: { temperature: 1.7, top_p: 0.8, top_k: 25, repetition_penalty: 1, max_seconds: 120, segment_chars: 400, pause_ms: 160, seed: 2026 },
  reference_id: null,
  voice_id: null,
  reference_trim_start: 0,
  reference_trim_end: null,
  output_profile: { format: "WAV", sample_rate: 48000, bit_depth: 24, channels: 2, loudness_lufs: -23 },
};

const voice: VoiceAsset = {
  id: "voice-1",
  name: "真人参考",
  saved: true,
  created_at: "2026-08-13T10:00:00",
  artifact_url: "/api/v2/artifacts/voice-1",
  health: { duration: 5, sample_rate: 48000, channels: 2, peak_dbfs: -1, rms_dbfs: -18, clipping_ratio: 0, snr_db: 24, silence_ratio: 4, score: 90, suitability: "适合克隆", findings: [], waveform: [0.2, 0.7, 0.4] },
};

afterEach(cleanup);

function renderPanel(current: WorkspaceDraft, voices: VoiceAsset[] = []) {
  const onWorkspace = vi.fn();
  const onMessage = vi.fn();
  const onOpenVoiceDesign = vi.fn();
  render(<VoicePanel voices={voices} workspace={current} onWorkspace={onWorkspace} onVoicesChanged={async () => undefined} onMessage={onMessage} onOpenVoiceDesign={onOpenVoiceDesign} />);
  return { onWorkspace, onMessage, onOpenVoiceDesign };
}

describe("VoicePanel reference-free mode", () => {
  it("shows the reference-free guidance and opens voice design without installing anything", () => {
    const { onOpenVoiceDesign } = renderPanel(workspace);
    expect(screen.getByRole("switch", { name: /当前为无参考模式/ })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("当前为无参考模式")).toBeInTheDocument();
    expect(screen.getByText(/正式配音制作建议使用真人参考音频/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "前往音色设计" }));
    expect(onOpenVoiceDesign).toHaveBeenCalledOnce();
  });

  it("clears the selected reference and trim when the enabled switch is turned off", () => {
    const selected = { ...workspace, voice_id: voice.id, reference_trim_start: 1.25, reference_trim_end: 4.5 };
    const { onWorkspace } = renderPanel(selected, [voice]);
    const toggle = screen.getByRole("switch", { name: /关闭参考音色/ });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByText("当前为无参考模式")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(onWorkspace).toHaveBeenCalledWith({ voice_id: null, reference_id: null, reference_trim_start: 0, reference_trim_end: null });
  });

  it("explains how to enable reference mode when no voice is selected", () => {
    const { onMessage } = renderPanel(workspace);
    fireEvent.click(screen.getByRole("switch", { name: /当前为无参考模式/ }));
    expect(onMessage).toHaveBeenCalledWith("请上传真人参考音频，或从音色库选择音色。", "success");
  });
});
