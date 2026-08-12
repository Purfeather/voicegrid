import { AudioLines, MicVocal, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ModuleId } from "../../types";

export interface ModuleVisualDefinition {
  path: string;
  fallbackName: string;
  icon: LucideIcon;
}

export const MODULE_VISUALS: Record<ModuleId, ModuleVisualDefinition> = {
  speech: { path: "speech", fallbackName: "语音合成", icon: MicVocal },
  voice_design: { path: "voice-design", fallbackName: "音色设计", icon: Sparkles },
  sound_effect: { path: "sound-effect", fallbackName: "音效生成", icon: AudioLines },
};

export const MODULE_ORDER: ModuleId[] = ["speech", "voice_design", "sound_effect"];
