"""
Hayamimi Polyglot - Automated Model Downloader for CI & Clean Setup.
Downloads official open-source INT8 models directly from GitHub releases & Hugging Face.
Zero user data transmission. Fully reproducible.
"""

import os
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
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)


def download_file(url: str, dst: Path, desc: str = ""):
    if dst.exists() and dst.stat().st_size > 0:
        print(f"  [Cached] {dst.name} ({dst.stat().st_size / (1024*1024):.1f} MB)")
        return
    print(f"[Downloading] {desc or dst.name} from {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "Hayamimi-Model-Downloader"})
    temp_dst = dst.with_suffix(dst.suffix + ".tmp")
    with urllib.request.urlopen(req) as resp, open(temp_dst, "wb") as out:
        shutil.copyfileobj(resp, out)
    temp_dst.rename(dst)
    print(f"  [OK] Saved to {dst.name} ({dst.stat().st_size / (1024*1024):.1f} MB)")


def extract_tar_bz2(tar_path: Path, dst_dir: Path):
    print(f"[Extracting] {tar_path.name} to {dst_dir} ...")
    with tarfile.open(tar_path, "r:bz2") as tar:
        tar.extractall(path=dst_dir)
    print(f"  [OK] Extracted {tar_path.name}")


def ensure_models():
    print("=" * 60)
    print("[INFO] Ensuring All Required AI Models in:", MODELS_DIR)
    print("=" * 60)

    # 1. Silero VAD
    vad_file = MODELS_DIR / "silero_vad.onnx"
    if not vad_file.exists():
        vad_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
        download_file(vad_url, vad_file, "Silero VAD ONNX")

    # 2. ReazonSpeech Zipformer INT8
    rz_dir = MODELS_DIR / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17"
    if not (rz_dir.is_dir() and (rz_dir / "tokens.txt").is_file()):
        rz_tar = MODELS_DIR / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17.tar.bz2"
        rz_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17.tar.bz2"
        download_file(rz_url, rz_tar, "ReazonSpeech INT8 Zipformer")
        extract_tar_bz2(rz_tar, MODELS_DIR)
        if rz_tar.exists():
            rz_tar.unlink()

    # 3. Parakeet TDT 0.6B v3 INT8
    p_dir = MODELS_DIR / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
    if not (p_dir.is_dir() and (p_dir / "tokens.txt").is_file()):
        p_tar = MODELS_DIR / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"
        p_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"
        download_file(p_url, p_tar, "Parakeet TDT 0.6B v3 INT8")
        extract_tar_bz2(p_tar, MODELS_DIR)
        if p_tar.exists():
            p_tar.unlink()

    # 4. SenseVoice Small INT8
    sv_dir = MODELS_DIR / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    if not (sv_dir.is_dir() and (sv_dir / "tokens.txt").is_file()):
        sv_tar = MODELS_DIR / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
        sv_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
        download_file(sv_url, sv_tar, "SenseVoice Small INT8")
        extract_tar_bz2(sv_tar, MODELS_DIR)
        if sv_tar.exists():
            sv_tar.unlink()

    # 5. M2M-100 CT2 (Hugging Face)
    m2m_dir = MODELS_DIR / "mojicast-m2m100-ct2"
    m2m_dir.mkdir(parents=True, exist_ok=True)
    m2m_files = ["model.bin", "config.json", "shared_vocabulary.json", "sentencepiece.model"]
    for f in m2m_files:
        dst = m2m_dir / f
        if not dst.exists() or dst.stat().st_size == 0:
            url = f"https://huggingface.co/ishiki-emo/mojicast-m2m100-ct2/resolve/main/{f}"
            download_file(url, dst, f"M2M-100 {f}")

    # 6. FuguMT CT2 (Hugging Face)
    fugu_dir = MODELS_DIR / "mojicast-fugumt-ja-en-ct2"
    fugu_dir.mkdir(parents=True, exist_ok=True)
    fugu_files = ["model.bin", "config.json", "shared_vocabulary.json", "source.spm", "target.spm"]
    for f in fugu_files:
        dst = fugu_dir / f
        if not dst.exists() or dst.stat().st_size == 0:
            url = f"https://huggingface.co/ishiki-emo/mojicast-fugumt-ja-en-ct2/resolve/main/{f}"
            download_file(url, dst, f"FuguMT {f}")

    print("\n[SUCCESS] All AI models verified in models/ directory!")


if __name__ == "__main__":
    ensure_models()
