from __future__ import annotations

import gc
import hashlib
import importlib.util
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from desktop.backend.paths import HF_HOME_DIR, HF_MODULES_DIR, MOSS_CODEC_DIR, MOSS_MODEL_DIR, RAW_OUTPUTS_DIR, VOICE_CACHE_DIR


os.environ.setdefault("HF_HOME", str(HF_HOME_DIR))
os.environ.setdefault("HF_MODULES_CACHE", str(HF_MODULES_DIR))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

ProgressCallback = Callable[[float, str], None]
CancelCallback = Callable[[], bool]


class TaskCancelled(RuntimeError):
    pass


PAUSE_MARKER_PATTERN = re.compile(r"\[pause\s+(\d+(?:\.\d+)?)s\]")


def _protect_pause_markers(text: str) -> tuple[str, dict[str, str]]:
    markers: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        for codepoint in range(0xE000, 0xF8FF + 1):
            token = chr(codepoint)
            if token not in text and token not in markers:
                markers[token] = match.group(0)
                return token
        raise ValueError("停顿标记数量过多，无法安全切分文本。")

    return PAUSE_MARKER_PATTERN.sub(replace, text), markers


def split_text(text: str, max_chars: int) -> list[str]:
    normalized = re.sub(r"\r\n?", "\n", (text or "").strip())
    if not normalized:
        return []
    normalized, pause_markers = _protect_pause_markers(normalized)
    limit = max(20, int(max_chars))
    units = re.split(r"(?<=[。！？!?；;：:\n])", normalized)
    result: list[str] = []
    current = ""
    for unit in (part.strip() for part in units if part.strip()):
        while len(unit) > limit:
            if current:
                result.append(current)
                current = ""
            cut = max(unit.rfind("，", 0, limit), unit.rfind(",", 0, limit))
            cut = limit if cut < limit // 2 else cut + 1
            result.append(unit[:cut].strip())
            unit = unit[cut:].strip()
        if not current:
            current = unit
        elif len(current) + len(unit) <= limit:
            current += unit
        else:
            result.append(current)
            current = unit
    if current:
        result.append(current)
    return ["".join(pause_markers.get(character, character) for character in segment) for segment in result]


