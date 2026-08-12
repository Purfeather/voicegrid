from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Iterable, Iterator

try:
    from .audio_io import write_pcm24_wav
except ImportError:  # Direct execution by an isolated optional runtime.
    from audio_io import write_pcm24_wav


PROTOCOL_PREFIX = "VOICEGRID_EVENT "
SAMPLE_RATE = 48_000
CHANNELS = 1
BIT_DEPTH = 24
UPSTREAM_REVISION = "58b20a0d5fcc6766658d50967a90a9d890009a46"
RUNTIME_PRECISION = "float16"

os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
os.environ.setdefault("TORCH_COMPILE_DISABLE", "1")
os.environ.setdefault("TORCHINDUCTOR_DISABLE", "1")
os.environ.setdefault("DISABLE_TORCH_COMPILE", "1")
os.environ.setdefault("TRITON_DISABLE", "1")


def emit(event: str, **payload: Any) -> None:
    message = {"event": event, **payload}
    sys.stdout.write(PROTOCOL_PREFIX + json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def validate_request(command: dict[str, Any]) -> dict[str, Any]:
    prompt = str(command.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("音效提示词不能为空。")
    seconds = float(command.get("seconds", 10))
    steps = int(command.get("num_inference_steps", 100))
    cfg_scale = float(command.get("cfg_scale", 4.0))
    sigma_shift = float(command.get("sigma_shift", 5.0))
    seed = int(command.get("seed", 2026))
    output_path_value = str(command.get("output_path") or "").strip()
    output_path = Path(output_path_value)
    if not 1.0 <= seconds <= 30.0:
        raise ValueError("音效时长必须在 1 到 30 秒之间。")
    if not 10 <= steps <= 150:
        raise ValueError("推理步数必须在 10 到 150 之间。")
    if not 1.0 <= cfg_scale <= 8.0:
        raise ValueError("CFG 必须在 1 到 8 之间。")
    if not 0.0 <= sigma_shift <= 10.0:
        raise ValueError("Sigma Shift 必须在 0 到 10 之间。")
    if not output_path_value:
        raise ValueError("音效输出路径不能为空。")
    return {
        "prompt": prompt,
        "seconds": seconds,
        "num_inference_steps": steps,
        "cfg_scale": cfg_scale,
        "sigma_shift": sigma_shift,
        "seed": seed,
        "output_path": output_path,
    }


def prepare_audio(audio: Any, expected_seconds: float, sample_rate: int = SAMPLE_RATE) -> Any:
    import numpy as np

    samples = audio.detach().cpu().float().numpy() if hasattr(audio, "detach") else np.asarray(audio, dtype=np.float32)
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim == 3:
        if samples.shape[0] != 1:
            raise RuntimeError("音效工作进程只支持单样本输出。")
        samples = samples[0]
    if samples.ndim == 1:
        samples = samples[np.newaxis, :]
    if samples.ndim != 2 or samples.shape[0] != CHANNELS or samples.shape[1] < 1:
        raise RuntimeError("音效输出必须是非空单声道音频。")
    if sample_rate != SAMPLE_RATE:
        raise RuntimeError(f"音效模型返回了错误采样率：{sample_rate} Hz。")
    if not np.isfinite(samples).all():
        raise RuntimeError("音效输出包含 NaN 或无穷值。")
    expected_frames = int(round(expected_seconds * SAMPLE_RATE))
    actual_frames = int(samples.shape[1])
    tolerance_frames = int(SAMPLE_RATE * 0.02)
    if abs(actual_frames - expected_frames) > tolerance_frames:
        raise RuntimeError(
            f"音效时长不符合请求：期望 {expected_seconds:.3f} 秒，实际 {actual_frames / SAMPLE_RATE:.3f} 秒。"
        )
    return samples[:, :expected_frames]


def write_validated_audio(output_path: Path, audio: Any, expected_seconds: float) -> dict[str, Any]:
    import numpy as np
    import soundfile as sf

    samples = prepare_audio(audio, expected_seconds, SAMPLE_RATE)
    temporary = output_path.with_name(f".{output_path.name}.worker-partial.wav")
    temporary.unlink(missing_ok=True)
    try:
        metadata = write_pcm24_wav(temporary, samples, SAMPLE_RATE)
        decoded, decoded_rate = sf.read(temporary, dtype="float32", always_2d=True)
        info = sf.info(temporary)
        if decoded_rate != SAMPLE_RATE or info.samplerate != SAMPLE_RATE:
            raise RuntimeError("写入后的音效 WAV 不是 48 kHz。")
        if info.channels != CHANNELS or decoded.shape != (int(info.frames), CHANNELS):
            raise RuntimeError("写入后的音效 WAV 声道或帧数无效。")
        if info.subtype != "PCM_24":
            raise RuntimeError(f"写入后的音效 WAV 位深无效：{info.subtype}。")
        if decoded.size == 0 or not np.isfinite(decoded).all():
            raise RuntimeError("写入后的音效 WAV 为空或包含无效数值。")
        if abs(float(info.frames / info.samplerate) - expected_seconds) > 0.02:
            raise RuntimeError("写入后的音效 WAV 时长校验失败。")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, output_path)
        return {
            "duration": float(info.frames / info.samplerate),
            "sample_rate": int(info.samplerate),
            "channels": int(info.channels),
            "bit_depth": BIT_DEPTH,
        }
    finally:
        temporary.unlink(missing_ok=True)


class ProtocolProgress:
    def __init__(self, request_id: str, start: float = 0.38, end: float = 0.88) -> None:
        self.request_id = request_id
        self.start = start
        self.end = end

    def __call__(self, iterable: Iterable[Any], **_: Any) -> Iterator[Any]:
        items = list(iterable)
        total = max(1, len(items))
        for index, item in enumerate(items, start=1):
            emit(
                "progress",
                request_id=self.request_id,
                progress=self.start + (self.end - self.start) * index / total,
                message=f"正在生成音效 · {index}/{total}",
            )
            yield item


class SoundEffectWorker:
    def __init__(self, model_path: Path) -> None:
        self.model_path = model_path
        self.pipeline = None
        self.torch = None
        self.device = "cuda"
        self.precision = RUNTIME_PRECISION
        self.low_vram = True
        self.compute_capability = ""

    @staticmethod
    def _disable_compilation(torch_module: Any) -> None:
        os.environ["TORCHDYNAMO_DISABLE"] = "1"
        os.environ["TORCH_COMPILE_DISABLE"] = "1"
        os.environ["DISABLE_TORCH_COMPILE"] = "1"
        compiler = getattr(torch_module, "compiler", None)
        if compiler is not None and hasattr(compiler, "cudagraph_mark_step_begin"):
            compiler.cudagraph_mark_step_begin = lambda: None

    def _offload_all(self) -> None:
        if self.pipeline is None or self.torch is None:
            return
        engine = self.pipeline.engine
        engine.vram_management_enabled = True
        engine.load_models_to_device([])
        gc.collect()
        self.torch.cuda.empty_cache()

    def load(self) -> None:
        if self.pipeline is not None:
            return
        emit("progress", progress=0.03, message="正在载入音效运行组件")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        import torch
        from moss_soundeffect_v2 import MossSoundEffectPipeline

        if not torch.cuda.is_available():
            raise RuntimeError("MOSS-SoundEffect v2.0 需要可用的 NVIDIA CUDA 显卡。")
        capability = tuple(int(value) for value in torch.cuda.get_device_capability())
        self.compute_capability = ".".join(str(value) for value in capability)
        self._disable_compilation(torch)
        emit("progress", progress=0.10, message="正在 CPU 中载入 MOSS-SoundEffect v2.0")
        pipeline = MossSoundEffectPipeline.from_pretrained(
            str(self.model_path),
            torch_dtype=torch.float16,
            device="cpu",
            local_files_only=True,
        )
        engine = pipeline.engine
        engine.device = torch.device(self.device)
        engine.torch_dtype = torch.float16
        engine.vram_management_enabled = True
        for name in ("text_encoder", "dit"):
            model = getattr(engine, name, None)
            if model is not None:
                model.eval()
                model.to(device="cpu", dtype=torch.float16)
        if engine.vae is not None:
            engine.vae.eval()
            engine.vae.to(device="cpu", dtype=torch.float32)
        self.pipeline = pipeline
        self.torch = torch
        self._offload_all()
        emit(
            "loaded",
            progress=0.28,
            message="MOSS-SoundEffect v2.0 已就绪（低显存模式）",
            device=self.device,
            dtype=RUNTIME_PRECISION,
            precision=RUNTIME_PRECISION,
            compute_capability=self.compute_capability,
            low_vram=True,
        )

    def generate(self, command: dict[str, Any], request_id: str) -> dict[str, Any]:
        request = validate_request(command)
        self.load()
        assert self.pipeline is not None and self.torch is not None
        torch = self.torch
        pipeline = self.pipeline
        engine = pipeline.engine
        torch.cuda.reset_peak_memory_stats()
        prompt = f"{request['prompt']} duration: {request['seconds']:.1f}s"
        full_seconds = int(getattr(pipeline, "max_inference_seconds", 30))
        if full_seconds != 30 or int(getattr(pipeline, "sample_rate", SAMPLE_RATE)) != SAMPLE_RATE:
            raise RuntimeError("音效模型配置不是预期的 48 kHz / 30 秒版本。")
        emit("progress", request_id=request_id, progress=0.31, message="正在编码音效提示词")
        try:
            with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
                audio = engine(
                    prompt=prompt,
                    negative_prompt="",
                    seed=request["seed"],
                    cfg_scale=request["cfg_scale"],
                    sigma_shift=request["sigma_shift"],
                    num_inference_steps=request["num_inference_steps"],
                    num_samples=SAMPLE_RATE * full_seconds,
                    num_channels=CHANNELS,
                    progress_bar_cmd=ProtocolProgress(request_id),
                )
            requested_frames = int(round(request["seconds"] * SAMPLE_RATE))
            audio = audio[:, :, :requested_frames]
            emit("progress", request_id=request_id, progress=0.94, message="正在验证并写入 48 kHz 音效")
            metadata = write_validated_audio(request["output_path"], audio, request["seconds"])
            return {
                **metadata,
                "runtime_precision": RUNTIME_PRECISION,
                "low_vram": True,
                "cuda_peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 1024 / 1024, 1),
                "cuda_peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 1024 / 1024, 1),
            }
        finally:
            self._offload_all()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    worker = SoundEffectWorker(Path(args.model))
    emit("ready", message="音效生成工作进程已启动")
    for line in sys.stdin:
        request_id = ""
        try:
            command = json.loads(line)
            request_id = str(command.get("request_id") or "")
            action = command.get("action")
            if action == "shutdown":
                emit("shutdown", request_id=request_id)
                return 0
            if action != "generate":
                raise ValueError("不支持的工作进程操作。")
            result = worker.generate(command, request_id)
            emit("result", request_id=request_id, result=result)
        except Exception as exc:
            emit("error", request_id=request_id, message=str(exc), traceback=traceback.format_exc())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
