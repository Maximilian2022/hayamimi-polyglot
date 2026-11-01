"""
Hayamimi For Business - Business Dictionary & Instant Hotwords Engine.
Uses SudachiPy (Apache-2.0) for morphological analysis, phonetic matching and entity extraction.
Runs offline with no external network requests during runtime.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Set, Tuple


_ASCII_RULE_RE = re.compile(r"^[A-Za-z0-9/&\-\._]+$")
_KATAKANA_ONLY_RE = re.compile(r"^[\u30a0-\u30ffー]+$")
_JP_CHAR_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]")


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein distance between two strings using dynamic programming."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


# High-frequency common words that should never be overridden by fuzzy phonetic matching
COMMON_STOPWORDS: Set[str] = {
    "会社", "今日", "今回", "相手", "時間", "会議", "問題", "結果", "方法", "理由",
    "計画", "予定", "状況", "確認", "相談", "質問", "回答", "作業", "業務", "担当",
    "対応", "検討", "報告", "連絡", "提出", "実施", "決定", "開始", "終了", "変更",
    "参加", "共有", "作成", "登録", "設定", "表示", "利用", "使用", "管理", "運用",
    "開発", "資料", "進捗", "課題", "目標", "対策", "方針", "内容", "詳細", "全体",
    "これ", "それ", "あれ", "どれ", "ここ", "そこ", "あそこ", "どこ", "だれ", "なに",
    "テスト", "システム", "データ", "モデル", "サービス", "プロジェクト", "ミーティング",
}


class BusinessDictionary:
    """
    Business dictionary and phonetic post-processing engine.
    Applies exact, boundary, regex, and SudachiPy morphological phonetic corrections.
    """

    def __init__(self, dict_dir: Path | None = None):
        if dict_dir is None:
            dict_dir = Path(__file__).resolve().parent.parent / "dicts"
        self.dict_dir = dict_dir
        self.extensions_dir = dict_dir / "extensions"
        self.extensions_dir.mkdir(parents=True, exist_ok=True)

        self.static_terms: Set[str] = set()
        self.static_replacements: Dict[str, str] = {}
        self._compiled_static_regex: List[Tuple[Pattern[str], str]] = []
        self._literal_static_replacements: List[Tuple[str, str]] = []

        self.instant_hotwords: List[str] = []
        self.instant_hotword_readings: Dict[str, str] = {}
        self._instant_ascii_patterns: List[Tuple[Pattern[str], str]] = []

        self._tokenizer = None
        self._split_mode = None
        self._lock = threading.Lock()

        self._load_static_dicts()
        self._load_replacement_rules()
        self._load_extension_dicts()
        self._compile_replacement_patterns()

    def _get_tokenizer(self):
        """Thread-safe lazy initialization of SudachiPy tokenizer."""
        if self._tokenizer is None:
            with self._lock:
                if self._tokenizer is None:
                    try:
                        from sudachipy import dictionary, SplitMode
                        dict_instance = dictionary.Dictionary(dict="full")
                        tok_fn = getattr(dict_instance, "tokenizer", None)
                        self._tokenizer = tok_fn() if tok_fn is not None else dict_instance.create()
                        self._split_mode = SplitMode.C
                    except Exception:
                        try:
                            from sudachipy import dictionary, SplitMode
                            dict_instance = dictionary.Dictionary()
                            tok_fn = getattr(dict_instance, "tokenizer", None)
                            self._tokenizer = tok_fn() if tok_fn is not None else dict_instance.create()
                            self._split_mode = SplitMode.C
                        except Exception:
                            self._tokenizer = None
                            self._split_mode = None
        return self._tokenizer

    def warmup(self) -> None:
        """Pre-initialize the morphological analyzer to avoid first-utterance latency."""
        tok = self._get_tokenizer()
        if tok is not None:
            with self._lock:
                try:
                    from sudachipy import SplitMode
                    tok.tokenize("初期化", self._split_mode or SplitMode.C)
                except Exception:
                    pass

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

    def _load_replacement_rules(self) -> None:
        """Load mapping table for misrecognition & acronym normalization."""
        p = self.dict_dir / "term_replacements.txt"
        if p.is_file():
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "\t" in line:
                        parts = line.split("\t", 1)
                        misheard = parts[0].strip()
                        correct = parts[1].strip()
                        if misheard and correct and misheard != correct:
                            self.static_replacements[misheard] = correct

    def _load_extension_dicts(self) -> None:
        """Load optional extension dictionaries from dicts/extensions/."""
        if not self.extensions_dir.is_dir():
            return
        for ext_file in self.extensions_dir.glob("*.txt"):
            with open(ext_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        if "\t" in line:
                            parts = line.split("\t", 1)
                            k, v = parts[0].strip(), parts[1].strip()
                            if k and v and k != v:
                                self.static_replacements[k] = v
                        else:
                            self.static_terms.add(line)

    def _compile_replacement_patterns(self) -> None:
        """Pre-compile boundary-aware patterns so partial matches inside words never occur."""
        self._compiled_static_regex.clear()
        self._literal_static_replacements.clear()

        # Sort longer keys first to prevent shorter patterns from shadowing compound rules
        sorted_items = sorted(self.static_replacements.items(), key=lambda kv: len(kv[0]), reverse=True)
        for misheard, correct in sorted_items:
            if _ASCII_RULE_RE.match(misheard):
                # Enforce alphanumeric boundaries (e.g. 'nda' will not match inside 'agenda')
                pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(misheard)}(?![A-Za-z0-9])")
                self._compiled_static_regex.append((pat, correct))
            elif _KATAKANA_ONLY_RE.match(misheard) and len(misheard) <= 4:
                # Short katakana terms require katakana boundaries (e.g. 'サース' won't match 'リソース')
                pat = re.compile(rf"(?<![\u30a0-\u30ffー]){re.escape(misheard)}(?![\u30a0-\u30ffー])")
                self._compiled_static_regex.append((pat, correct))
            else:
                self._literal_static_replacements.append((misheard, correct))

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
            if len(t) >= 2 and not t.isdigit() and t.lower() not in {
                "the", "and", "for", "with", "this", "that", "from", "have", "will", "are", "was", "not"
            }:
                if t not in seen:
                    seen.add(t)
                    extracted.append(t)

        # 2. Morphological analysis with SudachiPy if available
        if tokenizer is not None:
            from sudachipy import SplitMode
            with self._lock:
                morphemes = tokenizer.tokenize(text, self._split_mode or SplitMode.C)
            for m in morphemes:
                pos = m.part_of_speech()
                surface = m.surface().strip()
                if len(surface) < 2 or surface in COMMON_STOPWORDS or surface.isdigit():
                    continue
                if pos[0] == "名詞":
                    # Only extract proper nouns or Katakana technical terms to avoid overriding common kanji words
                    is_proper = pos[1] == "固有名詞"
                    is_katakana_term = bool(_KATAKANA_ONLY_RE.match(surface))
                    if (is_proper or is_katakana_term) and pos[2] not in ("助数詞", "代名詞"):
                        if surface not in seen:
                            seen.add(surface)
                            extracted.append(surface)
        else:
            # Fallback simple Japanese regex: Katakana compounds
            jp_terms = re.findall(r"[\u30a0-\u30ffー]{2,15}", text)
            for term in jp_terms:
                if term not in seen and term not in COMMON_STOPWORDS:
                    seen.add(term)
                    extracted.append(term)

        return extracted[:max_keywords]

    def set_instant_hotwords(self, keywords: List[str]) -> None:
        """
        Set dynamic hotwords for the current meeting and precompute their Katakana readings
        and compiled regex patterns for real-time post-processing.
        """
        cleaned = [k.strip() for k in keywords if k.strip() and k.strip() not in COMMON_STOPWORDS]
        self.instant_hotwords = cleaned
        self.instant_hotword_readings.clear()
        self._instant_ascii_patterns.clear()

        for hw in self.instant_hotwords:
            if re.match(r"^[A-Za-z0-9_\-\.]+$", hw):
                pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(hw)}(?![A-Za-z0-9])", re.IGNORECASE)
                self._instant_ascii_patterns.append((pat, hw))

        tokenizer = self._get_tokenizer()
        if tokenizer is not None:
            from sudachipy import SplitMode
            with self._lock:
                for hw in self.instant_hotwords:
                    try:
                        morphemes = tokenizer.tokenize(hw, self._split_mode or SplitMode.C)
                        reading = "".join([m.reading_form() for m in morphemes])
                        if reading and len(reading) >= 2:
                            self.instant_hotword_readings[hw] = reading
                    except Exception:
                        pass

    def clear_instant_hotwords(self) -> None:
        """Clear dynamic hotwords and cached readings from memory."""
        self.instant_hotwords.clear()
        self.instant_hotword_readings.clear()
        self._instant_ascii_patterns.clear()

    def generate_hotwords_file(self, output_path: Path, score: float = 1.5) -> Path:
        """
        Generate sherpa-onnx compatible hotwords file.
        Format: word :score
        """
        all_words: Set[str] = set(self.instant_hotwords)
        all_words.update(self.static_terms)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for word in sorted(all_words):
                w = word.strip()
                if w and len(w) >= 2:
                    f.write(f"{w} :{score}\n")

        return output_path

    def _find_phonetic_match(self, surface: str, reading: str, pos: Tuple[str, ...]) -> Optional[str]:
        """
        Find closest phonetic match among instant hotwords for misrecognized Katakana words.
        Example: Speech recognition outputs 'テッチリ', matches hotword 'テック'.
        """
        if not reading or len(reading) < 2:
            return None
        if surface in COMMON_STOPWORDS:
            return None
        if pos[0] != "名詞":
            return None
        # Only apply fuzzy phonetic replacement to Katakana tokens so established Kanji words (e.g. 開発) are never corrupted
        if not _KATAKANA_ONLY_RE.match(surface):
            return None

        best_match: Optional[str] = None
        best_score = 999.0

        for hw, hw_reading in self.instant_hotword_readings.items():
            if hw == surface or hw_reading == reading:
                continue

            dist = _levenshtein(reading, hw_reading)
            hw_len = len(hw_reading)
            rd_len = len(reading)
            max_len = max(hw_len, rd_len)

            # Common prefix check (e.g. 'テック' and 'テッチリ' share 'テッ')
            common_prefix_len = 0
            for c1, c2 in zip(reading, hw_reading):
                if c1 == c2:
                    common_prefix_len += 1
                else:
                    break

            # Rule 1: Short hotwords (length <= 3) e.g., テック (3) vs テッチリ (4)
            if hw_len <= 3:
                if dist <= 2 and common_prefix_len >= 2:
                    score = dist / max_len
                    if score < best_score:
                        best_score = score
                        best_match = hw
            # Rule 2: Longer hotwords (length >= 4) e.g., コンセンサス vs コンセンス
            else:
                similarity = 1.0 - (dist / max_len)
                if dist <= 2 and similarity >= 0.55 and common_prefix_len >= 2:
                    score = dist / max_len
                    if score < best_score:
                        best_score = score
                        best_match = hw

        return best_match

    def apply_replacements(self, text: str) -> str:
        """
        Apply post-decoding corrections:
        1. Pre-compiled boundary & literal replacements from term_replacements.txt
        2. English acronym case normalization from Instant Hotwords
        3. SudachiPy morphological phonetic matching (for texts containing Japanese characters)
        """
        if not text:
            return ""

        res = text

        # ----------------------------------------------------------------------
        # Phase 1: Static Term Replacements (Literal + Boundary-aware Regex)
        # ----------------------------------------------------------------------
        for misheard, correct in self._literal_static_replacements:
            if misheard in res:
                res = res.replace(misheard, correct)

        for pat, correct in self._compiled_static_regex:
            res = pat.sub(correct, res)

        # ----------------------------------------------------------------------
        # Phase 2: Acronym Case Normalization (Word boundaries)
        # ----------------------------------------------------------------------
        for pat, hw in self._instant_ascii_patterns:
            res = pat.sub(hw, res)

        # ----------------------------------------------------------------------
        # Phase 3: SudachiPy Morphological & Phonetic Correction (Japanese only)
        # ----------------------------------------------------------------------
        if not _JP_CHAR_RE.search(res):
            return res

        tokenizer = self._get_tokenizer()
        if tokenizer is not None and (self.instant_hotword_readings or self.static_terms):
            from sudachipy import SplitMode
            try:
                with self._lock:
                    morphemes = tokenizer.tokenize(res, self._split_mode or SplitMode.C)
                    corrected_tokens: List[str] = []

                    for m in morphemes:
                        surf = m.surface()
                        pos = m.part_of_speech()
                        reading = m.reading_form()
                        norm = m.normalized_form()

                        # 1. Sudachi built-in normalization for standalone Latin acronyms
                        if surf.lower() in ("kpi", "dx", "saas", "arr", "mrr", "poc", "api", "aws", "gcp"):
                            corrected_tokens.append(norm)
                            continue

                        # 2. Check phonetic match against Instant Hotwords
                        if self.instant_hotword_readings:
                            phonetic_replacement = self._find_phonetic_match(surf, reading, pos)
                            if phonetic_replacement:
                                corrected_tokens.append(phonetic_replacement)
                                continue

                        corrected_tokens.append(surf)

                res = "".join(corrected_tokens)
            except Exception:
                pass

        return res

    # --------------------------------------------------------------------------
    # Extension Dictionaries Catalog & Download Management
    # --------------------------------------------------------------------------
    def get_extension_catalog(self) -> List[Dict[str, str]]:
        """
        Return the catalog of available online-optional extension dictionaries.
        These are open-data, commercial-safe domain dictionaries.
        """
        return [
            {
                "id": "medical_pharma",
                "name": "医療・製薬・ライフサイエンス専門辞書",
                "description": "厚生労働省MEDIS標準病名マスター・万病辞書由来。疾患名、医薬品一般名、治験用語を収録。",
                "filename": "medical_pharma.txt",
                "installed": (self.extensions_dir / "medical_pharma.txt").is_file(),
            },
            {
                "id": "legal_compliance",
                "name": "法務・知財・行政・コンプライアンス辞書",
                "description": "e-Gov法令用語、特許・商標、官公庁行政用語、企業コンプライアンス用語を収録。",
                "filename": "legal_compliance.txt",
                "installed": (self.extensions_dir / "legal_compliance.txt").is_file(),
            },
            {
                "id": "edinet_full",
                "name": "東証全上場企業 EDINET 辞書（約4,000社）",
                "description": "金融庁EDINET開示のプライム・スタンダード・グロース上場企業の正式名称・略称。",
                "filename": "edinet_full.txt",
                "installed": (self.extensions_dir / "edinet_full.txt").is_file(),
            },
            {
                "id": "science_engineering",
                "name": "科学技術・工学用語辞書",
                "description": "情報通信、半導体、機械工学、材料科学、バイオ工学の学術・技術用語。",
                "filename": "science_engineering.txt",
                "installed": (self.extensions_dir / "science_engineering.txt").is_file(),
            },
        ]

    def is_extension_installed(self, extension_id: str) -> bool:
        """Check if an extension dictionary is installed."""
        for item in self.get_extension_catalog():
            if item["id"] == extension_id:
                return (self.extensions_dir / item["filename"]).is_file()
        return False