class ModelEngine:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.processor: Any = None
        self.model: Any = None
        self.torch: Any = None
        self.sf: Any = None
        self.load_tensor_file: Any = None
        self.save_tensor_file: Any = None
        self.device: Any = None
        self.dtype: Any = None
        self.attention = "pending"
        self.state = "idle"
        self.message = "模型未加载"
        self.reference_memory_cache: dict[str, Any] = {}

    def installed(self) -> bool:
        return MOSS_MODEL_DIR.is_dir() and MOSS_CODEC_DIR.is_dir()

    def describe(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "active_model": "moss-tts-1.5" if self.model is not None else None,
            "message": self.message,
            "device": str(self.device) if self.device is not None else "待加载",
            "dtype": str(self.dtype).replace("torch.", "") if self.dtype is not None else "--",
            "attention": self.attention,
            "models": [{"key": "moss-tts-1.5", "name": "MOSS-TTS Local Transformer", "version": "1.5 · 4B", "installed": self.installed(), "enabled": self.installed()}],
        }

    def _import_runtime(self) -> None:
        if self.torch is not None:
            return
        import soundfile as sf
        import torch
        import torchaudio
        from safetensors.torch import load_file, save_file

        def soundfile_load(path: str | Path, *args: Any, **kwargs: Any):
            data, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
            return torch.from_numpy(data.T.copy()), int(sample_rate)

        torchaudio.load = soundfile_load
        self.torch = torch
        self.sf = sf
        self.load_tensor_file = load_file
        self.save_tensor_file = save_file
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if self.device.type == "cuda" and torch.cuda.get_device_capability()[0] >= 8 and torch.cuda.is_bf16_supported():
            self.dtype = torch.bfloat16
        elif self.device.type == "cuda":
            self.dtype = torch.float16
        else:
            self.dtype = torch.float32
        self.attention = self._attention_backend()

    def _attention_backend(self) -> str:
        if self.device.type != "cuda":
            return "eager"
        major, _ = self.torch.cuda.get_device_capability()
        return "flash_attention_2" if major >= 8 and importlib.util.find_spec("flash_attn") is not None else "sdpa"

    def load(self) -> str:
        with self.lock:
            if self.model is not None:
                return self.message
            if not self.installed():
                raise FileNotFoundError("MOSS-TTS 1.5 或 Audio Tokenizer v2 模型文件不完整。")
            self.state = "loading"
            self.message = "正在离线加载 MOSS-TTS 1.5 4B"
            self._import_runtime()
            from transformers import AutoModel, AutoProcessor
            from transformers.utils import logging as transformers_logging

            transformers_logging.set_verbosity_error()
            transformers_logging.disable_progress_bar()
            self.torch.backends.cuda.enable_cudnn_sdp(False)
            self.torch.backends.cuda.enable_flash_sdp(True)
            self.torch.backends.cuda.enable_mem_efficient_sdp(True)
            self.torch.backends.cuda.enable_math_sdp(True)
            self.processor = AutoProcessor.from_pretrained(
                str(MOSS_MODEL_DIR),
                trust_remote_code=True,
                codec_path=str(MOSS_CODEC_DIR),
                codec_weight_dtype="bf16",
                codec_compute_dtype="bf16",
                codec_attention_implementation=self.attention,
            )
            self.model = AutoModel.from_pretrained(
                str(MOSS_MODEL_DIR), trust_remote_code=True, attn_implementation=self.attention,
                torch_dtype=self.dtype, low_cpu_mem_usage=True, local_files_only=True,
            )
            self.model.eval()
            self.processor.audio_tokenizer.eval()
            self.state = "loaded"
            self.message = "MOSS-TTS 1.5 4B 已就绪"
            return self.message

    def release(self) -> None:
        with self.lock:
            self.state = "releasing"
            self.message = "正在释放模型与显存"
            model, processor = self.model, self.processor
            self.model = None
            self.processor = None
            self.reference_memory_cache.clear()
            for component in (model, getattr(processor, "audio_tokenizer", None)):
                try:
                    if component is not None:
                        component.to("cpu")
                except Exception:
                    pass
            del model, processor
            self._empty_cuda()
            self.state = "idle"
            self.message = "模型未加载"

    def _empty_cuda(self) -> None:
        gc.collect()
        if self.torch is not None and self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()
            self.torch.cuda.synchronize()

    def _activate_model(self) -> None:
        if self.device.type == "cuda":
            self.processor.audio_tokenizer.to("cpu")
            self._empty_cuda()
            self.model.to(self.device)
            self._empty_cuda()

    def _activate_codec(self) -> None:
        if self.device.type == "cuda":
            self.model.to("cpu")
            self._empty_cuda()
            self.processor.audio_tokenizer.to(self.device)
            self._empty_cuda()

    @staticmethod
    def _reference_key(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _encode_reference(self, path: Path):
        key = self._reference_key(path)
        if key in self.reference_memory_cache:
            return self.reference_memory_cache[key], True
        cache = VOICE_CACHE_DIR / f"{key}.safetensors"
        if cache.exists():
            codes = self.load_tensor_file(str(cache))["codes"].long().cpu()
            self.reference_memory_cache[key] = codes
            return codes, True
        codes = self.processor.encode_audios_from_path(str(path))[0].long().cpu().contiguous()
        self.save_tensor_file({"codes": codes}, str(cache))
        self.reference_memory_cache[key] = codes
        return codes, False

    @staticmethod
    def _outputs_to_cpu(outputs: Iterable[Any]) -> list[tuple[int, Any]]:
        return [(int(start), generation.detach().cpu()) for start, generation in outputs]

    def _join_audio(self, wavs: list[Any], sampling_rate: int, pause_ms: int):
        if not wavs:
            raise RuntimeError("模型没有返回有效音频。")
        normalized = []
        for wav in wavs:
            value = wav.detach().cpu().to(self.torch.float32)
            if value.ndim == 1:
                value = value.unsqueeze(0)
            if value.shape[0] == 1:
                value = value.repeat(2, 1)
            normalized.append(value[:2])
        silence = self.torch.zeros(2, max(0, int(sampling_rate * pause_ms / 1000)), dtype=self.torch.float32)
        pieces = []
        for index, wav in enumerate(normalized):
            if index and silence.shape[1]:
                pieces.append(silence)
            pieces.append(wav)
        return self.torch.cat(pieces, dim=1)

    def synthesize(self, payload: dict[str, Any], progress: ProgressCallback, should_cancel: CancelCallback) -> dict[str, Any]:
        parameters = payload["parameters"]
        segments = split_text(payload["text"], int(parameters["segment_chars"]))
        if not segments:
            raise ValueError("请输入需要合成的文本。")
        with self.lock:
            if should_cancel():
                raise TaskCancelled("任务已取消。")
            self.load()
            self.state = "running"
            self.message = "MOSS-TTS 正在生成音频"
            progress(.03, "准备模型")
            reference_codes = None
            reference_path = Path(payload["reference_path"]) if payload.get("reference_path") else None
            if reference_path:
                self._activate_codec()
                progress(.07, "编码参考音色")
                with self.torch.inference_mode():
                    reference_codes, cache_hit = self._encode_reference(reference_path)
                if cache_hit:
                    progress(.1, "已载入音色缓存")

            self._activate_model()
            generated_batches = []
            segment_target_tokens = payload.get("segment_target_tokens")
            if segment_target_tokens is not None and len(segment_target_tokens) != len(segments):
                raise ValueError("语速控制参数与文本切分数量不一致。")
            base_frame_budget = max(25, int(float(parameters["max_seconds"]) * 12.5))
            for index, segment in enumerate(segments):
                if should_cancel():
                    raise TaskCancelled("已在上一文本段结束后安全停止。")
                progress(.12 + .58 * index / max(1, len(segments)), f"生成第 {index + 1}/{len(segments)} 段")
                target_tokens = int(segment_target_tokens[index]) if segment_target_tokens is not None else None
                max_new_tokens = max(base_frame_budget, target_tokens + 32) if target_tokens is not None else base_frame_budget
                message = self.processor.build_user_message(
                    text=segment,
                    reference=[reference_codes] if reference_codes is not None else None,
                    language=payload.get("language") or None,
                    instruction=payload.get("instruction") or None,
                    tokens=int(target_tokens) if target_tokens is not None else None,
                )
                batch = self.processor([[message]], mode="generation")
                input_ids = batch["input_ids"].to(self.device)
                attention_mask = batch["attention_mask"].to(self.device)
                self.torch.manual_seed(int(parameters["seed"]) + index)
                if self.torch.cuda.is_available():
                    self.torch.cuda.manual_seed_all(int(parameters["seed"]) + index)
                with self.torch.inference_mode():
                    outputs = self.model.generate(
                        input_ids=input_ids, attention_mask=attention_mask, max_new_tokens=max_new_tokens,
                        do_sample=True, audio_temperature=float(parameters["temperature"]), audio_top_p=float(parameters["top_p"]),
                        audio_top_k=int(parameters["top_k"]), audio_repetition_penalty=float(parameters["repetition_penalty"]),
                    )
                generated_batches.append(self._outputs_to_cpu(outputs))
                del input_ids, attention_mask, outputs, batch

            if should_cancel():
                raise TaskCancelled("已在文本生成后安全停止。")
            self._activate_codec()
            decoded_wavs = []
            for index, outputs_cpu in enumerate(generated_batches):
                progress(.72 + .23 * index / max(1, len(generated_batches)), f"解码第 {index + 1}/{len(generated_batches)} 段")
                with self.torch.inference_mode():
                    messages = self.processor.decode(outputs_cpu, return_stereo=True)
                for decoded in messages:
                    if decoded is not None:
                        decoded_wavs.extend(wav for wav in decoded.audio_codes_list if isinstance(wav, self.torch.Tensor))
            sampling_rate = int(self.processor.model_config.sampling_rate)
            audio = self._join_audio(decoded_wavs, sampling_rate, int(parameters["pause_ms"]))
            target = RAW_OUTPUTS_DIR / f"moss_v15_{datetime.now():%Y%m%d_%H%M%S_%f}.wav"
            self.sf.write(str(target), audio.T.numpy(), sampling_rate, subtype="PCM_24")
            self.state = "loaded"
            self.message = "MOSS-TTS 1.5 4B 已就绪"
            progress(1.0, "生成完成")
            return {"source_path": str(target), "segments": len(segments), "duration": audio.shape[-1] / sampling_rate}


ENGINE = ModelEngine()
