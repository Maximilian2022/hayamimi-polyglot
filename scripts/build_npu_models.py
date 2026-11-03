"""
Hayamimi Polyglot - build the NPU model set (development / CI tool).

Produces OpenVINO IR (fp16) models under <out>/ for the Intel NPU backends:

    reazon/      ReazonSpeech zipformer2 (encoder fixed to a 15 s window; decoder/joiner for CPU)
    sensevoice/  SenseVoice Small (whole network, fixed 15 s window, LayerNorm rescaled for fp16)
    parakeet/    Parakeet TDT 0.6B v3 (downloaded as-is from FluidInference/parakeet-tdt-0.6b-v3-ov)

Why this is needed: NPUs need static shapes and fp16-safe numerics, and the shipped CPU models
are dynamic-shape int8. The converted models are an *add-on*; the CPU models stay untouched.

Requirements (build machine only, never shipped to users): onnx, openvino, numpy.

    python scripts/build_npu_models.py --out models/npu              # reazon + sensevoice
    python scripts/build_npu_models.py --out models/npu --with-parakeet
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"

REAZON_FRAMES = 1500        # 15 s of fbank frames
SENSEVOICE_LFR_FRAMES = 250  # 15 s
LN_SCALE = 1.0 / 256.0       # LayerNorm input scale that keeps (x - mean)^2 inside the fp16 range

PARAKEET_REPO = "https://huggingface.co/FluidInference/parakeet-tdt-0.6b-v3-ov/resolve/main/"
PARAKEET_FILES = (
    "parakeet_melspectogram.xml", "parakeet_melspectogram.bin",
    "parakeet_encoder.xml", "parakeet_encoder.bin",
    "parakeet_decoder.xml", "parakeet_decoder.bin",
    "parakeet_joint.xml", "parakeet_joint.bin",
    "parakeet_v3_vocab.json",
)


def _save_ir(ov_model, xml_path: Path, fp16: bool) -> None:
    import openvino as ov
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    ov.save_model(ov_model, str(xml_path), compress_to_fp16=fp16)


def patch_layernorm_scale(model, scale: float = LN_SCALE) -> int:
    """
    Make every LayerNorm (decomposed as ReduceMean/Sub/Pow/ReduceMean/Add/Sqrt/Div) fp16-safe.

    LayerNorm is invariant to a uniform input scale when eps is scaled by scale**2, so the
    input is multiplied by `scale` first. This keeps (x - mean)^2 below the fp16 maximum
    (65504) for the large residual-stream activations of SenseVoice.
    Returns the number of LayerNorms patched.
    """
    import numpy as np
    from onnx import helper, numpy_helper

    g = model.graph
    by_name = {n.name: n for n in g.node}
    g.initializer.append(numpy_helper.from_array(np.array(scale, dtype=np.float32), "ln_scale"))
    patched = []
    for n in list(g.node):
        if n.op_type != "Pow" or not n.name.endswith("/Pow"):
            continue
        prefix = n.name[:-4]
        mean_node, sub_node, add_node = (by_name.get(prefix + s) for s in ("/ReduceMean", "/Sub", "/Add"))
        if not (mean_node and sub_node and add_node):
            continue
        x = mean_node.input[0]
        if sub_node.input[0] != x:
            raise RuntimeError(f"unexpected LayerNorm structure at {prefix}")
        xs = prefix + "/ScaleIn_out"
        scale_node = helper.make_node("Mul", [x, "ln_scale"], [xs], name=prefix + "/ScaleIn")
        mean_node.input[0] = xs
        sub_node.input[0] = xs
        eps_name = add_node.input[1]
        const = next(k for k in g.node if k.op_type == "Constant" and eps_name in k.output)
        t = const.attribute[0].t
        const.attribute[0].t.CopyFrom(numpy_helper.from_array(numpy_helper.to_array(t).astype(np.float32) * scale * scale, t.name))
        patched.append((mean_node, scale_node))
    for mean_node, scale_node in patched:
        g.node.insert(list(g.node).index(mean_node), scale_node)
    return len(patched)


def build_reazon(out: Path, src: Path | None = None) -> None:
    import numpy as np
    import onnx
    import openvino as ov
    from onnx import numpy_helper

    src = src or MODELS / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17"
    enc_path = src / "encoder-epoch-35-avg-1.onnx"
    if not enc_path.is_file():
        raise SystemExit(f"fp32 ReazonSpeech encoder not found: {enc_path}\n"
                         "(the tar.bz2 from k2-fsa/sherpa-onnx releases contains it)")
    dst = out / "reazon"
    print(f"[reazon] fixing the encoder to {REAZON_FRAMES} frames ...")
    m = onnx.load(str(enc_path))
    g = m.graph
    g.input.remove(next(i for i in g.input if i.name == "x_lens"))
    g.initializer.append(numpy_helper.from_array(np.array([REAZON_FRAMES], dtype=np.int64), "x_lens"))
    dims = g.input[0].type.tensor_type.shape.dim
    dims[0].dim_value, dims[1].dim_value = 1, REAZON_FRAMES
    tmp = dst / "_encoder_fixed.onnx"
    dst.mkdir(parents=True, exist_ok=True)
    onnx.save(m, str(tmp))
    _save_ir(ov.convert_model(str(tmp)), dst / "encoder.xml", fp16=True)
    tmp.unlink()

    # decoder/joiner are tiny and run on the CPU plugin; make their batch static (N=1)
    for name, shapes in (("decoder", {"y": [1, 2]}), ("joiner", {"encoder_out": [1, 512], "decoder_out": [1, 512]})):
        model = ov.convert_model(str(src / f"{name}-epoch-35-avg-1.onnx"))
        model.reshape(shapes)
        _save_ir(model, dst / f"{name}.xml", fp16=False)

    shutil.copy2(src / "tokens.txt", dst / "tokens.txt")
    (dst / "meta.json").write_text(json.dumps({"frames": REAZON_FRAMES}), encoding="utf-8")
    print("[reazon] done")


def build_sensevoice(out: Path, src: Path | None = None) -> None:
    import numpy as np
    import onnx
    import openvino as ov
    from onnx import numpy_helper

    src = src or MODELS / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    model_path = src / "model.onnx"
    if not model_path.is_file():
        raise SystemExit(f"fp32 SenseVoice model not found: {model_path}")
    dst = out / "sensevoice"
    dst.mkdir(parents=True, exist_ok=True)
    print("[sensevoice] rescaling LayerNorm for fp16 and fixing the window ...")
    m = onnx.load(str(model_path))
    meta = {p.key: p.value for p in m.metadata_props}
    count = patch_layernorm_scale(m)
    if count == 0:
        raise SystemExit("no LayerNorm found to patch; the model layout changed")
    print(f"[sensevoice] patched {count} LayerNorm blocks")

    g = m.graph
    xl = next(i for i in g.input if i.name == "x_length")
    dtype = np.int32 if xl.type.tensor_type.elem_type == 6 else np.int64
    g.input.remove(xl)
    g.initializer.append(numpy_helper.from_array(np.array([SENSEVOICE_LFR_FRAMES], dtype=dtype), "x_length"))
    for inp in g.input:
        inp.type.tensor_type.shape.dim[0].dim_value = 1
        if inp.name == "x":
            inp.type.tensor_type.shape.dim[1].dim_value = SENSEVOICE_LFR_FRAMES
    tmp = dst / "_model_fixed.onnx"
    onnx.save(m, str(tmp))
    _save_ir(ov.convert_model(str(tmp)), dst / "model.xml", fp16=True)
    tmp.unlink()

    shutil.copy2(src / "tokens.txt", dst / "tokens.txt")
    (dst / "meta.json").write_text(json.dumps({
        "lfr_frames": SENSEVOICE_LFR_FRAMES,
        "neg_mean": [float(v) for v in meta["neg_mean"].split(",")],
        "inv_stddev": [float(v) for v in meta["inv_stddev"].split(",")],
        "lang_auto": int(meta.get("lang_auto", 0)),
        "with_itn": int(meta.get("with_itn", 14)),
    }), encoding="utf-8")
    print("[sensevoice] done")


def fetch_parakeet(out: Path) -> None:
    dst = out / "parakeet"
    dst.mkdir(parents=True, exist_ok=True)
    for name in PARAKEET_FILES:
        target = dst / name
        if target.is_file() and target.stat().st_size > 0:
            print(f"[parakeet] cached {name}")
            continue
        print(f"[parakeet] downloading {name} ...")
        req = urllib.request.Request(PARAKEET_REPO + name, headers={"User-Agent": "Hayamimi-NPU-Builder"})
        tmp = target.with_suffix(target.suffix + ".tmp")
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f, length=1024 * 1024)
        tmp.replace(target)
    print("[parakeet] done")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=MODELS / "npu")
    ap.add_argument("--only", choices=["reazon", "sensevoice", "parakeet"])
    ap.add_argument("--with-parakeet", action="store_true")
    args = ap.parse_args()
    todo = [args.only] if args.only else ["reazon", "sensevoice"] + (["parakeet"] if args.with_parakeet else [])
    if len(todo) > 1:
        # OpenVINO numbers its nodes with a process-wide counter, so each model is built in its own
        # fresh process. That keeps the generated files byte-identical between runs and machines,
        # which the add-on's pinned manifest hash (core/npu/addons_known.json) depends on.
        import subprocess

        for name in todo:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--out", str(args.out), "--only", name], check=True)
        return 0
    name = todo[0]
    if name == "reazon":
        build_reazon(args.out)
    elif name == "sensevoice":
        build_sensevoice(args.out)
    else:
        fetch_parakeet(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
