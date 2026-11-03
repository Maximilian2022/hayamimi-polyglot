"""
Hayamimi Polyglot - CPU vs NPU accuracy comparison through the real ASR engine.

For every language it runs `BusinessASREngine.transcribe_pcm(..., hint_lang=<lang>)` once with the
CPU engines (device="cpu") and once with the NPU engines (device="npu", after the CPU->NPU swap),
and reports CER (ja/zh/ko) or WER (en/fr/de/es). Release rule of thumb: |NPU - CPU| <= 2 points.

Data: a folder per language containing .wav files and ref.json ({"<file>.wav": ["<reference>", ...]}),
e.g. created with --download-fleurs (Google FLEURS test split, CC-BY-4.0).

    python scripts/eval_npu.py --data eval_data --download-fleurs --per-lang 50
    python scripts/eval_npu.py --data eval_data
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import tarfile
import time
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# app language code -> (FLEURS config, metric)
LANGS = {
    "ja": ("ja_jp", "cer"), "zh": ("cmn_hans_cn", "cer"), "ko": ("ko_kr", "cer"),
    "en": ("en_us", "wer"), "fr": ("fr_fr", "wer"), "de": ("de_de", "wer"), "es": ("es_419", "wer"),
}
FLEURS = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/%s/"
MAX_SECONDS = 14.9  # utterances that fit one NPU window


def download_fleurs(data: Path, per_lang: int) -> None:
    for lang, (cfg, _) in LANGS.items():
        d = data / lang
        if (d / "ref.json").is_file():
            continue
        d.mkdir(parents=True, exist_ok=True)
        print(f"[fleurs] {lang}: downloading {per_lang} utterances ...")
        tsv = urllib.request.urlopen(FLEURS % cfg + "test.tsv").read().decode("utf-8")
        refs = {row[1]: row[2] for row in csv.reader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE) if len(row) > 3}
        got = {}
        with urllib.request.urlopen(FLEURS % cfg + "audio/test.tar.gz") as r, tarfile.open(fileobj=r, mode="r|gz") as t:
            for m in t:
                name = Path(m.name).name
                if m.isfile() and name in refs:
                    (d / name).write_bytes(t.extractfile(m).read())
                    got[name] = refs[name]
                    if len(got) >= per_lang:
                        break
        (d / "ref.json").write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")


def normalize(text: str, cjk: bool) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(c for c in text if not unicodedata.category(c).startswith(("P", "S")))
    text = " ".join(text.split())
    return text.replace(" ", "") if cjk else text


def edit_distance(a, b) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def error_rate(refs, hyps, metric: str) -> float:
    cjk = metric == "cer"
    errs = total = 0
    for r, h in zip(refs, hyps):
        r, h = normalize(r, cjk), normalize(h, cjk)
        rt, ht = (list(r), list(h)) if cjk else (r.split(), h.split())
        errs += edit_distance(rt, ht)
        total += len(rt)
    return 100.0 * errs / max(total, 1)


def load_utterances(data: Path, lang: str):
    import numpy as np
    import soundfile as sf
    from core.npu.base import resample_to_16k

    d = data / lang
    refs = json.loads((d / "ref.json").read_text(encoding="utf-8"))
    out = []
    for name, ref in sorted(refs.items()):
        w, sr = sf.read(str(d / name), dtype="float32")
        w = resample_to_16k(w if w.ndim == 1 else w[:, 0], sr)
        if len(w) / 16000 <= MAX_SECONDS:
            out.append((name, np.ascontiguousarray(w), ref[0] if isinstance(ref, list) else ref))
    return out


def run_engine(device: str, data: Path, langs, models_dir: Path):
    from core.asr_engine import BusinessASREngine
    from core.npu import addons

    if device == "npu":
        addons.run_startup(background=False)
    eng = BusinessASREngine(models_dir=models_dir, initial_languages=list(langs), device=device, high_accuracy_mode=True)
    if device == "npu":
        t0 = time.time()
        while time.time() - t0 < 900:
            summary = eng.get_device_summary()
            if summary and all(v == "npu" or (not v.startswith("cpu (NPU") and v != "npu-compiling") for v in summary.values()):
                break
            time.sleep(1)
        print(f"[npu] engine state: {eng.get_device_summary()}")
        if not any(v == "npu" for v in eng.get_device_summary().values()):
            raise SystemExit("no engine runs on the NPU; nothing to compare")
    results = {}
    for lang in langs:
        results[lang] = [eng.transcribe_pcm(w, hint_lang=lang) for _, w, _ in load_utterances(data, lang)]
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--per-lang", type=int, default=50)
    ap.add_argument("--download-fleurs", action="store_true")
    ap.add_argument("--langs", default=",".join(LANGS))
    ap.add_argument("--models-dir", type=Path, default=ROOT / "models")
    ap.add_argument("--max-delta", type=float, default=2.0, help="fail if any |NPU - CPU| exceeds this many points")
    args = ap.parse_args()
    langs = [l for l in args.langs.split(",") if l in LANGS]
    if args.download_fleurs:
        download_fleurs(args.data, args.per_lang)

    cpu = run_engine("cpu", args.data, langs, args.models_dir)
    npu = run_engine("npu", args.data, langs, args.models_dir)
    print(f"\n{'lang':5}{'n':>4}{'metric':>8}{'CPU':>9}{'NPU':>9}{'delta':>8}")
    worst = 0.0
    for lang in langs:
        utts = load_utterances(args.data, lang)
        refs = [r for _, _, r in utts]
        metric = LANGS[lang][1]
        a, b = error_rate(refs, cpu[lang], metric), error_rate(refs, npu[lang], metric)
        worst = max(worst, abs(b - a))
        print(f"{lang:5}{len(utts):>4}{metric.upper():>8}{a:>8.1f}%{b:>8.1f}%{b - a:>+7.1f}")
    print(f"\nlargest |delta| = {worst:.1f} points (limit {args.max_delta})")
    return 0 if worst <= args.max_delta else 1


if __name__ == "__main__":
    sys.exit(main())
