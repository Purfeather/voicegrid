import { AudioLines, MicVocal, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ModuleId } from "../../types";

export interface ModuleVisualDefinition {
  path: string;
  fallbackName: string;
  icon: LucideIcon;
  outputKind: "speech_output" | "voice_design_output" | "sound_effect_output";
  assetLabel: string;
  emptyOutputTitle: string;
  emptyActivityTitle: string;
  installEyebrow: string;
}

export const MODULE_VISUALS: Record<ModuleId, ModuleVisualDefinition> = {
  speech: { path: "speech", fallbackName: "语音合成", icon: MicVocal, outputKind: "speech_output", assetLabel: "配音", emptyOutputTitle: "尚未生成音频", emptyActivityTitle: "暂无任务与输出", installEyebrow: "MODULE STATUS" },
  voice_design: { path: "voice-design", fallbackName: "音色设计", icon: Sparkles, outputKind: "voice_design_output", assetLabel: "试听音色", emptyOutputTitle: "还没有试听结果", emptyActivityTitle: "暂无设计历史", installEyebrow: "MODULE STATUS" },
  sound_effect: { path: "sound-effect", fallbackName: "音效生成", icon: AudioLines, outputKind: "sound_effect_output", assetLabel: "音效", emptyOutputTitle: "还没有音效输出", emptyActivityTitle: "暂无任务与输出", installEyebrow: "MODULE STATUS" },
};

export const MODULE_ORDER: ModuleId[] = ["speech", "voice_design", "sound_effect"];
