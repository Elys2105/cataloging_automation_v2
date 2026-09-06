from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping


_NUMBER_CONFUSIONS = str.maketrans(
    {
        "O": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "L": "1",
        "Z": "2",
        "E": "3",
        "A": "4",
        "S": "5",
        "G": "6",
        "T": "7",
        "B": "8",
    }
)

# The number token is deliberately tolerant because the archive contains many
# handwritten corrections over a printed number.  Tolerance is limited to the
# token before the dash; arbitrary prose is never converted to digits.
_HEADER_NUMBER_SYMBOL_RE = re.compile(
    r"(?:^|\b)(?:S[oố0]\s*[:：]?\s*)?"
    r"(?P<number>[0-9OQDILSZGEATB|]{1,7})\s*[-–—]\s*"
    r"(?P<symbol>[A-ZĐÂĂÊÔƠƯ0-9]{1,10}(?:\s*[-–—]\s*[A-ZĐÂĂÊÔƠƯ0-9]{1,8})?"
    r"(?:\s*/\s*[A-ZĐÂĂÊÔƠƯ0-9]{1,15})+)",
    re.IGNORECASE,
)

_SYMBOL_ONLY_RE = re.compile(
    r"(?P<symbol>[A-ZĐÂĂÊÔƠƯ0-9]{1,10}(?:\s*[-–—]\s*[A-ZĐÂĂÊÔƠƯ0-9]{1,8})?"
    r"(?:\s*/\s*[A-ZĐÂĂÊÔƠƯ0-9]{1,15})+)",
    re.IGNORECASE,
)

_TITLE_START_RE = re.compile(
    r"^(?:V(?:ề|ê|e)\b|V\s*/\s*v(?:ề|e)?\b|V\s+việc\b|"
    r"Báo\s+cáo\s+về\b)",
    re.IGNORECASE,
)

_INLINE_TITLE_START_RE = re.compile(
    r"\b(?:V(?:ề|ê|e)\b|V\s*/\s*v(?:ề|e)?\b|Báo\s+cáo\s+về\b)",
    re.IGNORECASE,
)

_SEPARATOR_RE = re.compile(r"^\s*(?:[-–—_=*]\s*){3,}$")

# A Công văn abstract is the italic block below its number.  These are reliable
# starts of the body or recipient block when Kính gửi was missed by OCR.
_CV_BODY_BOUNDARY_RE = re.compile(
    r"\s+(?=(?:"
    r"Kính\s+gửi|Kinh\s+gui|Đồng\s+kính\s+gửi|Dong\s+kinh\s+gui|"
    r"Để\s+có\s+cơ\s+sở|De\s+co\s+co\s+so|"
    r"Căn\s+cứ|Can\s+cu|"
    r"Thời\s+gian\s+qua|Thoi\s+gian\s+qua|"
    r"Nhằm\s+|Nham\s+|Tiếp\s+nhận|Tiep\s+nhan|Rất\s+mong|Rat\s+mong|"
    r"Nay\s+Ban|Qua\s+đó|Qua\s+do|"
    r"Trên\s+cơ\s+sở|Tren\s+co\s+so|"
    r"\d+[.)]\s+|[IVX]+[.)]\s+|Nơi\s+nhận|Noi\s+nhan"
    r")\b)",
    re.IGNORECASE,
)

_CV_BODY_LINE_RE = re.compile(
    r"^(?:"
    r"Kính\s+gửi|Kinh\s+gui|Đồng\s+kính\s+gửi|Dong\s+kinh\s+gui|"
    r"Để\s+có\s+cơ\s+sở|De\s+co\s+co\s+so|"
    r"Căn\s+cứ|Can\s+cu|"
    r"Thời\s+gian\s+qua|Thoi\s+gian\s+qua|"
    r"Nhằm\s+|Nham\s+|Tiếp\s+nhận|Tiep\s+nhan|Rất\s+mong|Rat\s+mong|"
    r"Nay\s+Ban|Trên\s+cơ\s+sở|Tren\s+co\s+so|"
    r"Nơi\s+nhận|Noi\s+nhan|"
    r"\d+[.)]\s+|[IVX]+[.)]\s+"
    r")",
    re.IGNORECASE,
)

_CITED_INSTRUMENT_LINE_RE = re.compile(
    r"^(?:Thực\s+hiện|Thuc\s+hien|Thc\s+hin)\s+"
    r"(?:Kế\s+hoạch|Ke\s+hoach|Công\s+văn|Cong\s+van|"
    r"Quyết\s+định|Quyet\s+dinh|Nghị\s+quyết|Nghi\s+quyet|"
    r"Chỉ\s+thị|Chi\s+thi|Hướng\s+dẫn|Huong\s+dan|"
    r"Chương\s+trình|Chuong\s+trinh)\b",
    re.IGNORECASE,
)

_INSTITUTION_BODY_LINE_RE = re.compile(
    r"^(?:Đảng\s+ủy|Dang\s+uy|Ban\s+Thường\s+vụ|Ban\s+Thuong\s+vu|"
    r"Thường\s+trực|Thuong\s+truc).{0,80}\b"
    r"(?:có|co|đã|da|nhận|nhan|đề\s+nghị|de\s+nghi|ban\s+hành|ban\s+hanh|"
    r"thông\s+tin|thong\s+tin|yêu\s+cầu|yeu\s+cau|"
    r"thống\s+nhất|thong\s+nhat)\b",
    re.IGNORECASE,
)

_HEADER_NOISE_PREFIXES = (
    "dang cong san viet nam",
    "dang bo thanh pho",
    "dang uy thanh pho",
    "dang uy phuong",
    "quan uy quan",
    "dang bo quan",
)


@dataclass(frozen=True, slots=True)
class HeaderNumberSymbol:
    number: str
    symbol: str
    line: str
    index: int
    score: float


@dataclass(frozen=True, slots=True)
class CongVanTitle:
    value: str
    strong_boundary: bool
    number: str = ""
    symbol: str = ""
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class CanonicalDocumentHeader:
    text: str
    number: str = ""
    symbol: str = ""
    number_support: int = 0
    number_score: float = 0.0
    number_candidate_count: int = 0
    title_score: float = 0.0


def fold_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "")
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return re.sub(
        r"\s+",
        " ",
        without_marks.replace("đ", "d").replace("Đ", "D").casefold(),
    ).strip()


