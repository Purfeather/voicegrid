from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import soundfile as sf

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.model_engine import ENGINE
from desktop.backend.defaults import BUILT_IN_STYLES, PARAMETER_PRESETS
from desktop.backend.paths import ROOT
from desktop.backend.task_service import duration_to_tokens


CALIBRATION_SENTENCES = (
    "清晨的第一束光落在窗边，城市慢慢恢复了声音。",
    "我们把每一次呼吸、每一个停顿和每一处情绪变化都认真记录。",
    "声音不只是传递文字，也应该保留真实自然的温度。",
    "清楚的语句与恰当的节奏，会让听众更容易进入故事。",
    "平静的叙述并不意味着平淡，细微变化同样能够带来力量。",
    "当画面向前推进，声音会沿着人物的感受缓慢展开。",
    "重要的信息需要准确表达，也需要为思考留出一点空间。",
    "自然的停连让句子彼此衔接，形成稳定而舒适的听觉节奏。",
    "我们关注音色的质感，也关注每个词语落下时的轻重。",
    "好的配音会贴合内容，不抢夺画面，却能让情绪更加完整。",
    "从一句简短问候到一段漫长独白，声音始终服务于表达。",
    "这段测试素材将帮助工作站找到更准确、更可靠的时长控制。",
)


def calibration_text(seconds: int) -> str:
    target_chars = max(18, round(seconds * 4.2))
    text = ""
    index = 0
    while len(text) < target_chars:
        text += CALIBRATION_SENTENCES[index % len(CALIBRATION_SENTENCES)]
        index += 1
    if len(text) > target_chars:
        text = text[:target_chars - 1].rstrip("，。！？；：") + "。"
    return text


def parse_values(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def run_sample(output_dir: Path, seconds: int, seed: int, reference: Path) -> dict[str, Any]:
    parameters = dict(PARAMETER_PRESETS["标准"])
    parameters["seed"] = seed
    tokens = duration_to_tokens(seconds)
    text = calibration_text(seconds)
    progress_state = {"message": ""}

    def progress(value: float, message: str) -> None:
        if message != progress_state["message"]:
            print(f"[{seconds:>3}s / seed {seed}] {value:>5.1%} {message}", flush=True)
            progress_state["message"] = message

    result = ENGINE.synthesize(
        {
            "text": text,
            "language": "Chinese",
            "instruction": BUILT_IN_STYLES[0][1],
            "parameters": parameters,
            "reference_path": str(reference),
            "target_tokens": tokens,
        },
        progress,
        lambda: False,
    )
    source = Path(result["source_path"])
    target = output_dir / f"target-{seconds:03d}s_seed-{seed}_tokens-{tokens}.wav"
    shutil.move(str(source), target)
    info = sf.info(str(target))
    actual = float(info.frames) / float(info.samplerate)
    return {
        "target_seconds": seconds,
        "seed": seed,
        "target_tokens": tokens,
        "actual_seconds": round(actual, 4),
        "error_seconds": round(actual - seconds, 4),
        "error_percent": round((actual - seconds) / seconds * 100, 2),
        "sample_rate": info.samplerate,
        "frames": info.frames,
        "filename": target.name,
        "text_chars": len(text),
    }


def validate(output_dir: Path, targets: list[int], seed: int, reference: Path) -> list[dict[str, Any]]:
    validation_dir = output_dir / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for seconds in targets:
        record = run_sample(validation_dir, seconds, seed, reference)
        tolerance = max(1.0, seconds * .1)
        record["tolerance_seconds"] = tolerance
        record["passed"] = abs(record["error_seconds"]) <= tolerance
        records.append(record)
        print(json.dumps({"validation": record}, ensure_ascii=False), flush=True)
    return records


def write_report(output_dir: Path, records: list[dict[str, Any]], reference: Path) -> None:
    grouped: dict[int, list[float]] = {}
    for record in records:
        grouped.setdefault(record["target_seconds"], []).append(record["actual_seconds"])
    summary = [
        {
            "target_seconds": target,
            "samples": len(values),
            "median_actual_seconds": round(statistics.median(values), 4),
            "median_error_seconds": round(statistics.median(values) - target, 4),
        }
        for target, values in sorted(grouped.items())
    ]
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": "MOSS-TTS-Local-Transformer-v1.5 4B",
        "reference": str(reference),
        "text_source": list(CALIBRATION_SENTENCES),
        "instruction": BUILT_IN_STYLES[0][1],
        "records": records,
        "summary": summary,
    }
    temporary = output_dir / "report.json.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output_dir / "report.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="MOSS-TTS 目标时长实机校准")
    parser.add_argument("--targets", default="5,10,20,30,60")
    parser.add_argument("--seeds", default="2026,2027,2028")
    parser.add_argument("--reference", default=str(ROOT / "data" / "uploads" / "d0953b096dd3418685fe2fb1eda9a78c_旁白1.wav"))
    parser.add_argument("--output", default=str(ROOT / "startup-lab" / "results" / "duration-calibration-v2"))
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--validation-seed", type=int, default=2029)
    parser.add_argument("--validation-name", default="validation")
    args = parser.parse_args()

    targets = parse_values(args.targets)
    seeds = parse_values(args.seeds)
    reference = Path(args.reference).resolve()
    if not reference.is_file():
        raise FileNotFoundError(f"校准参考音频不存在：{reference}")
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.validate:
        try:
            validation = validate(output_dir, targets, args.validation_seed, reference)
        finally:
            ENGINE.release()
        (output_dir / f"{args.validation_name}.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    report_path = output_dir / "report.json"
    records = []
    if report_path.is_file():
        records = json.loads(report_path.read_text(encoding="utf-8")).get("records", [])
    completed = {(item["target_seconds"], item["seed"]) for item in records}

    try:
        for seconds in targets:
            for seed in seeds:
                if (seconds, seed) in completed:
                    continue
                record = run_sample(output_dir, seconds, seed, reference)
                records.append(record)
                write_report(output_dir, records, reference)
                print(json.dumps(record, ensure_ascii=False), flush=True)
    finally:
        ENGINE.release()
    write_report(output_dir, records, reference)
    print(f"校准记录：{output_dir / 'report.json'}", flush=True)


if __name__ == "__main__":
    main()
