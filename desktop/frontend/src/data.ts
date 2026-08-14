import type { SynthesisParameters } from "./types";

export const PARAMETER_PRESETS: Record<"标准" | "兼容", SynthesisParameters> = {
  标准: {
    temperature: 1.7,
    top_p: 0.8,
    top_k: 25,
    repetition_penalty: 1,
    max_seconds: 120,
    segment_chars: 400,
    pause_ms: 160,
    seed: 2026,
  },
  兼容: {
    temperature: 1.7,
    top_p: 0.8,
    top_k: 25,
    repetition_penalty: 1,
    max_seconds: 20,
    segment_chars: 90,
    pause_ms: 180,
    seed: 2026,
  },
};

export const PARAMETER_HELP: Record<keyof SynthesisParameters, string> = {
  temperature: "控制声音变化幅度。较高更活泼，过高可能不稳定。",
  top_p: "只从累计概率范围内采样，越低越保守。",
  top_k: "每一步保留的候选数量，增大可增加变化但不保证更自然。",
  repetition_penalty: "抑制重复发音和异常循环，通常保持 1.0。",
  max_seconds: "单段允许生成的最长音频时间。",
  segment_chars: "每段最大字符数。标准预设已在 16GB 显存上验证 400 字。",
  pause_ms: "自动切分后，相邻音频段之间插入的静音。",
  seed: "随机种子；相同输入与参数更容易复现相近结果。",
};

export const SAMPLE_TEXT = "你好，欢迎使用声格 VoiceGrid。\n这里是以 MOSS-TTS 1.5 4B 为核心的本地配音工作站。你可以管理音色、设计情绪、预览切分并生成可直接交付的音频。";