def clean_lines(raw_text: str) -> list[str]:
    lines: list[str] = []
    for raw in (raw_text or "").replace("\r", "\n").splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" \t")
        if not line:
            continue
        if _SEPARATOR_RE.fullmatch(line):
            lines.append("-----")
        else:
            lines.append(line)
    return lines


def normalize_ocr_number(token: str) -> str:
    compact = re.sub(r"[^0-9A-Z|]", "", (token or "").upper())
    if not compact:
        return ""
    compact = compact.replace("|", "1").translate(_NUMBER_CONFUSIONS)
    return compact if re.fullmatch(r"\d{1,6}", compact) else ""


def _normalize_cv_header_number(token: str) -> str:
    """Normalize OCR glyph confusions without guessing a numeric prefix.

    A leading OCR stroke may be attached to the handwritten number, but a
    single reading is not enough evidence to delete digits.  Prefix removal is
    performed later only when an independent OCR/crop candidate explicitly
    confirms the suffix.
    """
    return normalize_ocr_number(token)


def normalize_header_symbol(
    value: str,
    *,
    known_codes: Iterable[str] = (),
    issuer_text: str = "",
) -> str:
    symbol = unicodedata.normalize("NFC", value or "").upper()
    symbol = symbol.replace("–", "-").replace("—", "-")
    symbol = re.sub(r"\s*/\s*", "/", symbol)
    symbol = re.sub(r"\s*-\s*", "-", symbol)
    symbol = symbol.strip(" -/.,;:|_")

    codes = {str(code).upper().replace("Đ", "D") for code in known_codes}
    # OCR commonly absorbs the S/V printed before the dash into the symbol:
    # S-CV/ĐU, V-CV/ĐU, I-CV/ĐU. Remove only a one-character prefix when the
    # following code is a known document code, so valid CV/UBKTTU remains intact.
    prefixed = re.fullmatch(r"[A-Z0-9]-([A-ZĐ0-9]{1,8}/[A-ZĐ0-9/]{1,30})", symbol)
    if prefixed:
        tail = prefixed.group(1)
        tail_code = tail.split("/", 1)[0].replace("Đ", "D")
        if not codes or tail_code in codes:
            symbol = tail

    symbol = re.sub(r"(^|/)D\s*U\b", r"\1ĐU", symbol)
    symbol = re.sub(r"(^|/)T[ƯU]\b", r"\1TW", symbol)

    issuer_key = fold_text(issuer_text)
    # For a local Đảng ủy phường issuer, CV/U or CV/DU is a common loss of
    # the Đ glyph in the office suffix.  This rule is organizational, not tied
    # to one ward or record.
    if "dang uy phuong " in issuer_key and symbol.startswith("CV/"):
        suffix = symbol.split("/", 1)[1]
        folded_suffix = (
            suffix.replace("Đ", "D")
            .replace("Ư", "U")
            .replace("0", "O")
            .replace("|", "I")
        )
        compact_suffix = re.sub(r"[^A-Z0-9]", "", folded_suffix)
        # The own office code on these Công văn headers is CV/ĐU.  Small OCR
        # debris from the handwritten number or issuer line commonly produces
        # CV/U, CV/DU, CV/PDU or CV/PĐU.  Repair only short near-ĐU suffixes;
        # longer valid offices such as CV/BTCTU and CV/UBKTTU are preserved.
        near_du = (
            compact_suffix in {"U", "DU", "DƯ", "PDU", "PĐU", "DDU", "D0", "PU"}
            or (len(compact_suffix) <= 4 and compact_suffix.endswith("DU"))
        )
        if near_du:
            symbol = "CV/ĐU"

    return symbol.strip(" -/.,;:|_")


def _header_candidate_score(
    lines: list[str],
    index: int,
    line: str,
    symbol: str,
    *,
    expected_code: str = "",
    known_codes: Iterable[str] = (),
) -> float:
    folded = fold_text(line)
    score = 0.0
    if index < 7:
        score += 7.0
    elif index < 14:
        score += 4.0
    elif index < 25:
        score += 1.5
    else:
        score -= 1.0

    if re.match(r"^\s*S[oố0]\s*[:：]?", line, re.IGNORECASE):
        score += 8.0
    if folded.startswith("so "):
        score += 2.0

    code = symbol.split("/", 1)[0].replace("Đ", "D") if symbol else ""
    known = {str(item).upper().replace("Đ", "D") for item in known_codes}
    if code in known:
        score += 1.5
    if expected_code:
        if code == expected_code.upper().replace("Đ", "D"):
            score += 8.0
        else:
            score -= 7.0

    first_recipient = next(
        (i for i, item in enumerate(lines[:60]) if fold_text(item).startswith("kinh gui")),
        -1,
    )
    if first_recipient >= 0:
        score += 4.0 if index < first_recipient else -9.0

    next_lines = lines[index + 1 : index + 8]
    if any(_TITLE_START_RE.match(item.strip()) for item in next_lines):
        score += 5.0
    if any(fold_text(item).startswith("kinh gui") for item in next_lines):
        score += 2.0

    # Cited instruments in the body are never the document's own header.
    if re.search(
        r"\b(?:thuc hien|can cu|theo|cong van|ke hoach|quyet dinh|"
        r"nghi quyet|chi thi|huong dan|ket luan)\s+(?:so\s+)?",
        folded,
    ) and not folded.startswith("so "):
        score -= 10.0
    if "ngay" in folded and len(folded.split()) > 7:
        score -= 2.0
    return score


def extract_number_symbol_candidates(
    raw_text: str,
    *,
    expected_code: str = "",
    known_codes: Iterable[str] = (),
) -> list[HeaderNumberSymbol]:
    lines = clean_lines(raw_text)
    joined_issuer = "\n".join(lines[:16])
    result: list[HeaderNumberSymbol] = []
    for index, line in enumerate(lines[:100]):
        normalized = re.sub(r"\bB\s+C\s*/", "BC/", line, flags=re.IGNORECASE)
        for match in _HEADER_NUMBER_SYMBOL_RE.finditer(normalized):
            number = (
                _normalize_cv_header_number(match.group("number"))
                if expected_code.upper().replace("Đ", "D") == "CV"
                else normalize_ocr_number(match.group("number"))
            )
            symbol = normalize_header_symbol(
                match.group("symbol"), known_codes=known_codes, issuer_text=joined_issuer
            )
            if not number or not symbol:
                continue
            score = _header_candidate_score(
                lines,
                index,
                line,
                symbol,
                expected_code=expected_code,
                known_codes=known_codes,
            )
            result.append(HeaderNumberSymbol(number, symbol, line, index, score))
    result.sort(key=lambda item: (item.score, -item.index), reverse=True)
    return result


