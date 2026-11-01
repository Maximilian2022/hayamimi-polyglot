"""
Hayamimi For Business - Audio DSP Preprocessing Chain.
Applies a 4-stage audio processing pipeline prior to ASR decoding:
  1. Noise Gate (soft-knee downward expander for background floor noise)
  2. Mid-Range Equalizer (85Hz high-pass cut + 300Hz-3.4kHz voice presence shaping)
  3. De-Esser (split-band dynamic sibilance suppression in 4.2kHz-7.6kHz)
  4. Automatic Gain Control (AGC) Compressor & Soft Limiter
Implemented in pure vectorized NumPy with zero external dependencies.
"""

from __future__ import annotations

import numpy as np


class AudioDSPChain:
    """
    4-stage audio preprocessing chain designed for speech recognition clarity.
    Operates on 16kHz mono float32 utterance chunks.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        gate_threshold_db: float = -48.0,
        target_rms_db: float = -17.0,
        max_gain_db: float = 12.0,
        comp_threshold_db: float = -12.0,
        comp_ratio: float = 3.0,
        deess_threshold_ratio: float = 0.38,
    ):
        self.sample_rate = sample_rate
        self.gate_threshold = 10.0 ** (gate_threshold_db / 20.0)
        self.target_rms = 10.0 ** (target_rms_db / 20.0)
        self.max_gain = 10.0 ** (max_gain_db / 20.0)
        self.comp_threshold = 10.0 ** (comp_threshold_db / 20.0)
        self.comp_ratio = max(1.0, comp_ratio)
        self.deess_threshold_ratio = deess_threshold_ratio

    def _compute_envelope(self, audio: np.ndarray, window_ms: float = 20.0) -> np.ndarray:
        """Compute a smooth sample-level RMS envelope using vectorized cumulative sums."""
        win_len = max(16, int(self.sample_rate * (window_ms / 1000.0)))
        if len(audio) <= win_len:
            rms = float(np.sqrt(np.mean(audio * audio) + 1e-12))
            return np.full_like(audio, rms)

        sq = audio.astype(np.float64) ** 2
        pad_left = win_len // 2
        pad_right = win_len - pad_left - 1
        padded = np.pad(sq, (pad_left, pad_right), mode="edge")
        csum = np.concatenate(([0.0], np.cumsum(padded)))
        mean_sq = (csum[win_len:] - csum[:-win_len]) / float(win_len)
        return np.sqrt(np.maximum(mean_sq, 1e-12)).astype(np.float32)

    def _apply_noise_gate(self, audio: np.ndarray) -> np.ndarray:
        """Stage 1: Soft-knee noise gate to attenuate low-level stationary room noise."""
        env = self._compute_envelope(audio, window_ms=25.0)
        # Soft-knee expansion below gate_threshold
        ratio = env / (self.gate_threshold + 1e-9)
        gain = np.where(ratio >= 1.0, 1.0, np.clip(ratio ** 1.5, 0.15, 1.0)).astype(np.float32)

        # Smooth gain transitions (attack/release smoothing ~15ms)
        smooth_len = max(8, int(self.sample_rate * 0.015))
        if len(gain) > smooth_len:
            kernel = np.ones(smooth_len, dtype=np.float32) / float(smooth_len)
            gain = np.convolve(gain, kernel, mode="same")

        return audio * gain

    def _apply_eq_and_deesser(self, audio: np.ndarray) -> np.ndarray:
        """
        Stage 2 & 3: Mid-range Equalizer + Split-band Dynamic De-Esser.
        Uses zero-phase FFT filtering for minimal latency and zero phase distortion.
        """
        n = len(audio)
        if n < 64:
            return audio

        spec = np.fft.rfft(audio)
        freqs = np.fft.rfftfreq(n, d=1.0 / float(self.sample_rate))

        # --- Stage 2: Mid-Range EQ ---
        # 1) 4th-order Butterworth-like High-Pass at 85Hz to remove hum and mic plosives
        hp_cutoff = 85.0
        hp_gain = 1.0 / np.sqrt(1.0 + (hp_cutoff / np.maximum(freqs, 1.0)) ** 8)
        hp_gain[0] = 0.0

        # 2) Gentle Mid-Range Presence Boost (+2.0 dB centered around 1.8kHz, spanning 300Hz-3.4kHz)
        center_freq = 1800.0
        bandwidth = 1400.0
        bell = np.exp(-0.5 * ((freqs - center_freq) / bandwidth) ** 2)
        presence_gain = 1.0 + (10.0 ** (2.0 / 20.0) - 1.0) * bell

        # 3) Gentle roll-off above 7500Hz to suppress high-frequency aliasing noise
        lp_cutoff = 7500.0
        lp_gain = 1.0 / np.sqrt(1.0 + (freqs / lp_cutoff) ** 8)

        eq_curve = (hp_gain * presence_gain * lp_gain).astype(np.float32)
        eq_spec = spec * eq_curve
        eq_audio = np.fft.irfft(eq_spec, n=n).astype(np.float32)

        # --- Stage 3: Split-band Dynamic De-Esser (4.2kHz - 7.6kHz) ---
        sib_mask = ((freqs >= 4200.0) & (freqs <= 7600.0)).astype(np.float32)
        sib_band = np.fft.irfft(eq_spec * sib_mask, n=n).astype(np.float32)

        full_env = self._compute_envelope(eq_audio, window_ms=10.0)
        sib_env = self._compute_envelope(sib_band, window_ms=10.0)

        # Detect harsh sibilance where high-frequency energy dominates total energy
        sib_ratio = sib_env / (full_env + 1e-5)
        excess = np.maximum(0.0, sib_ratio - self.deess_threshold_ratio)
        # Attenuate sibilance band up to -6dB (0.5x) during harsh sibilant peaks
        sib_reduction = np.clip(excess * 1.5, 0.0, 0.5).astype(np.float32)

        return eq_audio - (sib_band * sib_reduction)

    def _apply_agc_compressor(self, audio: np.ndarray) -> np.ndarray:
        """Stage 4: Automatic Gain Control (AGC) + Dynamic Compressor & Soft Limiter."""
        env = self._compute_envelope(audio, window_ms=35.0)

        # Estimate active speech level using the 80th percentile of envelope
        active_mask = env > (self.gate_threshold * 1.5)
        if np.any(active_mask):
            active_rms = float(np.percentile(env[active_mask], 80))
        else:
            active_rms = float(np.percentile(env, 80))

        if active_rms < 1e-4:
            return audio

        # Compute makeup gain toward target RMS (clamped to avoid over-amplifying quiet noise)
        desired_gain = self.target_rms / active_rms
        makeup_gain = float(np.clip(desired_gain, 0.5, self.max_gain))
        leveled = audio * makeup_gain
        leveled_env = env * makeup_gain

        # Dynamic downward compression above comp_threshold
        over = leveled_env > self.comp_threshold
        comp_gain = np.ones_like(leveled_env)
        if np.any(over):
            # In linear domain: g = (env / T) ** ((1/ratio) - 1)
            exponent = (1.0 / self.comp_ratio) - 1.0
            comp_gain[over] = (leveled_env[over] / self.comp_threshold) ** exponent

        compressed = leveled * comp_gain

        # Soft-knee peak limiter at +/- 0.95 to prevent digital clipping
        limit = 0.95
        abs_x = np.abs(compressed)
        over_limit = abs_x > 0.80
        if np.any(over_limit):
            sign = np.sign(compressed[over_limit])
            mag = abs_x[over_limit]
            compressed[over_limit] = sign * (0.80 + (limit - 0.80) * np.tanh((mag - 0.80) / (limit - 0.80)))

        return compressed.astype(np.float32)

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Run the full 4-stage audio DSP pipeline on a 16kHz mono float32 array."""
        if audio is None or len(audio) < 160:
            return audio

        x = np.asarray(audio, dtype=np.float32)
        if x.ndim > 1:
            x = x.reshape(-1)

        # Remove DC offset
        x = x - np.mean(x)

        # 1. Noise Gate
        x = self._apply_noise_gate(x)
        # 2 & 3. Mid-Range EQ + De-Esser
        x = self._apply_eq_and_deesser(x)
        # 4. AGC Compressor & Limiter
        x = self._apply_agc_compressor(x)

        return x

