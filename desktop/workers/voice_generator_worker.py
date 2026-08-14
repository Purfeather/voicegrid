from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

try:
    from .audio_io import write_pcm24_wav
    from .cuda_policy import configure_sdpa, voice_generator_precision_policy
    from .sampling_precision import install_fp32_sampling
except ImportError:  # Direct execution by an isolated optional runtime.
    from audio_io import write_pcm24_wav
    from cuda_policy import configure_sdpa, voice_generator_precision_policy
    from sampling_precision import install_fp32_sampling


PROTOCOL_PREFIX = "VOICEGRID_EVENT "


def emit(event: str, **payload) -> None:
    message = {"event": event, **payload}
    sys.stdout.write(PROTOCOL_PREFIX + json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def native_bf16_available(capability: tuple[int, int], reported_support: bool) -> bool:
    """Reject software-emulated BF16 on pre-Ampere NVIDIA devices."""
    return int(capability[0]) >= 8 and bool(reported_support)


class VoiceGeneratorWorker:
    def __init__(self, model_path: Path, codec_path: Path) -> None:
        self.model_path = model_path
        self.codec_path = codec_path
        self.model = None
        self.processor = None
        self.torch = None
        self.device = "cuda"
        self.dtype_name = "float32"
        self.sampling_dtype_name = "float32"
        self.attention = "sdpa"
        self.attention_backend = "pending"
        self.compute_capability = ""
        self.precision_label = "pending"
        self.precision_report: dict = {}

    def load(self) -> None:
        if self.model is not None:
            return
        emit("progress", progress=0.03, message="正在载入音色设计运行组件")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
        import torch
        from transformers import AutoModel, AutoProcessor

        if not torch.cuda.is_available():
            raise RuntimeError("MOSS-VoiceGenerator 需要可用的 NVIDIA CUDA 显卡。")
        capability = tuple(int(value) for value in torch.cuda.get_device_capability())
        self.compute_capability = ".".join(str(value) for value in capability)
        attention_policy = configure_sdpa(torch, capability)
        self.attention_backend = attention_policy.label
        try:
            reported_bf16 = bool(torch.cuda.is_bf16_supported(including_emulation=False))
        except TypeError:
            reported_bf16 = bool(torch.cuda.is_bf16_supported())
        precision_policy = voice_generator_precision_policy(
            capability,
            native_bf16_available(capability, reported_bf16),
        )
        dtype = getattr(torch, precision_policy.model_dtype)
        self.dtype_name = precision_policy.model_dtype
        self.sampling_dtype_name = precision_policy.sampling_dtype
        self.precision_label = precision_policy.runtime_label
        self.precision_report = asdict(precision_policy)
        emit("progress", progress=0.12, message="正在载入 MOSS 音频分词器")
        processor_kwargs = {
            "trust_remote_code": True,
            "normalize_inputs": True,
            "codec_path": str(self.codec_path),
            "local_files_only": True,
        }
        try:
            processor = AutoProcessor.from_pretrained(str(self.model_path), **processor_kwargs)
        except TypeError:
            processor_kwargs.pop("local_files_only", None)
            processor = AutoProcessor.from_pretrained(str(self.model_path), **processor_kwargs)
        processor.audio_tokenizer.eval()
        processor.audio_tokenizer = processor.audio_tokenizer.to("cpu")
        emit("progress", progress=0.48, message="正在载入 MOSS-VoiceGenerator")
        try:
            model = AutoModel.from_pretrained(
                str(self.model_path),
                trust_remote_code=True,
                local_files_only=True,
                attn_implementation=self.attention,
                torch_dtype=dtype,
            ).to(self.device)
        except TypeError:
            model = AutoModel.from_pretrained(
                str(self.model_path),
                trust_remote_code=True,
                attn_implementation=self.attention,
                torch_dtype=dtype,
            ).to(self.device)
        model.eval()
        if not install_fp32_sampling(model):
            raise RuntimeError("无法安装稳定采样适配层。")
        floating_parameter_count = sum(
            int(parameter.numel())
            for parameter in model.parameters()
            if parameter.is_floating_point()
        )
        precision_extra_bytes = floating_parameter_count * 2 if dtype == torch.float32 else 0
        self.precision_report.update({
            "floating_parameter_count": floating_parameter_count,
            "estimated_extra_parameter_bytes": precision_extra_bytes,
        })
        self.torch = torch
        self.processor = processor
        self.model = model
        emit(
            "loaded",
            progress=0.72,
            message="MOSS-VoiceGenerator 已就绪",
            device=self.device,
            dtype=self.dtype_name,
            sampling_dtype=self.sampling_dtype_name,
            attention=self.attention_backend,
            compute_capability=self.compute_capability,
            precision=self.precision_label,
            projection_dtype=precision_policy.projection_dtype,
            precision_extra_mib=round(precision_extra_bytes / 1024 / 1024, 1),
        )

    def generate(self, command: dict) -> dict:
        self.load()
        assert self.model is not None and self.processor is not None and self.torch is not None
        text = str(command.get("text") or "").strip()
        instruction = str(command.get("instruction") or "").strip()
        if not text or not instruction:
            raise ValueError("试听台词和音色提示词不能为空。")
        parameters = dict(command.get("parameters") or {})
        seed = int(parameters.get("seed", 2026))
        self.torch.manual_seed(seed)
        self.torch.cuda.manual_seed_all(seed)
        self.torch.cuda.reset_peak_memory_stats()
        emit("progress", progress=0.76, message="正在构建音色设计指令")
        conversations = [[self.processor.build_user_message(text=text, instruction=instruction)]]
        batch = self.processor(conversations, mode="generation")
        input_ids = batch["input_ids"].to(self.device)
        attention_mask = batch["attention_mask"].to(self.device)
        self.processor.audio_tokenizer.to("cpu")
        self.model.to(self.device)
        gc.collect()
        self.torch.cuda.empty_cache()
        try:
            emit("progress", progress=0.80, message="正在生成试听音色")
            with self.torch.inference_mode():
                outputs = self.model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    audio_temperature=float(parameters.get("audio_temperature", 1.5)),
                    audio_top_p=float(parameters.get("audio_top_p", 0.6)),
                    audio_top_k=int(parameters.get("audio_top_k", 50)),
                    audio_repetition_penalty=float(parameters.get("audio_repetition_penalty", 1.1)),
                    max_new_tokens=int(parameters.get("max_new_tokens", 4096)),
                )
            outputs_cpu = [(int(start), generation.detach().cpu()) for start, generation in outputs]
            del outputs, input_ids, attention_mask, batch
            self.model.to("cpu")
            gc.collect()
            self.torch.cuda.empty_cache()
            self.processor.audio_tokenizer.to(self.device)
            emit("progress", progress=0.94, message="正在解码试听音色")
            with self.torch.inference_mode():
                decoded = self.processor.decode(outputs_cpu)
            if not decoded or decoded[0] is None or not decoded[0].audio_codes_list:
                raise RuntimeError("模型没有返回可解码的音频。")
            audio = decoded[0].audio_codes_list[0]
            if audio.ndim == 1:
                audio = audio.unsqueeze(0)
            output_path = Path(str(command["output_path"]))
            sample_rate = int(self.processor.model_config.sampling_rate)
            result = write_pcm24_wav(output_path, audio, sample_rate)
            result.update({
                "runtime_precision": self.precision_label,
                "precision_report": self.precision_report,
                "cuda_peak_allocated_mib": round(self.torch.cuda.max_memory_allocated() / 1024 / 1024, 1),
                "cuda_peak_reserved_mib": round(self.torch.cuda.max_memory_reserved() / 1024 / 1024, 1),
            })
            return result
        finally:
            self.model.to("cpu")
            self.processor.audio_tokenizer.to("cpu")
            gc.collect()
            self.torch.cuda.empty_cache()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--codec", required=True)
    args = parser.parse_args()
    worker = VoiceGeneratorWorker(Path(args.model), Path(args.codec))
    emit("ready", message="音色设计工作进程已启动")
    for line in sys.stdin:
        try:
            command = json.loads(line)
            request_id = str(command.get("request_id") or "")
            action = command.get("action")
            if action == "shutdown":
                emit("shutdown", request_id=request_id)
                return 0
            if action != "generate":
                raise ValueError("不支持的工作进程操作。")
            result = worker.generate(command)
            emit("result", request_id=request_id, result=result)
        except Exception as exc:
            emit("error", request_id=str(locals().get("request_id", "")), message=str(exc), traceback=traceback.format_exc())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
