"""
Hayamimi For Business - Local Realtime Multilingual Translation Engine.
Supports multilingual bidirectional translation via M2M-100 (418M INT8),
plus FuguMT for Japanese -> English.
Runs offline with no external network requests during runtime.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Callable, Dict, List, Optional

import ctranslate2
import sentencepiece as spm


# Major business language codes supported out-of-the-box (7 Core Languages)
SUPPORTED_LANGUAGES: Dict[str, str] = {
    "ja": "日本語",
    "en": "英語",
    "zh": "中国語 (簡体字)",
    "ko": "韓国語",
    "fr": "フランス語",
    "de": "ドイツ語",
    "es": "スペイン語",
}


class LocalTranslator:
    """
    Local CTranslate2-based multilingual translator for business meetings.
    Supports bidirectional translation across ja, en, zh, ko, fr, de, es.
    """

    def __init__(self, models_dir: Path | str | None = None):
        if models_dir is None:
            candidates = [
                Path(__file__).resolve().parent.parent / "models",
                Path(__file__).resolve().parent.parent.parent / "models",
                Path("models"),
            ]
            for c in candidates:
                if c.is_dir() and (c / "mojicast-m2m100-ct2").is_dir():
                    models_dir = c
                    break

        self.models_dir = Path(models_dir) if models_dir else Path("models")
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="Translator")
        self._is_shutdown = False

        # 1. FuguMT (ja -> en)
        self._fugumt_translator: Optional[ctranslate2.Translator] = None
        self._fugumt_source_sp: Optional[spm.SentencePieceProcessor] = None
        self._fugumt_target_sp: Optional[spm.SentencePieceProcessor] = None

        # 2. M2M-100 (Multilingual bidirectional)
        self._m2m_translator: Optional[ctranslate2.Translator] = None
        self._m2m_sp: Optional[spm.SentencePieceProcessor] = None

        self._load_models()

    def _load_models(self) -> None:
        """Load CTranslate2 INT8 models if available."""
        # 1. FuguMT (ja -> en)
        fugumt_dir = self.models_dir / "mojicast-fugumt-ja-en-ct2"
        if fugumt_dir.is_dir():
            try:
                self._fugumt_translator = ctranslate2.Translator(
                    str(fugumt_dir),
                    device="cpu",
                    compute_type="int8",
                    inter_threads=1,
                    intra_threads=2,
                )
                source_spm = fugumt_dir / "source.spm"
                target_spm = fugumt_dir / "target.spm"
                if source_spm.is_file() and target_spm.is_file():
                    with open(source_spm, "rb") as f:
                        self._fugumt_source_sp = spm.SentencePieceProcessor(model_proto=f.read())
                    with open(target_spm, "rb") as f:
                        self._fugumt_target_sp = spm.SentencePieceProcessor(model_proto=f.read())
            except Exception:
                pass

        # 2. M2M-100 (Any-to-Any)
        m2m_dir = self.models_dir / "mojicast-m2m100-ct2"
        if m2m_dir.is_dir():
            try:
                self._m2m_translator = ctranslate2.Translator(
                    str(m2m_dir),
                    device="cpu",
                    compute_type="int8",
                    inter_threads=1,
                    intra_threads=2,
                )
                sp_model = m2m_dir / "sentencepiece.model"
                if sp_model.is_file():
                    with open(sp_model, "rb") as f:
                        self._m2m_sp = spm.SentencePieceProcessor(model_proto=f.read())
            except Exception:
                pass

    def translate(self, text: str, src_lang: str = "ja", tgt_lang: str = "en") -> str:
        """
        Translate text from src_lang to tgt_lang locally.
        """
        text = text.strip()
        if not text or src_lang == tgt_lang:
            return text

        # Use FuguMT for ja -> en if available (requires trailing </s> EOS token for Marian models)
        if src_lang == "ja" and tgt_lang == "en" and self._fugumt_translator and self._fugumt_source_sp and self._fugumt_target_sp:
            try:
                tokens = self._fugumt_source_sp.encode_as_pieces(text) + ["</s>"]
                results = self._fugumt_translator.translate_batch(
                    [tokens],
                    beam_size=1,
                    no_repeat_ngram_size=3,
                    repetition_penalty=1.1,
                    max_decoding_length=150,
                )
                output_tokens = results[0].hypotheses[0]
                return self._fugumt_target_sp.decode_pieces(output_tokens).strip()
            except Exception:
                pass

        # Universal M2M-100 translation
        if self._m2m_translator and self._m2m_sp:
            try:
                pieces = self._m2m_sp.encode_as_pieces(text)
                tokens = [f"__{src_lang}__"] + pieces + ["</s>"]
                results = self._m2m_translator.translate_batch(
                    [tokens],
                    target_prefix=[[f"__{tgt_lang}__"]],
                    beam_size=1,
                    no_repeat_ngram_size=3,
                    max_decoding_length=150,
                )
                output_tokens = results[0].hypotheses[0]
                if output_tokens and output_tokens[0] == f"__{tgt_lang}__":
                    output_tokens = output_tokens[1:]
                return self._m2m_sp.decode_pieces(output_tokens).strip()
            except Exception:
                return text

        return text

    def translate_ja_to_en(self, text: str) -> str:
        return self.translate(text, src_lang="ja", tgt_lang="en")

    def translate_en_to_ja(self, text: str) -> str:
        return self.translate(text, src_lang="en", tgt_lang="ja")

    def translate_async(
        self,
        text: str,
        direction: str,
        callback: Callable[[str, str], None],
    ) -> None:
        """Asynchronously translate without blocking the audio/ASR pipeline."""
        if not text.strip() or self._is_shutdown:
            return

        def _worker():
            if self._is_shutdown:
                return
            if "->" in direction:
                src, tgt = direction.split("->", 1)
                res = self.translate(text, src_lang=src.strip(), tgt_lang=tgt.strip())
            else:
                res = text
            if not self._is_shutdown:
                callback(text, res)

        try:
            self._executor.submit(_worker)
        except RuntimeError:
            pass

    def translate_multicast(
        self,
        text: str,
        src_lang: str,
        target_langs: List[str],
    ) -> Dict[str, str]:
        """
        Translate text from src_lang to multiple target languages simultaneously (Max 5 targets).
        """
        text = text.strip()
        if not text:
            return {}

        results: Dict[str, str] = {}
        targets = [t for t in target_langs if t != src_lang][:5]
        if not targets:
            return {}

        # 1. FuguMT for ja -> en if applicable
        m2m_targets = list(targets)
        if src_lang == "ja" and "en" in targets and self._fugumt_translator and self._fugumt_source_sp and self._fugumt_target_sp:
            try:
                en_trans = self.translate(text, src_lang="ja", tgt_lang="en")
                if en_trans and en_trans != text:
                    results["en"] = en_trans
                m2m_targets.remove("en")
            except Exception:
                pass

        # 2. M2M-100 batch inference for all remaining targets
        if m2m_targets and self._m2m_translator and self._m2m_sp:
            try:
                pieces = self._m2m_sp.encode_as_pieces(text)
                src_tokens = [f"__{src_lang}__"] + pieces + ["</s>"]

                batch_tokens = [src_tokens] * len(m2m_targets)
                target_prefixes = [[f"__{tgt}__"] for tgt in m2m_targets]

                batch_results = self._m2m_translator.translate_batch(
                    batch_tokens,
                    target_prefix=target_prefixes,
                    beam_size=1,
                    no_repeat_ngram_size=3,
                    max_decoding_length=150,
                )

                for tgt, res_item in zip(m2m_targets, batch_results):
                    if res_item.hypotheses:
                        out_tokens = res_item.hypotheses[0]
                        if out_tokens and out_tokens[0] == f"__{tgt}__":
                            out_tokens = out_tokens[1:]
                        trans_text = self._m2m_sp.decode_pieces(out_tokens).strip()
                        if trans_text and trans_text != text:
                            results[tgt] = trans_text
            except Exception:
                for tgt in m2m_targets:
                    res = self.translate(text, src_lang=src_lang, tgt_lang=tgt)
                    if res and res != text:
                        results[tgt] = res
        elif m2m_targets:
            for tgt in m2m_targets:
                res = self.translate(text, src_lang=src_lang, tgt_lang=tgt)
                if res and res != text:
                    results[tgt] = res

        return results

    def translate_multicast_async(
        self,
        text: str,
        src_lang: str,
        target_langs: List[str],
        callback: Callable[[str, Dict[str, str]], None],
    ) -> None:
        """Asynchronously multicast translate to multiple languages."""
        if not text.strip() or self._is_shutdown:
            return

        def _worker():
            if self._is_shutdown:
                return
            results = self.translate_multicast(text, src_lang, target_langs)
            if not self._is_shutdown:
                callback(text, results)

        try:
            self._executor.submit(_worker)
        except RuntimeError:
            pass

    def shutdown(self, wait: bool = False) -> None:
        """Cleanly shut down the translation worker thread pool."""
        self._is_shutdown = True
        try:
            self._executor.shutdown(wait=wait, cancel_futures=True)
        except Exception:
            pass
