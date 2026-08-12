from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


WELCOME_TEXT = """你好，欢迎使用龙融影业AI配音台。
这里是以 MOSS-TTS 1.5 4B 为核心的本地配音工作站。你可以管理音色、设计情绪、预览切分并生成可直接交付的音频。"""

LANGUAGES = [
    {"value": "Chinese", "label": "中文"},
    {"value": "English", "label": "English"},
    {"value": "Japanese", "label": "日本語"},
    {"value": "Korean", "label": "한국어"},
]

PARAMETER_PRESETS: dict[str, dict[str, Any]] = {
    "标准": {
        "temperature": 1.7,
        "top_p": 0.8,
        "top_k": 25,
        "repetition_penalty": 1.0,
        "max_seconds": 120,
        "segment_chars": 400,
        "pause_ms": 160,
        "seed": 2026,
    },
    "兼容": {
        "temperature": 1.7,
        "top_p": 0.8,
        "top_k": 25,
        "repetition_penalty": 1.0,
        "max_seconds": 20,
        "segment_chars": 90,
        "pause_ms": 180,
        "seed": 2026,
    },
}

BUILT_IN_STYLES = [
    ("自然影视", "自然、清晰、真实，情绪随语义自然变化；语速适中，停连流畅，保持影视对白般的生活感，避免播音腔和过度表演。"),
    ("纪录片旁白", "沉稳、克制、可信，声音有厚度和空间感；语速略慢，吐字清楚，句尾收束，重点信息适度加强，保留充足停顿。"),
    ("商业广告", "明亮、自信、富有感染力，语速稍快，节奏鲜明；关键词有明确重音，情绪积极饱满，结尾干净有推动力。"),
    ("温柔治愈", "温暖、柔和、亲近，像贴近听众轻声讲述；语速舒缓，气息自然，带轻微笑意，情绪细腻但不过分煽情。"),
    ("新闻播报", "客观、准确、沉着，语速均匀，咬字清晰；信息层次分明，重音克制，保持专业权威，不加入明显个人情绪。"),
    ("冷峻悬疑", "低沉、冷静、克制，语速偏慢；停顿带有悬念，句子收尾利落，保持紧张压迫感和疏离感，避免夸张惊悚腔。"),
    ("轻松喜剧", "轻快、灵动、自然幽默，语速稍快；节奏富于变化，转折和包袱前后停顿明确，带松弛感和适度俏皮。"),
    ("热血激昂", "坚定、昂扬、充满力量，情绪逐步推进；节奏有冲击力，重音明确，高潮具有爆发感，但避免持续喊叫和声音失真。"),
]


def default_workspace(language: str, output_directory: Path) -> dict[str, Any]:
    return {
        "text": WELCOME_TEXT,
        "language": language,
        "style": "自然影视",
        "instruction": BUILT_IN_STYLES[0][1],
        "natural_speed": 1.0,
        "preset": "标准",
        "parameters": deepcopy(PARAMETER_PRESETS["标准"]),
        "reference_id": None,
        "voice_id": None,
        "reference_trim_start": 0.0,
        "reference_trim_end": None,
        "output_profile": {
            "format": "WAV",
            "sample_rate": 48000,
            "bit_depth": 24,
            "channels": 1,
            "loudness_lufs": -23.0,
            "filename_template": "{project}_{voice}_{index}_{date}",
            "output_directory": str(output_directory.resolve()),
        },
    }
