"""
Hayamimi Polyglot - Moonshine Streaming ONNX Recognizer (MIT License compatible).

Provides a thin OfflineRecognizer-compatible interface (`create_stream`, `decode_stream`,
`stream.result.text`) over the 5-graph incremental ONNX export of Moonshine v2
(`frontend.onnx`, `encoder*.onnx`, `adapter*.onnx`, `cross_kv*.onnx`, `decoder_kv*.onnx`).

Designed to work generically with any Moonshine Streaming language pack (currently
`moonshine-streaming-tiny-zh-onnx`, and future `moonshine-streaming-*-ko-onnx` packs).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import onnxruntime as ort


def _pick_onnx(directory: Path, stem: str) -> Optional[Path]:
    """Prefer INT8 quantized ONNX if available, falling back to fp32."""
    for name in (f"{stem}_int8.onnx", f"{stem}.int8.onnx", f"{stem}.onnx"):
        p = directory / name
        if p.is_file():
            return p
    return None


def _resample_16k(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate == 16000 or len(samples) == 0:
        return np.ascontiguousarray(samples, dtype=np.float32)
    n_out = max(1, int(round(len(samples) * 16000.0 / float(sample_rate))))
    x_old = np.linspace(0.0, 1.0, len(samples), endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.ascontiguousarray(np.interp(x_new, x_old, samples), dtype=np.float32)


@dataclass
class _StreamResult:
    text: str = ""


class _MoonshineStream:
    def __init__(self) -> None:
        self.samples: np.ndarray = np.zeros(0, dtype=np.float32)
        self.result = _StreamResult()

    def accept_waveform(self, sample_rate: int, waveform: np.ndarray) -> None:
        arr = np.asarray(waveform, dtype=np.float32)
        if arr.ndim > 1:
            arr = arr[:, 0]
        if sample_rate != 16000:
            arr = _resample_16k(arr, sample_rate)
        if len(self.samples) == 0:
            self.samples = np.ascontiguousarray(arr, dtype=np.float32)
        else:
            self.samples = np.concatenate([self.samples, arr]).astype(np.float32)


class MoonshineStreamingRecognizer:
    """OfflineRecognizer-compatible runner for Moonshine v2 5-graph ONNX models."""

    def __init__(self, model_dir: Path | str, num_threads: int = 2) -> None:
        self.model_dir = Path(model_dir)
        cfg_path = self.model_dir / "streaming_config.json"
        tok_path = self.model_dir / "tokenizer.json"
        if not (cfg_path.is_file() and tok_path.is_file()):
            raise FileNotFoundError(f"Incomplete Moonshine config/tokenizer in {self.model_dir}")

        self.cfg: dict = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.id2tok: Dict[int, str] = self._load_vocab(tok_path)

        frontend = _pick_onnx(self.model_dir, "frontend")
        encoder = _pick_onnx(self.model_dir, "encoder")
        adapter = _pick_onnx(self.model_dir, "adapter")
        cross_kv = _pick_onnx(self.model_dir, "cross_kv")
        decoder_kv = _pick_onnx(self.model_dir, "decoder_kv")
        missing = [
            name
            for name, path in (
                ("frontend", frontend),
                ("encoder", encoder),
                ("adapter", adapter),
                ("cross_kv", cross_kv),
                ("decoder_kv", decoder_kv),
            )
            if path is None
        ]
        if missing:
            raise FileNotFoundError(f"Missing Moonshine ONNX graphs {missing} in {self.model_dir}")

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, int(num_threads))
        opts.inter_op_num_threads = 1
        providers = ["CPUExecutionProvider"]

        self.frontend = ort.InferenceSession(str(frontend), opts, providers=providers)
        self.encoder = ort.InferenceSession(str(encoder), opts, providers=providers)
        self.adapter = ort.InferenceSession(str(adapter), opts, providers=providers)
        self.cross_kv = ort.InferenceSession(str(cross_kv), opts, providers=providers)
        self.decoder_kv = ort.InferenceSession(str(decoder_kv), opts, providers=providers)

    @staticmethod
    def is_valid_dir(model_dir: Path) -> bool:
        if not model_dir.is_dir():
            return False
        if not ((model_dir / "streaming_config.json").is_file() and (model_dir / "tokenizer.json").is_file()):
            return False
        return all(
            _pick_onnx(model_dir, stem) is not None
            for stem in ("frontend", "encoder", "adapter", "cross_kv", "decoder_kv")
        )

    @staticmethod
    def _load_vocab(tok_path: Path) -> Dict[int, str]:
        tok_data = json.loads(tok_path.read_text(encoding="utf-8"))
        vocab = tok_data["model"]["vocab"]
        if isinstance(vocab, dict):
            id2tok = {int(v): str(k) for k, v in vocab.items()}
        else:
            id2tok = {
                i: str(item[0] if isinstance(item, list) else item)
                for i, item in enumerate(vocab)
            }
        for added in tok_data.get("added_tokens", []):
            id2tok[int(added["id"])] = str(added["content"])
        return id2tok

    def create_stream(self) -> _MoonshineStream:
        return _MoonshineStream()

    def decode_stream(self, stream: _MoonshineStream) -> None:
        pcm = stream.samples
        # Ignore empty or sub-100ms transient audio
        if len(pcm) < 1600:
            stream.result.text = ""
            return

        # Respect max_position_embeddings (typically 4096 frames * 320 samples ~= 81.9s)
        max_samples = int(self.cfg.get("max_position_embeddings", 4096)) * 320
        if len(pcm) > max_samples:
            pcm = pcm[:max_samples]

        # frontend.onnx requires a multiple of 640 samples
        pad = (-len(pcm)) % 640
        if pad:
            pcm = np.concatenate([pcm, np.zeros(pad, dtype=np.float32)])

        shapes = self.cfg["frontend_state_shapes"]
        feats, *_ = self.frontend.run(
            None,
            {
                "audio_chunk": pcm[None, :],
                "sample_buffer": np.zeros(shapes["sample_buffer"], dtype=np.float32),
                "sample_len": np.zeros(shapes["sample_len"], dtype=np.int64),
                "conv1_buffer": np.zeros(shapes["conv1_buffer"], dtype=np.float32),
                "conv2_buffer": np.zeros(shapes["conv2_buffer"], dtype=np.float32),
                "frame_count": np.zeros(shapes["frame_count"], dtype=np.int64),
            },
        )
        (encoded,) = self.encoder.run(None, {"features": feats})
        (memory,) = self.adapter.run(
            None,
            {"encoded": encoded, "pos_offset": np.array([0], dtype=np.int64)},
        )
        k_cross, v_cross = self.cross_kv.run(None, {"memory": memory})

        depth = int(self.cfg["depth"])
        nheads = int(self.cfg["nheads"])
        head_dim = int(self.cfg["head_dim"])
        k_self = np.zeros((depth, 1, nheads, 0, head_dim), dtype=np.float32)
        v_self = np.zeros((depth, 1, nheads, 0, head_dim), dtype=np.float32)

        cur_tok = int(self.cfg["bos_id"])
        eos_id = int(self.cfg["eos_id"])
        max_tokens = max(16, int(len(pcm) / 16000.0 * 14))
        out_ids: List[int] = []
        repeat_count = 0
        prev_tok = -1

        for _ in range(max_tokens):
            logits, k_self, v_self, k_cross, v_cross = self.decoder_kv.run(
                None,
                {
                    "token": np.array([[cur_tok]], dtype=np.int64),
                    "k_self": k_self,
                    "v_self": v_self,
                    "out_k_cross": k_cross,
                    "out_v_cross": v_cross,
                },
            )
            nxt = int(np.argmax(logits[0, -1]))
            if nxt == eos_id:
                break
            if nxt == prev_tok:
                repeat_count += 1
                if repeat_count >= 8:
                    break
            else:
                repeat_count = 0
                prev_tok = nxt
            out_ids.append(nxt)
            cur_tok = nxt

        stream.result.text = self._decode_ids(out_ids)

    def _decode_ids(self, ids: List[int]) -> str:
        toks: List[str] = []
        bos_id = int(self.cfg.get("bos_id", 1))
        eos_id = int(self.cfg.get("eos_id", 2))
        for tid in ids:
            if tid in (bos_id, eos_id):
                continue
            s = self.id2tok.get(tid, "")
            if s.startswith("<") and s.endswith(">"):
                continue
            toks.append(s)
        return "".join(toks).replace("\u2581", " ").replace("Ġ", " ").strip()
