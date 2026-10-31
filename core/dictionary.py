"""
Hayamimi For Business - Business Dictionary & Instant Hotwords Engine.
Uses SudachiPy (Apache-2.0) for morphological analysis and named entity extraction.
Zero network communication. 100% offline.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Set


class BusinessDictionary:
    def __init__(self, dict_dir: Path | None = None):
        if dict_dir is None:
            dict_dir = Path(__file__).resolve().parent.parent / "dicts"
        self.dict_dir = dict_dir
        self.static_terms: Set[str] = set()
        self.instant_hotwords: List[str] = []
        self._tokenizer = None

        self._load_static_dicts()

    def _get_tokenizer(self):
        if self._tokenizer is None:
            try:
                from sudachipy import dictionary, SplitMode
                self._tokenizer = dictionary.Dictionary(dict="full").create()
                self._split_mode = SplitMode.C
            except Exception:
                try:
                    from sudachipy import dictionary, SplitMode
                    self._tokenizer = dictionary.Dictionary().create()
                    self._split_mode = SplitMode.C
                except Exception:
                    self._tokenizer = None
                    self._split_mode = None
        return self._tokenizer

    def _load_static_dicts(self) -> None:
        """Load business terms and listed company names."""
        for filename in ("business_terms.txt", "listed_companies.txt"):
            p = self.dict_dir / filename
            if p.is_file():
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            self.static_terms.add(line)

    def extract_keywords_from_text(self, text: str, max_keywords: int = 50) -> List[str]:
        """
        Extract business keywords, technical terms, and proper nouns from agenda/document text.
        Instant Hotwords generator.
        """
        if not text or not text.strip():
            return []

        tokenizer = self._get_tokenizer()
        extracted: List[str] = []
        seen: Set[str] = set()

        # 1. Regex for alphanumeric acronyms and English business terms (e.g., KPI, AWS, Project-X, SaaS)
        ascii_terms = re.findall(r"\b[A-Za-z0-9][A-Za-z0-9_\-\.]{1,20}\b", text)
        for term in ascii_terms:
            t = term.strip("-_.")
            if len(t) >= 2 and t.lower() not in {"the", "and", "for", "with", "this", "that", "from"}:
                if t not in seen:
                    seen.add(t)
                    extracted.append(t)

        # 2. Morphological analysis with SudachiPy if available
        if tokenizer is not None:
            from sudachipy import SplitMode
            morphemes = tokenizer.tokenize(text, self._split_mode or SplitMode.C)
            for m in morphemes:
                pos = m.part_of_speech()
                # Extract proper nouns (固有名詞), general nouns with length >= 2
                surface = m.surface().strip()
                if len(surface) < 2:
                    continue
                if pos[0] == "名詞":
                    if pos[1] in ("固有名詞", "一般") and pos[2] not in ("助数詞", "代名詞"):
                        if surface not in seen and not surface.isdigit():
                            seen.add(surface)
                            extracted.append(surface)
        else:
            # Fallback simple Japanese regex: Kanji/Katakana compounds
            jp_terms = re.findall(r"[\u4e00-\u9fff\u30a0-\u30ff]{2,15}", text)
            for term in jp_terms:
                if term not in seen:
                    seen.add(term)
                    extracted.append(term)

        return extracted[:max_keywords]

    def set_instant_hotwords(self, keywords: List[str]) -> None:
        """Set dynamic hotwords for the current meeting."""
        self.instant_hotwords = [k.strip() for k in keywords if k.strip()]

    def generate_hotwords_file(self, output_path: Path, score: float = 1.5) -> Path:
        """
        Generate sherpa-onnx compatible hotwords file.
        Format: word / score
        """
        all_words: Set[str] = set(self.instant_hotwords)
        # Add top static terms
        all_words.update(self.static_terms)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for word in sorted(all_words):
                # Clean word
                w = word.strip()
                if w and len(w) >= 2:
                    f.write(f"{w} : {score}\n")

        return output_path