def best_number_symbol(
    raw_text: str,
    *,
    expected_code: str = "",
    known_codes: Iterable[str] = (),
) -> HeaderNumberSymbol | None:
    candidates = extract_number_symbol_candidates(
        raw_text, expected_code=expected_code, known_codes=known_codes
    )
    return candidates[0] if candidates else None


def infer_header_symbol(
    raw_text: str,
    *,
    expected_code: str = "",
    known_codes: Iterable[str] = (),
) -> str:
    best = best_number_symbol(
        raw_text, expected_code=expected_code, known_codes=known_codes
    )
    if best:
        return best.symbol
    lines = clean_lines(raw_text)
    issuer = "\n".join(lines[:16])
    expected = expected_code.upper().replace("Đ", "D")
    for line in lines[:18]:
        if not re.match(r"^\s*S[oố0]\b", line, re.IGNORECASE):
            continue
        for match in _SYMBOL_ONLY_RE.finditer(line):
            symbol = normalize_header_symbol(
                match.group("symbol"), known_codes=known_codes, issuer_text=issuer
            )
            code = symbol.split("/", 1)[0].replace("Đ", "D") if symbol else ""
            if symbol and (not expected or code == expected):
                return symbol
    return ""


def _is_header_noise(line: str) -> bool:
    key = fold_text(line)
    if not key:
        return True
    if key in {"khan", "thuong khan", "hoa toc"}:
        return True
    if any(key.startswith(prefix) for prefix in _HEADER_NOISE_PREFIXES):
        return True
    if re.fullmatch(
        r"\(?\s*(?:[^,]{1,60},\s*)?ngay\s+\d{1,2}\s+thang\s+\d{1,2}\s+nam\s+20\d{2}.*",
        key,
    ):
        return True
    return False


def _strip_noise_before_title(line: str) -> str:
    text = re.sub(r"\s+", " ", line or "").strip(" |:_-–—")
    matches = list(_INLINE_TITLE_START_RE.finditer(text))
    if not matches:
        return text

    # Prefer a later title start only when the preceding text is recogniser/UI
    # debris. This removes forms such as ``ve 3 mm Vô việc ...`` without
    # deleting legitimate titles containing another ordinary ``về`` later on.
    chosen = matches[0]
    for match in matches[1:]:
        prefix = text[: match.start()].strip(" |:_-–—")
        folded_prefix = fold_text(prefix)
        looks_like_debris = (
            len(prefix) <= 36
            and (
                bool(re.search(r"[|^ˆ~`´]", prefix))
                or bool(re.search(r"\b(?:mm+|nn+|vide|dqqd|nd|vl)\b", folded_prefix))
                or sum(char.isdigit() for char in prefix) >= 1
                or not re.search(r"[a-zà-ỹ]{4,}", prefix, re.IGNORECASE)
            )
        )
        if looks_like_debris:
            chosen = match
    prefix = text[: chosen.start()].strip()
    if chosen.start() <= 32 and (
        not prefix
        or not re.search(r"[a-zà-ỹ]{3,}", prefix, re.IGNORECASE)
        or re.search(r"\b(?:mm+|nn+|vide|dqqd|nd|vl)\b", fold_text(prefix))
    ):
        text = text[chosen.start() :]
    return text.strip(" |:_-–—")



_CV_UI_LEAK_TOKENS = (
    "trich yeu noi dung",
    "tap luu cong van",
    "van di dang uy nam",
    "so thu tu van ban",
    "ma dinh danh tai lieu",
    "ten the loai van ban",
    "ky hieu van ban",
)

_CV_RECIPIENT_STARTS = (
    "ban chi huy",
    "ban to chuc",
    "ban xay dung dang",
    "dang uy xa",
    "dang uy phuong",
    "uy ban nhan dan",
    "cong an phuong",
    "benh vien",
    "trung tam",
    "cac dong chi",
    "dong chi",
)

_CV_DATE_CONTINUATION_TAILS = (
    "quy dinh",
    "quyet dinh",
    "cac quy dinh, quyet dinh",
    "dot",
    "nghi quyet",
    "ke hoach",
    "chuong trinh",
    "moi du",
    "trien khai",
    "viec trien khai",
    "thuc hien",
    "so",
)


def _looks_like_kinh_token(token: str) -> bool:
    folded = fold_text(token)
    if folded in {"kinh", "klnh", "k1nh", "klnh"}:
        return True
    return len(folded) in {4, 5} and difflib.SequenceMatcher(
        None, folded.replace("1", "i").replace("l", "i"), "kinh"
    ).ratio() >= 0.78


