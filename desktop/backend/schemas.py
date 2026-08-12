from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SynthesisParameters(BaseModel):
    temperature: float = Field(default=1.7, ge=0.1, le=3.0)
    top_p: float = Field(default=0.8, ge=0.1, le=1.0)
    top_k: int = Field(default=25, ge=1, le=200)
    repetition_penalty: float = Field(default=1.0, ge=0.5, le=2.0)
    max_seconds: int = Field(default=120, ge=5, le=300)
    segment_chars: int = Field(default=400, ge=20, le=1000)
    pause_ms: int = Field(default=160, ge=0, le=2000)
    seed: int = Field(default=2026, ge=0, le=2_147_483_647)


class OutputProfile(BaseModel):
    format: Literal["WAV", "FLAC"] = "WAV"
    sample_rate: Literal[24000, 44100, 48000] = 48000
    bit_depth: Literal[16, 24, 32] = 24
    channels: Literal[1, 2] = 2
    loudness_lufs: float | None = Field(default=-23.0, ge=-40, le=-6)


class WorkspaceDraft(BaseModel):
    text: str = ""
    language: str = "Chinese"
    style: str = "自然影视"
    instruction: str = Field(default="", max_length=2000)
    manual_speed_enabled: bool = False
    manual_speed_level: Literal["慢", "较慢", "中等", "较快", "快"] = "中等"
    preset: Literal["标准", "兼容"] = "标准"
    parameters: SynthesisParameters = Field(default_factory=SynthesisParameters)
    reference_id: str | None = None
    voice_id: str | None = None
    reference_trim_start: float = Field(default=0.0, ge=0)
    reference_trim_end: float | None = Field(default=None, gt=0)
    output_profile: OutputProfile = Field(default_factory=OutputProfile)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_speed(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            value.pop("natural_speed", None)
            value.pop("target_duration_enabled", None)
            value.pop("target_duration_seconds", None)
            value.setdefault("manual_speed_enabled", False)
            value.setdefault("manual_speed_level", "中等")
        return value

    @model_validator(mode="after")
    def validate_reference(self):
        if self.reference_id and self.voice_id:
            raise ValueError("临时参考音频和音色库资产不能同时启用。")
        if self.reference_trim_end is not None and self.reference_trim_end <= self.reference_trim_start:
            raise ValueError("裁剪终点必须晚于起点。")
        return self


ModuleId = Literal["speech", "voice_design", "sound_effect"]


class VoicePromptComposer(BaseModel):
    role: str = "纪录片旁白"
    age_gender: str = "成熟中性"
    texture: str = "清晰温润"
    pitch_strength: str = "中低音，力度克制"
    pace_rhythm: str = "自然语速，节奏从容"
    accent_language: str = "标准普通话"
    emotion: str = "沉稳可信"
    performance: str = "情绪保持稳定，句尾自然收束"


class VoiceDesignParameters(BaseModel):
    audio_temperature: float = Field(default=1.5, ge=0.1, le=3.0)
    audio_top_p: float = Field(default=0.6, ge=0.1, le=1.0)
    audio_top_k: int = Field(default=50, ge=1, le=200)
    audio_repetition_penalty: float = Field(default=1.1, ge=0.5, le=2.0)
    max_new_tokens: int = Field(default=4096, ge=256, le=8192)
    seed: int = Field(default=2026, ge=0, le=2_147_483_647)


class VoiceDesignDraft(BaseModel):
    mode: Literal["composer", "freeform"] = "composer"
    text: str = "你好，很高兴与你见面。这是一段用于确认新音色气质与表现力的试听台词。"
    composer: VoicePromptComposer = Field(default_factory=VoicePromptComposer)
    prompt_preview: str = ""
    instruction: str = "成熟中性的纪录片旁白，声音清晰温润，中低音且力度克制，自然语速、节奏从容，使用标准普通话，整体沉稳可信，情绪保持稳定并在句尾自然收束。"
    parameters: VoiceDesignParameters = Field(default_factory=VoiceDesignParameters)


class SoundEffectParameters(BaseModel):
    seconds: int = Field(default=10, ge=1, le=30)
    num_inference_steps: int = Field(default=100, ge=10, le=150)
    cfg_scale: float = Field(default=4.0, ge=1.0, le=8.0)
    sigma_shift: float = Field(default=5.0, ge=0.0, le=10.0)
    seed: int = Field(default=2026, ge=0, le=2_147_483_647)


class SoundEffectDraft(BaseModel):
    prompt: str = "雨夜城市街道，远处车辆驶过湿润路面，近处有细密雨滴落在金属棚顶。"
    parameters: SoundEffectParameters = Field(default_factory=SoundEffectParameters)


class ProjectWorkspaces(BaseModel):
    speech: WorkspaceDraft = Field(default_factory=WorkspaceDraft)
    voice_design: VoiceDesignDraft = Field(default_factory=VoiceDesignDraft)
    sound_effect: SoundEffectDraft = Field(default_factory=SoundEffectDraft)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    language: str = "Chinese"


class ProjectPatch(BaseModel):
    revision: int = Field(default=0, ge=0)
    module: ModuleId = "speech"
    workspace: WorkspaceDraft | VoiceDesignDraft | SoundEffectDraft

    @model_validator(mode="before")
    @classmethod
    def parse_workspace_for_module(cls, value):
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        module = payload.get("module", "speech")
        expected = {
            "speech": WorkspaceDraft,
            "voice_design": VoiceDesignDraft,
            "sound_effect": SoundEffectDraft,
        }.get(module)
        if expected is not None:
            payload["workspace"] = expected.model_validate(payload.get("workspace") or {})
        return payload

    @model_validator(mode="after")
    def validate_module_workspace(self):
        expected = {
            "speech": WorkspaceDraft,
            "voice_design": VoiceDesignDraft,
            "sound_effect": SoundEffectDraft,
        }[self.module]
        if not isinstance(self.workspace, expected):
            raise ValueError("工作区内容与模块不匹配。")
        return self


class VoicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    saved: bool | None = None
    role: str | None = Field(default=None, max_length=80)
    language_accent: str | None = Field(default=None, max_length=120)
    gender_age: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)


class SaveDesignedVoice(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SoundEffectOutputPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    favorite: bool | None = None


class StyleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    instruction: str = Field(min_length=1, max_length=2000)


class ModuleTaskCreate(BaseModel):
    project_id: str
    module: ModuleId
    workspace: WorkspaceDraft | VoiceDesignDraft | SoundEffectDraft

    @model_validator(mode="before")
    @classmethod
    def parse_workspace_for_module(cls, value):
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        expected = {
            "speech": WorkspaceDraft,
            "voice_design": VoiceDesignDraft,
            "sound_effect": SoundEffectDraft,
        }.get(payload.get("module"))
        if expected is not None:
            payload["workspace"] = expected.model_validate(payload.get("workspace") or {})
        return payload

    @model_validator(mode="after")
    def validate_module_workspace(self):
        expected = {
            "speech": WorkspaceDraft,
            "voice_design": VoiceDesignDraft,
            "sound_effect": SoundEffectDraft,
        }[self.module]
        if not isinstance(self.workspace, expected):
            raise ValueError("任务内容与模块不匹配。")
        return self


class ModuleInstallRequest(BaseModel):
    confirm: bool = False
