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
    channels: Literal[1, 2] = 1
    loudness_lufs: float | None = Field(default=-23.0, ge=-40, le=-6)
    filename_template: str = Field(default="{project}_{voice}_{index}_{date}", min_length=1, max_length=160)
    output_directory: str = ""


class WorkspaceDraft(BaseModel):
    text: str = ""
    language: str = "Chinese"
    style: str = "自然影视"
    instruction: str = Field(default="", max_length=2000)
    natural_speed: float = Field(default=1.0, ge=0.7, le=1.35)
    preset: Literal["标准", "兼容"] = "标准"
    parameters: SynthesisParameters = Field(default_factory=SynthesisParameters)
    reference_id: str | None = None
    voice_id: str | None = None
    reference_trim_start: float = Field(default=0.0, ge=0)
    reference_trim_end: float | None = Field(default=None, gt=0)
    output_profile: OutputProfile = Field(default_factory=OutputProfile)

    @model_validator(mode="after")
    def validate_reference(self):
        if self.reference_id and self.voice_id:
            raise ValueError("临时参考音频和音色库资产不能同时启用。")
        if self.reference_trim_end is not None and self.reference_trim_end <= self.reference_trim_start:
            raise ValueError("裁剪终点必须晚于起点。")
        return self


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    language: str = "Chinese"


class ProjectPatch(BaseModel):
    revision: int = Field(default=0, ge=0)
    workspace: WorkspaceDraft


class VoicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    saved: bool | None = None
    role: str | None = Field(default=None, max_length=80)
    language_accent: str | None = Field(default=None, max_length=120)
    gender_age: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)


class StyleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    instruction: str = Field(min_length=1, max_length=2000)


class TaskCreate(BaseModel):
    project_id: str
    workspace: WorkspaceDraft
