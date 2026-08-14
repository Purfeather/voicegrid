from __future__ import annotations

from fastapi import APIRouter, File, UploadFile
from ..events import EVENTS
from ..repositories.assets import add_upload, delete_sound_effect_output, delete_style, delete_voice, list_styles, list_voices, save_output_as_voice, save_style, update_sound_effect_output, update_voice
from ..schemas import SaveDesignedVoice, SoundEffectOutputPatch, StyleCreate, VoicePatch
from .errors import translate_error

router = APIRouter(prefix="/api/v2", tags=["assets"])

@router.get("/voices")
def voices(): return list_voices()

@router.post("/voices/uploads")
async def voice_upload(file: UploadFile = File(...)):
    try:
        content = await file.read()
        if len(content) > 256 * 1024 * 1024: raise ValueError("参考音频不能超过 256MB。")
        return add_upload(file.filename or "reference.wav", content)
    except Exception as exc: raise translate_error(exc) from exc

@router.patch("/voices/{asset_id}")
def voice_update(asset_id: str, request: VoicePatch):
    try: return update_voice(asset_id, request)
    except Exception as exc: raise translate_error(exc) from exc

@router.delete("/voices/{asset_id}", status_code=204)
def voice_remove(asset_id: str, delete_file: bool = True):
    try: delete_voice(asset_id, delete_file)
    except Exception as exc: raise translate_error(exc) from exc

@router.get("/styles")
def styles(): return list_styles()

@router.post("/styles")
def style_create(request: StyleCreate):
    try: return save_style(request.name, request.instruction)
    except Exception as exc: raise translate_error(exc) from exc

@router.delete("/styles/{name}", status_code=204)
def style_remove(name: str):
    try: delete_style(name)
    except Exception as exc: raise translate_error(exc) from exc

@router.post("/voice-design/outputs/{output_id}/save-as-voice")
def voice_design_save(output_id: str, request: SaveDesignedVoice):
    try:
        voice = save_output_as_voice(output_id, request.name); EVENTS.publish("voice.updated", voice); return voice
    except Exception as exc: raise translate_error(exc) from exc

@router.patch("/sound-effects/outputs/{output_id}")
def sound_effect_output_update(output_id: str, request: SoundEffectOutputPatch):
    try:
        output = update_sound_effect_output(output_id, request); EVENTS.publish("project.saved", {"id": output["project_id"], "module": "sound_effect"}); return output
    except Exception as exc: raise translate_error(exc) from exc

@router.delete("/sound-effects/outputs/{output_id}", status_code=204)
def sound_effect_output_remove(output_id: str, delete_file: bool = True):
    try:
        project_id = delete_sound_effect_output(output_id, delete_file); EVENTS.publish("project.saved", {"id": project_id, "module": "sound_effect"})
    except Exception as exc: raise translate_error(exc) from exc
