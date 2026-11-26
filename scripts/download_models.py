"""
Hayamimi Polyglot - Automated Model Downloader for CI & Clean Setup.
Downloads official open-source INT8 models directly from GitHub releases & Hugging Face.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODELS_DIR = ROOT / "models"

MOONSHINE_ZH_REPO = "https://huggingface.co/Masterx/moonshine-streaming-tiny-zh-ONNX/resolve/main/"
MOONSHINE_ZH_FILES = [
    "LICENSE",
    "README.md",
    "config.json",
    "generation_config.json",
    "preprocessor_config.json",
    "processor_config.json",
    "special_tokens_map.json",
    "streaming_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "frontend.onnx",
    "encoder_int8.onnx",
    "adapter_int8.onnx",
    "cross_kv_int8.onnx",
    "decoder_kv_int8.onnx",
]

NEMOTRON_REPO = (
    "https://huggingface.co/csukuangfj2/sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-1120ms-int8-2026-06-11/resolve/main/"
)
NEMOTRON_FILES = [
    "README.md",
    "tokens.txt",
    "encoder.int8.onnx",
    "decoder.int8.onnx",
    "joiner.int8.onnx",
    "test_wavs/zh.wav",
    "test_wavs/ko.wav",
    "test_wavs/ja.wav",
    "test_wavs/en.wav",
]


def download_file(url: str, dst: Path, desc: str = "") -> None:
    if dst.exists() and dst.stat().st_size > 0:
        print(f"  [Cached] {dst.name} ({dst.stat().st_size / (1024*1024):.1f} MB)")
        return
    print(f"[Downloading] {desc or dst.name} from {url} ...")
    dst.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Hayamimi-Model-Downloader"})
    temp_dst = dst.with_suffix(dst.suffix + ".tmp")
    with urllib.request.urlopen(req, timeout=120) as resp, open(temp_dst, "wb") as out:
        shutil.copyfileobj(resp, out)
    temp_dst.replace(dst)
    print(f"  [OK] Saved to {dst.name} ({dst.stat().st_size / (1024*1024):.1f} MB)")


def extract_tar_bz2(tar_path: Path, dst_dir: Path) -> None:
    print(f"[Extracting] {tar_path.name} to {dst_dir} ...")
    with tarfile.open(tar_path, "r:bz2") as tar:
        try:
            tar.extractall(path=dst_dir, filter="data")
        except TypeError:
            tar.extractall(path=dst_dir)
    print(f"  [OK] Extracted {tar_path.name}")


def ensure_models(
    models_dir: Path = DEFAULT_MODELS_DIR,
    with_parakeet: bool = True,
    with_asian_asr: bool = True,
    with_sense_voice: bool | None = None,
) -> None:
    # Keep `with_sense_voice` accepted as a deprecated alias for backward compatibility.
    if with_sense_voice is not None:
        with_asian_asr = with_sense_voice

    models_dir.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("[INFO] Ensuring Required AI Models in:", models_dir)
    print("=" * 60)

    # 1. Silero VAD
    vad_file = models_dir / "silero_vad.onnx"
    if not vad_file.exists():
        vad_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
        download_file(vad_url, vad_file, "Silero VAD ONNX")

    # 2. ReazonSpeech Zipformer INT8
    rz_dir = models_dir / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17"
    if not (rz_dir.is_dir() and (rz_dir / "tokens.txt").is_file()):
        rz_tar = models_dir / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17.tar.bz2"
        rz_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17.tar.bz2"
        download_file(rz_url, rz_tar, "ReazonSpeech INT8 Zipformer")
        extract_tar_bz2(rz_tar, models_dir)
        rz_tar.unlink(missing_ok=True)

    # 3. Parakeet TDT 0.6B v3 INT8
    if with_parakeet:
        p_dir = models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
        if not (p_dir.is_dir() and (p_dir / "tokens.txt").is_file()):
            p_tar = models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"
            p_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"
            download_file(p_url, p_tar, "Parakeet TDT 0.6B v3 INT8")
            extract_tar_bz2(p_tar, models_dir)
            p_tar.unlink(missing_ok=True)

    # 4. Asian ASR: Moonshine Streaming Tiny Zh (MIT) & Nemotron 3.5 ASR Streaming 0.6B (OpenMDW-1.1)
    if with_asian_asr:
        ms_zh_dir = models_dir / "moonshine-streaming-tiny-zh-onnx"
        for f in MOONSHINE_ZH_FILES:
            download_file(MOONSHINE_ZH_REPO + f, ms_zh_dir / f, f"Moonshine Zh {f}")

        nem_dir = models_dir / "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-1120ms-int8"
        for f in NEMOTRON_FILES:
            download_file(NEMOTRON_REPO + f, nem_dir / f, f"Nemotron 3.5 {f}")

        # Remove legacy SenseVoice model directories left over from earlier versions
        for legacy_dir in (
            models_dir / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
            models_dir / "npu" / "sensevoice",
        ):
            if legacy_dir.is_dir():
                print(f"[Cleanup] Removing legacy model directory: {legacy_dir}")
                shutil.rmtree(legacy_dir, ignore_errors=True)

    # 5. M2M-100 CT2 (Hugging Face)
    m2m_dir = models_dir / "mojicast-m2m100-ct2"
    m2m_dir.mkdir(parents=True, exist_ok=True)
    m2m_files = ["model.bin", "config.json", "shared_vocabulary.json", "sentencepiece.model"]
    for f in m2m_files:
        dst = m2m_dir / f
        if not dst.exists() or dst.stat().st_size == 0:
            url = f"https://huggingface.co/ishiki-emo/mojicast-m2m100-ct2/resolve/main/{f}"
            download_file(url, dst, f"M2M-100 {f}")

    # 6. FuguMT CT2 (Hugging Face)
    fugu_dir = models_dir / "mojicast-fugumt-ja-en-ct2"
    fugu_dir.mkdir(parents=True, exist_ok=True)
    fugu_files = ["model.bin", "config.json", "shared_vocabulary.json", "source.spm", "target.spm"]
    for f in fugu_files:
        dst = fugu_dir / f
        if not dst.exists() or dst.stat().st_size == 0:
            url = f"https://huggingface.co/ishiki-emo/mojicast-fugumt-ja-en-ct2/resolve/main/{f}"
            download_file(url, dst, f"FuguMT {f}")

    print("\n[SUCCESS] All required AI models verified in:", models_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download required AI models for Hayamimi Polyglot.")
    parser.add_argument("--models-dir", type=str, default=str(DEFAULT_MODELS_DIR))
    parser.add_argument("--no-parakeet", action="store_true")
    parser.add_argument("--no-asian-asr", "--no-sense-voice", dest="no_asian_asr", action="store_true")
    args = parser.parse_args()
    ensure_models(
        models_dir=Path(args.models_dir),
        with_parakeet=not args.no_parakeet,
        with_asian_asr=not args.no_asian_asr,
    )


if __name__ == "__main__":
    main()
