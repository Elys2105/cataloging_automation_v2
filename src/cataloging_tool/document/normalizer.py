from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class NormalizationRule:
    wrong: str
    correct: str
    scope: str = "all"


def fold_vietnamese(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "")
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", without_marks.replace("đ", "d").replace("Đ", "D").casefold()).strip()


_CANONICAL_OCR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            # Tolerate the recurring OCR forms ``KT LUN``, ``KET LUAN``,
            # ``THƯNG VU`` and ``ĐNG Y/PANG UY`` without spell-checking
            # arbitrary prose.  This is a fixed institutional heading only.
            r"\bK(?:Ế|E)?T?\s+L(?:U|Ư)(?:Ậ|A)?N\s+"
            r"(?:C(?:Ủ|U)A\s+)?BAN\s+"
            r"TH(?:ƯỜ|ƯƠ|UƠ|UO|Ư|U)?NG\s+V(?:Ụ|U)\s+"
            r"(?:Đ|D|P)?(?:Ả|A)?NG\s+(?:Ủ|U)?Y\b",
            re.IGNORECASE,
        ),
        "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY",
    ),
    (
        re.compile(
            r"\bBAN\s+TH(?:ƯỜ|Ư|UO|UƠ|ƯƠ|U)NG\s+V(?:Ụ|U)\s+"
            r"(?:Đ|D|P)(?:Ả|A)NG\s+(?:Ủ|U)Y\b",
            re.IGNORECASE,
        ),
        "BAN THƯỜNG VỤ ĐẢNG ỦY",
    ),
)


class VietnameseNormalizer:
    def __init__(self, rules_path: Path | None = None) -> None:
        self.rules = self._load_rules(rules_path) if rules_path else []

    @staticmethod
    def _load_rules(path: Path) -> list[NormalizationRule]:
        if not path.exists():
            return []
        rules: list[NormalizationRule] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = raw.split("\t")
            if len(parts) >= 2:
                rules.append(
                    NormalizationRule(
                        wrong=parts[0].strip(),
                        correct=parts[1].strip(),
                        scope=parts[2].strip() if len(parts) > 2 else "all",
                    )
                )
        return rules

    def normalize_text(self, value: str, scope: str = "all") -> str:
        text = unicodedata.normalize("NFC", html.unescape(value or ""))
        text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
        # Sửa các tiêu đề chính trị cố định bằng pattern bảo thủ. Pattern cho
        # phép mất dấu và nhầm D/P nhưng không áp dụng spell-check rộng lên tên
        # người hoặc nội dung tự do, tránh sửa sai dữ liệu hợp lệ.
        for pattern, canonical in _CANONICAL_OCR_PATTERNS:
            text = pattern.sub(canonical, text)
        for rule in self.rules:
            if rule.scope not in {"all", scope}:
                continue
            if len(rule.wrong.strip()) < 3 and scope != "symbol":
                continue
            pattern = r"(?<![\wÀ-ỹ])" + re.escape(rule.wrong).replace(r"\ ", r"\s+") + r"(?![\wÀ-ỹ])"
            text = re.sub(pattern, rule.correct, text, flags=re.IGNORECASE)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text)
        return text.strip()

    def normalize_symbol(self, value: str) -> str:
        symbol = self.normalize_text(value, scope="symbol").upper()
        symbol = symbol.replace("–", "-").replace("—", "-")
        symbol = re.sub(r"\s*/\s*", "/", symbol)
        symbol = re.sub(r"\s*-\s*", "-", symbol)
        symbol = re.sub(r"(^|/)D\s*U\b", r"\1ĐU", symbol)
        symbol = re.sub(r"(^|/)T[ƯU]\b", r"\1TW", symbol)
        return symbol.strip(" -/.,;:")

    @staticmethod
    def clean_abstract(value: str) -> str:
        text = re.sub(r"\s+", " ", value or "").strip()
        text = re.sub(r"\s+([,.;:])", r"\1", text)
        text = re.sub(r"\(\s+", "(", text)
        text = re.sub(r"\s+\)", ")", text)
        return text.strip(" -–—_=*.;: ")
