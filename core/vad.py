"""
Hayamimi For Business - Silero VAD (ONNX).
Zero external communication. CPU optimized.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import onnxruntime as ort


class SileroVAD:
    """Silero VAD ONNX wrapper for real-time speech detection."""

    def __init__(self, model_path: Path | str | None = None, models_dir: Path | str | None = None, threshold: float = 0.5):
        if model_path is not None:
            mp = Path(model_path)
            if mp.is_dir():
                models_dir = mp
                model_path = None

        if model_path is None:
            if models_dir:
                p = Path(models_dir) / "silero_vad.onnx"
                if p.is_file():
                    model_path = p
            if model_path is None:
                candidates = [
                    Path(__file__).resolve().parent.parent / "models" / "silero_vad.onnx",
                    Path("models") / "silero_vad.onnx",
                    Path.home() / ".cache" / "hayamimi-polyglot" / "models" / "silero_vad.onnx",
                    Path("D:/hayamimi4b/models") / "silero_vad.onnx",
                ]
                for c in candidates:
                    if c.is_file():
                        model_path = c
                        break

        if model_path is None or not Path(model_path).is_file():
            raise FileNotFoundError(f"Silero VAD model not found: {model_path}")

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        self.threshold = threshold

        # Auto-detect input names (Silero VAD v4 uses 'x', v5 uses 'input', with or without 'sr')
        model_input_names = [inp.name for inp in self.session.get_inputs()]
        self._audio_input_name = "x" if "x" in model_input_names else "input"
        self._needs_sr = "sr" in model_input_names
        self.reset()

    def reset(self):
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def is_speech(self, chunk_512: np.ndarray, sample_rate: int = 16000) -> bool:
        """Process a 512-sample float32 chunk (32ms at 16kHz)."""
        if len(chunk_512) != 512:
            return False

        x = chunk_512.reshape(1, -1).astype(np.float32)

        inputs = {
            self._audio_input_name: x,
            "h": self._h,
            "c": self._c,
        }
        if self._needs_sr:
            inputs["sr"] = np.array([sample_rate], dtype=np.int64)

        try:
            outputs = self.session.run(None, inputs)
            out, h, c = outputs[0], outputs[1], outputs[2]
            self._h = h
            self._c = c
            prob = float(out.flatten()[0])
            if prob >= self.threshold:
                return True
            # Energy fallback guard for voice transients (RMS > 0.03)
            rms = float(np.sqrt(np.mean(chunk_512**2)))
            return rms > 0.035
        except Exception as ex:
            # Fallback to pure energy VAD if model inference fails
            rms = float(np.sqrt(np.mean(chunk_512**2)))
            return rms > 0.025