def _cv_inline_boundary_index(value: str) -> int | None:
    """Return the first hard boundary after a Công văn title.

    OCR often damages only ``gửi`` (for example ``Kính oxrr``), therefore
    requiring the exact phrase ``Kính gửi`` is unsafe.  Seeing a Kính-like token
    after a valid title is sufficient to stop.  UI labels are also hard stops.
    """
    text = value or ""
    indexes: list[int] = []
    for match in re.finditer(r"[A-Za-zÀ-ỹĐđ0-9|]+", text):
        if _looks_like_kinh_token(match.group(0)):
            indexes.append(match.start())
            break
    folded = fold_text(text)
    for token in _CV_UI_LEAK_TOKENS:
        position = folded.find(token)
        if position >= 0:
            # Folded and original strings have different accent widths but the
            # surrounding ASCII words are stable. Locate the first word again.
            first = token.split()[0]
            raw = re.search(rf"\b{re.escape(first)}\w*\b", text, re.IGNORECASE)
            if raw:
                indexes.append(raw.start())
    for pattern in (
        r"\bĐể\s+có\s+cơ\s+sở\b",
        r"\bCăn\s+cứ\b",
        r"\bNơi\s+nhận\b",
        r"\b(?:J\s+)?văn\s+đi\s+Đảng\s+ủy\s+năm\b",
        r"\bTập\s+lưu\s+Công\s+văn\b",
        r"\bTrích\s+yếu\s+nội\s+dung\b",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            indexes.append(match.start())
    for date_match in re.finditer(r"\b(?:Ngày|Ngay)\s+\d{1,2}\b", text, re.IGNORECASE):
        prefix = fold_text(text[: date_match.start()]).rstrip(" ,;:-")
        if not _cv_previous_allows_date_continuation(prefix):
            indexes.append(date_match.start())

    positive = [index for index in indexes if index >= 8]
    return min(positive) if positive else None



def _cv_previous_allows_date_continuation(previous: str) -> bool:
    """Return True when a ``Ngày ...`` line clearly continues the italic title.

    Công văn titles in the archive frequently wrap after a cited instrument,
    for example ``... Quyết định số 1480-QĐ/TU / ngày 25/7/2023 ...``.  The
    older rule only accepted a previous line ending literally in ``quyết định``
    or ``số`` and therefore truncated these valid title lines.
    """
    key = fold_text(previous).rstrip(" ,;:")
    if any(key.endswith(tail) for tail in _CV_DATE_CONTINUATION_TAILS):
        return True
    return bool(
        re.search(
            r"(?:quy dinh|nghi quyet|ke hoach|cong van|chi thi|huong dan|"
            r"chuong trinh)\s+so\s+[0-9a-z]+(?:[-–—/][0-9a-z]+)+$",
            key,
        )
        or re.search(r"\bso\s+[0-9a-z]+(?:[-–—/][0-9a-z]+)+$", key)
    )


def cong_van_title_looks_truncated(value: str) -> bool:
    """Detect a likely incomplete Công văn title without inventing missing text.

    This is intentionally conservative.  It is used for OCR candidate ranking
    and retry decisions, not for generating content.
    """
    text = re.sub(r"\s+", " ", value or "").strip()
    if not text:
        return True
    key = fold_text(text).rstrip()
    words = key.split()
    if len(words) <= 3:
        return True
    if text.rstrip().endswith((",", ";", ":", "-", "–", "—", "/")):
        return True
    dangling = (
        "doi voi", "lien quan den", "cua", "theo", "va", "tai", "trong",
        "cho", "den", "ve", "de", "nham", "thuc hien", "trien khai",
        "bao cao viec trien khai", "quy trinh", "kiem tra", "giam sat",
        "cap uy", "chi bo", "dang vien",
    )
    if any(key.endswith(item) for item in dangling):
        return True
    # A four/five-word administrative opener is almost always only the first
    # wrapped line of the italic block (e.g. ``Về triển khai`` or
    # ``Về việc tăng cường``), not the complete abstract.
    if len(words) <= 5 and key.startswith(("ve viec ", "ve trien khai", "v/v ")):
        return True
    return False


def cong_van_title_is_safe_extension(longer: str, shorter: str) -> bool:
    """Return True when ``longer`` is a bounded title extension of ``shorter``.

    Used to preserve a manually corrected website abstract when a fresh OCR pass
    only recovers its prefix.  The extension must remain title-shaped and must
    not begin with a body/recipient opener.
    """
    long_clean = _clean_cv_title(longer)
    short_clean = _clean_cv_title(shorter)
    if not long_clean or not short_clean or long_clean == short_clean:
        return False
    if not cong_van_title_is_clean(long_clean) or not cong_van_title_is_clean(short_clean):
        return False
    if len(long_clean) > 420:
        return False

    long_tokens = re.findall(r"[a-z0-9]+", fold_text(long_clean))
    short_tokens = re.findall(r"[a-z0-9]+", fold_text(short_clean))
    if len(short_tokens) < 3 or len(long_tokens) < len(short_tokens) + 2:
        return False

    matcher = difflib.SequenceMatcher(None, long_tokens, short_tokens, autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size]
    if not blocks:
        return False
    first = blocks[0]
    matched = sum(block.size for block in blocks)
    prefix_aligned = first.a <= 1 and first.b <= 1
    short_coverage = matched / max(1, len(short_tokens))
    if not prefix_aligned or short_coverage < 0.84:
        return False

    # Estimate where the extension starts. Reject obvious body/recipient text.
    extension_tokens = long_tokens[len(short_tokens):]
    extension_key = " ".join(extension_tokens[:8])
    body_starts = (
        "kinh gui", "can cu", "nham", "tiep nhan", "rat mong", "noi nhan",
        "thoi gian qua", "nay ban", "tren co so",
    )
    if any(extension_key.startswith(item) for item in body_starts):
        return False
    if extension_key.startswith("thuc hien") and not cong_van_title_looks_truncated(short_clean):
        return False
    return True


def _cv_line_is_title_continuation(line: str, collected: list[str]) -> bool:
    if not collected:
        return False
    current = fold_text(line)
    previous = fold_text(collected[-1]).rstrip(" ,;:")
    if current.startswith("ngay ") and _cv_previous_allows_date_continuation(previous):
        return True
    if current.startswith(("dang uy phuong", "dang uy xa")) and any(
        previous.endswith(tail)
        for tail in (
            "bi thu", "pho bi thu", "thuong truc", "ban thuong vu",
            "cap uy", "dang uy", "dang bo", "cua dong chi bi thu",
        )
    ):
        return True
    if _starts_with_lowercase_letter(line):
        return True
    if collected[-1].rstrip().endswith((",", ";", ":", "-", "–", "—")):
        return True
    return False


def _cv_line_is_recipient_or_ui(line: str, collected: list[str]) -> bool:
    folded = fold_text(line)
    first_word = next(iter(re.findall(r"[A-Za-zÀ-ỹĐđ0-9|]+", line or "")), "")
    if _looks_like_kinh_token(first_word):
        return True
    if any(token in folded for token in _CV_UI_LEAK_TOKENS):
        return True
    if not collected:
        return False

    # ``Đảng ủy phường ...`` is usually a recipient, but it can legitimately be
    # the wrapped completion of a title such as ``... đồng chí Bí thư / Đảng ủy
    # phường Quý I/2025``.  Preserve it only when the previous title line clearly
    # requires an institutional complement.
    if folded.startswith(("dang uy phuong", "dang uy xa")):
        previous = fold_text(collected[-1]).rstrip(" ,;:")
        institution_complement_tails = (
            "bi thu", "pho bi thu", "thuong truc", "ban thuong vu",
            "cap uy", "dang uy", "dang bo", "cua dong chi bi thu",
        )
        if any(previous.endswith(tail) for tail in institution_complement_tails):
            return False

    return any(folded.startswith(prefix) for prefix in _CV_RECIPIENT_STARTS)


def _is_short_upper_fragment(token: str) -> bool:
    stripped = (token or "").strip(".,;:()[]{}")
    letters = "".join(ch for ch in stripped if ch.isalpha())
    return bool(letters) and len(letters) <= 2 and letters.isupper()


def _first_obvious_garbage_token(value: str) -> int | None:
    """Locate recogniser debris without cutting valid Vietnamese/acronyms."""
    text = value or ""
    token_matches = list(re.finditer(r"\S+", text))
    for index, match in enumerate(token_matches):
        if index < 4:
            continue
        token = match.group(0).strip(".,;:()[]{}")
        folded = fold_text(token)
        if not token:
            continue
        if re.search(r"&(?:quot|amp|lt|gt|#\d+);", token, re.IGNORECASE):
            return match.start()
        # Mojibake markers are case-sensitive. Using IGNORECASE here made the
        # suspicious capital ``Ã`` also match the perfectly valid Vietnamese
        # lowercase ``ã`` in words such as ``lãnh``/``xã`` and truncated titles.
        if any(marker in token for marker in ("�", "Ã", "Æ")):
            return match.start()
        if re.fullmatch(r"[xX]\d+", token) or re.fullmatch(r"\d+[A-Za-z]", token):
            return match.start()
        if re.search(r"[|^ˆ~`<>]", token):
            return match.start()
        if folded in {"bos", "plano", "cure", "curer", "vide", "dqqd"}:
            return match.start()
        if _is_short_upper_fragment(token):
            nearby = [
                item.group(0).strip(".,;:()[]{}")
                for item in token_matches[index : min(len(token_matches), index + 4)]
            ]
            if sum(_is_short_upper_fragment(item) for item in nearby) >= 2:
                return match.start()
        if index == len(token_matches) - 1 and _is_short_upper_fragment(token) and len(token) == 1:
            return match.start()
    return None


def _truncate_cv_ocr_garbage(value: str) -> str:
    """Cut OCR-only debris while preserving legitimate Công văn title text."""
    text = re.sub(r"\s+", " ", value or "").strip()
    if not text:
        return ""

    boundary = _cv_inline_boundary_index(text)
    if boundary is not None:
        text = text[:boundary].rstrip()

    patterns = (
        r"\s+(?:nu\s+)?m{2,}(?:\s*[|^ˆ~`´'\\/]+.*)?$",
        r"\s+[|^ˆ~`´]+.*$",
        r"\s+(?:mm+|nn+)(?:\s+|$).*$",
        r"\s+(?:nen\s+){2,}.*$",
        r"\s+(?:e{1,3}n\s+){2,}.*$",
        r"\s+-\s*(?:CT|ET|E|T)\s*$",
        r"\s+(?:[A-Z]\s+){2,}[A-Z]?\s*$",
        r"\s+(?:Pang|Dang)\s+Lee\s+nu\b.*$",
        r"\s+nu(?:\s+(?:nen|mm+|nn+)|\s*$).*$",
        r"\s+SN\s+\d*[A-Z]\b.*$",
        r"\s+(?:Home\s+Nano|Plano|BOS)\b.*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and len(text[: match.start()].split()) >= 4:
            text = text[: match.start()]
            break

    garbage_at = _first_obvious_garbage_token(text)
    if garbage_at is not None and len(text[:garbage_at].split()) >= 4:
        text = text[:garbage_at]

    # Remove trailing short recogniser fragments after a complete title.
    words = text.split()
    while len(words) >= 6:
        tail = fold_text(words[-1]).strip("-_/." )
        if tail in {"et", "ct", "mi", "kmi", "in", "een", "hi", "nu", "a"}:
            words.pop()
            continue
        break
    return " ".join(words).strip()


def _repair_cv_fixed_phrases(value: str) -> str:
    """Repair only stable Công văn phrases; never invent names or recipients."""
    text = value or ""
    replacements = (
        (r"\bV[oôơ]\s+vi[eệ]c\b", "Về việc"),
        (r"\bV[eêềèẻẽẹ]\s+vi[eệ]c\b", "Về việc"),
        (r"\bV[eêềèẻẽẹ]\s+tri[eể]n\s+khai\b", "Về triển khai"),
        (r"\bnguoi\s*xin\s*vao\s*dang\b", "người xin vào Đảng"),
        (r"\bnguoixinvao\s*dang\b", "người xin vào Đảng"),
        (
            r"\bph[uụ]c\s+v[uụ]\s+c[oô]ng\s+t[aá]c\s+"
            r"k[eế]t\s+n(?:a|g)p\s+(?:d[aả]ng|beng)\b",
            "phục vụ công tác kết nạp Đảng",
        ),
        (r"\bphuc\s+vu\s+cong\s+tac\s+ket\s+nap\s+dang\b", "phục vụ công tác kết nạp Đảng"),
        (r"\bxac\s+minh\s+thai\s+do\s+chinh\s+tri\b", "xác minh thái độ chính trị"),
        (r"\bcap\s+uy\s+dia\s+phuong\b", "cấp ủy địa phương"),
        (r"\bnguoi\s+xin\s+vao\s+Dang\b", "người xin vào Đảng"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    # A single coloured handwriting stroke is sometimes emitted as an isolated
    # capital between two real italic lines (``... chính trị Ả / phục vụ ...``).
    # Remove it only when the following words are a known title continuation;
    # sequences such as ``CC TT T`` remain visible garbage and are rejected.
    text = re.sub(
        r"\s+[A-ZÀ-ỸĐ]\s+(?=(?:ph[uụ]c|đ[oố]i|doi|ng[aà]y|ngay|h[oộ]i)\b)",
        " ",
        text,
    )
    text = re.sub(r"^\s*VE\b", "Về", text)
    return text


def _deduplicate_cv_title(value: str) -> str:
    words = (value or "").split()
    if len(words) < 8:
        return " ".join(words)

    folded = [fold_text(word) for word in words]
    changed = True
    while changed:
        changed = False
        # Remove adjacent repeated n-grams and overlapping crop duplicates.
        for size in range(min(18, len(words) // 2), 2, -1):
            found = False
            for start in range(0, len(words) - size * 2 + 1):
                if folded[start : start + size] == folded[start + size : start + size * 2]:
                    del words[start + size : start + size * 2]
                    del folded[start + size : start + size * 2]
                    changed = found = True
                    break
            if found:
                break

    # If OCR concatenated a shorter prefix and then repeated the complete title,
    # retain the later complete occurrence.
    starts = [
        index for index in range(1, len(words))
        if fold_text(" ".join(words[index : index + 2])).startswith(("ve viec", "v v"))
    ]
    for index in starts:
        prefix = " ".join(words[:index])
        suffix = " ".join(words[index:])
        if len(prefix.split()) <= 7 and _cv_title_language_quality(suffix) > _cv_title_language_quality(prefix):
            words = words[index:]
            break
    return " ".join(words).strip()


def cong_van_title_has_visible_garbage(value: str) -> bool:
    text = value or ""
    folded = fold_text(text)
    if re.search(r"[|^ˆ~`<>�]", text):
        return True
    if "Ã" in text or "Æ" in text:
        return True
    if re.search(r"&(?:quot|amp|lt|gt|#\d+);", text, re.IGNORECASE):
        return True
    if any(token in folded for token in _CV_UI_LEAK_TOKENS):
        return True
    if any(_looks_like_kinh_token(match.group(0)) for match in re.finditer(r"[A-Za-zÀ-ỹĐđ0-9|]+", text)):
        return True
    if re.search(r"\b(?:mmm+|nnn+|vide|dqqd|bos|plano)\b", folded):
        return True
    if re.search(r"\b(?:nen\s+){2,}|\b(?:een\s+){2,}", folded):
        return True
    if re.search(r"\b[xX]\d+\b|\b\d+[A-Za-z]\b", text):
        return True
    # Three or more isolated capital fragments (``CC TT T``) are recogniser
    # debris, while normal acronyms such as UBKT or NQ/TW remain valid tokens.
    if re.search(r"(?:^|\s)[A-ZĐ]{1,2}(?:\s+[A-ZĐ]{1,2}){2,}(?:\s|$)", text):
        return True
    # Mixed-case fragments such as ``cureR`` cannot be Vietnamese words and
    # repeatedly appeared when the italic crop was joined to body OCR.
    if re.search(r"\b[a-zà-ỹđ]{2,}[A-ZĐ][A-Za-zÀ-ỹĐđ]*\b", text):
        return True
    if re.search(r"\b(?:pang\s+lee\s+nu|lee\s+nu|home\s+nano)\b", folded):
        return True
    # A second occurrence of a substantive phrase in a short header normally
    # means overlapping OCR crops were concatenated rather than a real title.
    if len(re.findall(r"\bdanh\s+sach\b", folded)) >= 2:
        return True
    words = folded.split()
    if len(words) >= 5 and words[-1] in {"hi", "nu", "kmi", "een", "a"}:
        return True
    return False


def _cv_title_language_quality(value: str) -> float:
    text = _truncate_cv_ocr_garbage(value)
    words = re.findall(r"[A-Za-zÀ-ỹĐđ0-9/-]+", text)
    if not words:
        return 0.0
    folded_words = [fold_text(word) for word in words]
    garbage = 0
    for word in folded_words:
        letters = re.sub(r"[^a-z]", "", word)
        if not letters:
            continue
        if re.fullmatch(r"[mn]{3,}", letters):
            garbage += 2
        elif len(letters) >= 4 and not re.search(r"[aeiouy]", letters):
            garbage += 1
        elif letters in {"vide", "dqqd", "nd", "vl"}:
            garbage += 1
    start_bonus = 0.25 if _TITLE_START_RE.match(text.strip()) else 0.0
    length_score = min(0.45, len(words) / 30.0)
    corruption_penalty = 0.35 if cong_van_title_has_visible_garbage(text) else 0.0
    return max(0.0, min(1.0, 0.35 + start_bonus + length_score - garbage * 0.18 - corruption_penalty))


def cong_van_title_is_clean(value: str) -> bool:
    text = (value or "").strip()
    if len(text) < 8 or len(text) > 650:
        return False
    if not _TITLE_START_RE.match(text):
        return False
    if cong_van_title_has_visible_garbage(text):
        return False
    if _CV_BODY_BOUNDARY_RE.search(text):
        return False
    return _cv_title_language_quality(text) >= 0.48


def _clean_cv_title(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip(" -–—_=*.;:|")
    if not text:
        return ""
    text = _strip_noise_before_title(text)
    text = _repair_cv_fixed_phrases(text)
    text = _truncate_cv_ocr_garbage(text)
    boundary = _CV_BODY_BOUNDARY_RE.search(text)
    if boundary and boundary.start() >= 8:
        text = text[: boundary.start()]

    # Remove only an obviously stray standalone OCR year.  Earlier versions
    # deleted every year followed by words such as ``của``/``phục vụ`` and
    # therefore damaged legitimate title dates like ``ngày 25/7/2023 của ...``.
    stray_year = re.compile(
        r"\b20\d{2}\b(?=\s+(?:phục\s+vụ|về|để|của|cho)\b)",
        re.IGNORECASE,
    )

    def remove_only_stray_year(match: re.Match[str]) -> str:
        prefix_raw = text[max(0, match.start() - 42) : match.start()]
        prefix = fold_text(prefix_raw).rstrip()
        protected_tail = (
            "nam", "nhiem ky", "giai doan", "khoa",
            "quy i/", "quy ii/", "quy iii/", "quy iv/",
        )
        if any(prefix.endswith(item) for item in protected_tail):
            return match.group(0)
        if re.search(r"\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*$", prefix_raw):
            return match.group(0)
        if re.search(r"(?:ngày|ngay)\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s*$", prefix_raw, re.IGNORECASE):
            return match.group(0)
        return ""

    text = stray_year.sub(remove_only_stray_year, text)
    text = re.sub(r"\s+", " ", text).strip(" -–—_=*.;:|")
    text = _deduplicate_cv_title(text)
    return text.strip()


def _starts_with_lowercase_letter(value: str) -> bool:
    for char in value or "":
        if char.isalpha():
            return char.islower()
    return False


def _is_cv_body_line(line: str, collected: list[str]) -> bool:
    if _cv_line_is_recipient_or_ui(line, collected):
        return True

    # ``Ngày ...`` can be the second/third line of the italic title, e.g.
    # ``... các quy định, quyết định / ngày 30 tháng 8 ...``.  Do not cut it
    # merely because the first word is capitalised.
    if _cv_line_is_title_continuation(line, collected):
        return False

    if _CV_BODY_LINE_RE.match(line) or _INSTITUTION_BODY_LINE_RE.match(line):
        return True
    if not _CITED_INSTRUMENT_LINE_RE.match(line):
        return False
    if not collected:
        return False

    # A cited-instrument phrase may itself be the final line of a Công văn
    # abstract, e.g. ``... báo cáo việc triển khai / thực hiện Kế hoạch số...``.
    previous = fold_text(collected[-1]).rstrip(" ,;:")
    continuation_tail = (
        "trien khai",
        "viec trien khai",
        "bao cao viec trien khai",
        "ve viec",
        "ket qua",
        "moi du",
        "quy dinh",
        "quyet dinh",
        "dot",
    )
    if any(previous.endswith(item) for item in continuation_tail):
        return False
    return True


def extract_cong_van_title(
    raw_text: str,
    *,
    expected_number: str = "",
    expected_symbol: str = "",
    known_codes: Iterable[str] = (),
) -> CongVanTitle:
    lines = clean_lines(raw_text)
    if not lines:
        return CongVanTitle("", False)

    candidates = extract_number_symbol_candidates(
        raw_text,
        expected_code="CV",
        known_codes=known_codes,
    )
    candidate = None
    if expected_number or expected_symbol:
        normalized_expected_symbol = normalize_header_symbol(
            expected_symbol, known_codes=known_codes, issuer_text="\n".join(lines[:16])
        )
        for item in candidates:
            if expected_number and item.number != expected_number:
                continue
            if normalized_expected_symbol and item.symbol != normalized_expected_symbol:
                continue
            candidate = item
            break
    candidate = candidate or (candidates[0] if candidates else None)

    number_index = candidate.index if candidate else -1
    number = candidate.number if candidate else expected_number
    symbol = candidate.symbol if candidate else normalize_header_symbol(
        expected_symbol, known_codes=known_codes, issuer_text="\n".join(lines[:16])
    )

    # If OCR missed the handwritten number completely, locate the first visible
    # title in the top header only. This still provides a safe abstract while the
    # number field remains subject to its own validation.
    scan_start = number_index + 1 if number_index >= 0 else 0
    scan_end = min(len(lines), scan_start + (14 if number_index >= 0 else 20))
    parts: list[str] = []
    started = False
    strong_boundary = False

    if number_index >= 0:
        inline = _HEADER_NUMBER_SYMBOL_RE.sub("", lines[number_index], count=1)
        inline = _strip_noise_before_title(inline)
        if _TITLE_START_RE.match(inline):
            parts.append(inline)
            started = True

    for line in lines[scan_start:scan_end]:
        current = _strip_noise_before_title(line)
        if not current:
            continue
        if current == "-----" or _SEPARATOR_RE.fullmatch(current):
            if started:
                strong_boundary = True
                break
            continue
        if _is_header_noise(current) and not _cv_line_is_title_continuation(current, parts):
            continue
        if candidate and current == candidate.line:
            continue
        if _is_cv_body_line(current, parts):
            if started:
                strong_boundary = True
                break
            continue
        if re.match(r"^\s*S[oố0]\b", current, re.IGNORECASE):
            if started:
                strong_boundary = True
                break
            continue
        hard_boundary_index = _cv_inline_boundary_index(current)
        inline_boundary = (
            None
            if _cv_line_is_title_continuation(current, parts)
            else _CV_BODY_BOUNDARY_RE.search(current)
        )
        boundary_index = (
            min(
                index
                for index in (
                    hard_boundary_index,
                    inline_boundary.start() if inline_boundary else None,
                )
                if index is not None
            )
            if hard_boundary_index is not None or inline_boundary is not None
            else None
        )
        if boundary_index is not None:
            prefix = _clean_cv_title(current[:boundary_index])
            if prefix:
                if not started and _TITLE_START_RE.match(prefix):
                    started = True
                if started:
                    parts.append(prefix)
            strong_boundary = bool(parts)
            break
        if not started:
            if not _TITLE_START_RE.match(current):
                continue
            started = True
        parts.append(current)
        if len(parts) >= 7 or sum(len(item) for item in parts) >= 520:
            break

    value = _clean_cv_title(" ".join(parts))
    if not value or not _TITLE_START_RE.match(value):
        return CongVanTitle("", strong_boundary, number, symbol, 0.0)

    words = value.split()
    quality = min(1.0, len(words) / 12.0)
    language_quality = _cv_title_language_quality(value)
    score = 0.42 + 0.20 * quality + 0.30 * language_quality
    if language_quality < 0.42:
        score -= 0.28
    if candidate:
        score += min(0.16, max(0.0, candidate.score) / 100.0)
    if strong_boundary:
        score += 0.18
    if len(value) > 650:
        score -= 0.25
    return CongVanTitle(value, strong_boundary, number, symbol, min(1.0, score))


def document_header_score(
    raw_text: str,
    *,
    symbol_hint: str = "",
    type_hint: str = "",
    known_codes: Iterable[str] = (),
) -> float:
    expected_code = "CV" if (
        (symbol_hint or "").upper().split("/", 1)[0].endswith("CV")
        or "công văn" in (type_hint or "").casefold()
        or "cong van" in fold_text(type_hint)
        or re.search(r"\bCV\s*/", raw_text or "", re.IGNORECASE)
    ) else ""
    number = best_number_symbol(
        raw_text, expected_code=expected_code, known_codes=known_codes
    )
    title = extract_cong_van_title(
        raw_text,
        expected_number=number.number if number else "",
        expected_symbol=number.symbol if number else symbol_hint,
        known_codes=known_codes,
    ) if expected_code == "CV" else CongVanTitle("", False)
    score = 0.0
    if number:
        score += 0.46 + min(0.20, max(0.0, number.score) / 70.0)
    if title.value:
        score += 0.28 + (0.12 if title.strong_boundary else 0.0)
    lines = clean_lines(raw_text)
    if any(fold_text(line).startswith("kinh gui") for line in lines[:30]):
        score += 0.06
    if len(lines) > 35:
        score -= 0.08
    return max(0.0, min(1.0, score))


def build_canonical_document_header_details(
    raw_candidates: Iterable[str],
    *,
    symbol_hint: str = "",
    type_hint: str = "",
    known_codes: Iterable[str] = (),
) -> CanonicalDocumentHeader:
    values = [value for value in raw_candidates if (value or "").strip()]
    if not values:
        return CanonicalDocumentHeader("")

    expected_code = "CV" if (
        (symbol_hint or "").upper().split("/", 1)[0].endswith("CV")
        or "công văn" in (type_hint or "").casefold()
        or "cong van" in fold_text(type_hint)
        or any(re.search(r"\bCV\s*/", value, re.IGNORECASE) for value in values)
    ) else ""

    # Track support by independent OCR/crop text, not by duplicate lines inside
    # one candidate. This prevents one confidently wrong handwritten reading
    # from beating agreement across Paddle, Tesseract and a tight number crop.
    sourced: list[tuple[int, HeaderNumberSymbol]] = []
    for source_index, value in enumerate(values):
        seen_in_source: set[tuple[str, str]] = set()
        for item in extract_number_symbol_candidates(
            value, expected_code=expected_code, known_codes=known_codes
        ):
            key = (item.number, item.symbol)
            if key in seen_in_source:
                continue
            seen_in_source.add(key)
            sourced.append((source_index, item))

    available_numbers = {item.number for _, item in sourced}

    def number_alias(number: str) -> str:
        if expected_code != "CV":
            return number
        # Prefix debris from ``Số``/blue handwriting often creates 5224 or
        # 56234. Merge it with 224/234 only when another independent reading
        # explicitly saw that suffix. Sequence fallback handles the remaining
        # one-sided cases later without globally truncating valid four digits.
        for prefix_len in (1, 2):
            suffix = number[prefix_len:]
            if suffix in available_numbers and len(suffix) in {2, 3, 4}:
                return suffix
        return number

    normalized_symbol_hint = normalize_header_symbol(
        symbol_hint, known_codes=known_codes
    )

    def symbol_alias(symbol: str) -> str:
        if expected_code != "CV" or not normalized_symbol_hint.startswith("CV/"):
            return symbol
        suffix = symbol.split("/", 1)[1] if "/" in symbol else ""
        compact = re.sub(
            r"[^A-Z0-9]",
            "",
            suffix.replace("Đ", "D").replace("Ư", "U").replace("0", "O"),
        )
        if len(compact) <= 4 and (compact in {"U", "DU", "PDU", "DDU", "D0", "PU"} or compact.endswith("DU")):
            return normalized_symbol_hint
        return symbol

    grouped: dict[tuple[str, str], list[tuple[int, HeaderNumberSymbol]]] = {}
    for source_index, item in sourced:
        grouped.setdefault(
            (number_alias(item.number), symbol_alias(item.symbol)), []
        ).append((source_index, item))

    number: HeaderNumberSymbol | None = None
    number_support = 0
    number_score = 0.0
    if grouped:
        def consensus_rank(group: list[tuple[int, HeaderNumberSymbol]]) -> tuple[float, int, float, int]:
            best = max((item for _, item in group), key=lambda item: (item.score, -item.index))
            support = len({source_index for source_index, _ in group})
            consensus_bonus = min(24.0, max(0, support - 1) * 8.0)
            length_bonus = 1.5 if expected_code == "CV" and 1 <= len(number_alias(best.number)) <= 4 else 0.0
            own_symbol_bonus = 2.0 if expected_code == "CV" and best.symbol == "CV/ĐU" else 0.0
            return (best.score + consensus_bonus + length_bonus + own_symbol_bonus, support, best.score, -best.index)

        winning_key, winning_group = max(grouped.items(), key=lambda pair: consensus_rank(pair[1]))
        _best_source, best_item = max(
            winning_group, key=lambda pair: (pair[1].score, -pair[1].index)
        )
        canonical_number, canonical_symbol = winning_key
        number = HeaderNumberSymbol(
            canonical_number, canonical_symbol, best_item.line, best_item.index, best_item.score
        )
        number_support = len({source_index for source_index, _ in winning_group})
        number_score = best_item.score

    titles: list[CongVanTitle] = []
    if expected_code == "CV":
        for value in values:
            title = extract_cong_van_title(
                value,
                expected_number=number.number if number else "",
                expected_symbol=number.symbol if number else symbol_hint,
                known_codes=known_codes,
            )
            if title.value and cong_van_title_is_clean(title.value):
                titles.append(title)

        def title_rank(item: CongVanTitle) -> tuple[float, float, int, int]:
            agreement = sum(
                1
                for other in titles
                if other is not item
                and (
                    fold_text(other.value) == fold_text(item.value)
                    or fold_text(other.value).startswith(fold_text(item.value))
                    or fold_text(item.value).startswith(fold_text(other.value))
                    or difflib.SequenceMatcher(
                        None, fold_text(item.value), fold_text(other.value)
                    ).ratio() >= 0.72
                )
            )
            extension_support = sum(
                1
                for other in titles
                if other is not item
                and cong_van_title_is_safe_extension(item.value, other.value)
            )
            complete_bonus = min(0.24, len(item.value.split()) / 90.0)
            boundary_bonus = 0.10 if item.strong_boundary else 0.0
            truncation_penalty = 0.28 if cong_van_title_looks_truncated(item.value) else 0.0
            rank = (
                item.score
                + agreement * 0.10
                + extension_support * 0.22
                + complete_bonus
                + boundary_bonus
                - truncation_penalty
            )
            return (rank, _cv_title_language_quality(item.value), int(item.strong_boundary), len(item.value))

        titles.sort(key=title_rank, reverse=True)

    title = titles[0] if titles else None
    parts: list[str] = []
    if number:
        parts.append(f"Số {number.number}-{number.symbol}")
    if title:
        parts.append(title.value)
        parts.append("Kính gửi:")
    if parts:
        return CanonicalDocumentHeader(
            text="\n".join(parts),
            number=number.number if number else "",
            symbol=number.symbol if number else "",
            number_support=number_support,
            number_score=number_score,
            number_candidate_count=len(sourced),
            title_score=title.score if title else 0.0,
        )

    fallback = max(
        values,
        key=lambda value: document_header_score(
            value,
            symbol_hint=symbol_hint,
            type_hint=type_hint,
            known_codes=known_codes,
        ),
    )
    return CanonicalDocumentHeader(
        text=fallback,
        number=number.number if number else "",
        symbol=number.symbol if number else "",
        number_support=number_support,
        number_score=number_score,
        number_candidate_count=len(sourced),
    )


def build_canonical_document_header(
    raw_candidates: Iterable[str],
    *,
    symbol_hint: str = "",
    type_hint: str = "",
    known_codes: Iterable[str] = (),
) -> str:
    return build_canonical_document_header_details(
        raw_candidates,
        symbol_hint=symbol_hint,
        type_hint=type_hint,
        known_codes=known_codes,
    ).text


def clean_cong_van_title(value: str) -> str:
    """Public bounded cleanup for existing/stale Công văn abstracts."""
    return _clean_cv_title(value)
