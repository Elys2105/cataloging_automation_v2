from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_SPECIAL_SUBJECT_EVIDENCE = (
    "noi chinh",
    "tham nhung",
    "lang phi",
    "tieu cuc",
    "tu phap",
)


_DATE_HEADING_RE = re.compile(
    r"\bbao\s+cao\s+(?:ngay\s+)?(?P<day>\d{1,2})\s+"
    r"thang\s+(?P<month>\d{1,2})\s+nam\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_REPORT_HEADING_RE = re.compile(
    r"\bbao\s+cao(?:\s+(?:ngay|thang|tuan|quy|nam|\d{1,2}))?\b",
    re.IGNORECASE,
)
_PAREN_DATE_RE = re.compile(
    r"\(?\s*ng[aàáạảãâă]?y\s+(?P<day>\d{1,2})\s+"
    r"th[aàáạảã]?ng\s+(?P<month>\d{1,2})\s+"
    r"n[aăâ]?m\s+(?P<year>\d{4})\s*\)?",
    re.IGNORECASE,
)
_PAREN_REPORT_PERIOD_RE = re.compile(
    r"\(\s*(?:(?:k[ỳy]|ky)\s+b[aá]o\s+c[aá]o\s*:\s*)?"
    r"ng[aàáạảãâă]?y\s+(?P<day>\d{1,2})\s*[/-]\s*"
    r"(?P<month>\d{1,2})\s*[/-]\s*(?P<year>\d{4})\s*\)",
    re.IGNORECASE,
)
_FORM_DATE_RE = re.compile(
    r"(?P<year>\d{4})[-/]?(?P<month>\d{1,2})[-/]?(?P<day>\d{1,2})$|"
    r"(?P<day2>\d{1,2})[/-](?P<month2>\d{1,2})[/-](?P<year2>\d{4})$"
)

_BODY_PREFIXES = (
    "can cu",
    "kinh gui",
    "noi nhan",
    "danh sach",
    "dong chi",
    "ban noi chinh",
    "theo yeu cau",
    "noi dung bao cao",
    "a. tinh hinh",
    "a tinh hinh",
    "i. tinh hinh",
    "i tinh hinh",
    "stt",
)

_INLINE_BODY_RE = re.compile(
    r"\s+(?=(?:(?:Thực\s+hiện|Thc\s+hin|Thc\s+hien|Thuc\s+hien)\s+"
    r"(?:Kế\s+hoạch|Ke\s+hoach|Ké\s+hoch|Công\s+văn|Cong\s+van|"
    r"Quyết\s+định|Quyet\s+dinh|Nghị\s+quyết|Nghi\s+quyet|"
    r"Chương\s+trình|Chuong\s+trinh|Hướng\s+dẫn|Huong\s+dan)|"
    r"Căn\s+cứ|Can\s+cu|Kính\s+gửi|Kinh\s+gui|Danh\s+sách|"
    r"STT\b|A[.)]\s*TÌNH\s+HÌNH|I[.)]\s*TÌNH\s+HÌNH))",
    re.IGNORECASE,
)


def _find_inline_body_boundary(value: str) -> re.Match[str] | None:
    """Find appended body prose without cutting legitimate title wording."""
    for match in _INLINE_BODY_RE.finditer(value or ""):
        prefix_key = fold_report_text((value or "")[: match.start()])
        following_key = fold_report_text((value or "")[match.start() : match.start() + 100])
        # ``Tổng kết thực hiện Nghị quyết...`` is itself a recurring title.
        if prefix_key.endswith("tong ket") and following_key.startswith("thuc hien nghi quyet"):
            continue
        # FIX_REVIEW_EXISTING_REPORT_FRAGMENT_012748
        # ``triển khai thực hiện <văn bản>`` is a title predicate, not the
        # beginning of body prose.  OCR/form values are often flattened to one
        # line, so cutting at ``Thực hiện`` here loses the first half of a clean
        # report title and creates a false low-confidence review.
        if prefix_key.endswith("trien khai") and following_key.startswith("thuc hien "):
            continue
        return match
    return None


def fold_report_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "")
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    folded = without_marks.replace("đ", "d").replace("Đ", "D").casefold()
    folded = re.sub(r"[^a-z0-9/.,()\-–—]+", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def _clean_line(value: str) -> str:
    line = re.sub(r"\s+", " ", value or "").strip()
    return line.strip(" |_=*•·")


def _is_separator(value: str) -> bool:
    compact = re.sub(r"\s+", "", value or "")
    return len(compact) >= 3 and all(char in "-–—_=*·•." for char in compact)


def _uppercase_ratio(value: str) -> float:
    letters = [char for char in value if char.isalpha()]
    if not letters:
        return 0.0
    return sum(char.isupper() for char in letters) / len(letters)


def _looks_like_body_line(value: str, *, collected: int) -> bool:
    key = fold_report_text(value)
    if not key:
        return False
    if _is_separator(value):
        return True
    if key.startswith(_BODY_PREFIXES):
        return True
    if re.match(
        r"^(?:thuc hien|thc hien|thc hin|thuc hin)\s+"
        r"(?:ke hoach|cong van|quyet dinh|nghi quyet|chuong trinh|huong dan)\b",
        key,
    ):
        return True
    if re.match(r"^(?:\d+|[ivxlcdm]+)[.)]\s+", key):
        return True
    if re.match(
        r"^(?:so\s*)?\d{1,6}\s*[-–—]\s*"
        r"(?:cv|bc|kh|qd|nq|hd|tb|ttr|ct)\s*/",
        key,
    ):
        return True
    if key.startswith(("bao cao nhu sau", "bao cao sau day")):
        return True
    if collected > 0 and re.search(r"\bcong\s+van\s+so\b", key):
        return True
    if collected > 0 and re.search(r"\bban\s+noi\s+chinh\b", key):
        return True
    return False


def _looks_like_title_line(value: str, *, first: bool = False) -> bool:
    key = fold_report_text(value)
    if not key:
        return False
    if first and _REPORT_HEADING_RE.search(key):
        return True
    if key.startswith((
        "ve ", "v/v ", "v ve ", "tinh hinh ", "tinh hinh,", "tong ket ",
        "tng kt ", "nam tinh hinh ", "bao cao ve ", "ket qua ",
    )):
        return True
    if _PAREN_DATE_RE.search(value) or _PAREN_REPORT_PERIOD_RE.search(value):
        return True
    if any(
        token in key
        for token in (
            "cong tac noi chinh",
            "phong chong tham nhung",
            "lang phi tieu cuc",
            "cai cach tu phap",
            "dai hoi dai bieu",
            "xay dung dang",
            "he thong chinh tri",
        )
    ):
        return True
    return _uppercase_ratio(value) >= 0.62 and len(key) >= 8


def _canonical_date_heading(value: str) -> str:
    key = fold_report_text(value)
    match = _DATE_HEADING_RE.search(key)
    if not match:
        marker = re.search(r"B[ÁA]O\s+C[ÁA]O", value, re.IGNORECASE)
        return _clean_line(value[marker.start() :] if marker else value)
    return (
        f"BÁO CÁO NGÀY {int(match.group('day'))} "
        f"THÁNG {int(match.group('month'))} NĂM {match.group('year')}"
    )


def _canonical_parenthetical_date(value: str) -> str:
    # Only a date visibly enclosed in parentheses belongs to the abstract as a
    # parenthetical period.  A normal title may contain ``ngày ... tháng ...``
    # as substantive text (for example Nghị quyết 18-NQ/TW); that must not be
    # detached or reclassified.
    if not re.search(r"\([^)]*ng[aàáạảãâă]?y[^)]*\)", value or "", re.IGNORECASE):
        return ""
    match = _PAREN_DATE_RE.search(value or "")
    if not match:
        return ""
    return (
        f"(Ngày {int(match.group('day'))} tháng "
        f"{int(match.group('month'))} năm {match.group('year')})"
    )


def _canonical_parenthetical_period(value: str) -> str:
    """Return a parenthetical report period only when it is visible in OCR/PDF text.

    Normal reports must never inherit the form date merely because a date field
    exists.  The parenthetical is part of the abstract only when the PDF title
    block itself contains it.
    """
    textual = _canonical_parenthetical_date(value)
    if textual:
        return textual
    slash = _PAREN_REPORT_PERIOD_RE.search(value or "")
    if not slash:
        return ""
    prefix = fold_report_text(slash.group(0))
    label = "Kỳ báo cáo: " if "ky bao cao" in prefix else ""
    return (
        f"({label}ngày {int(slash.group('day'))}/"
        f"{int(slash.group('month'))}/{slash.group('year')})"
    )


def canonical_parenthetical_date_from_form(value: str) -> str:
    compact = re.sub(r"\s+", "", value or "")
    match = _FORM_DATE_RE.search(compact)
    if not match:
        return ""
    if match.group("year"):
        year = match.group("year")
        month = match.group("month")
        day = match.group("day")
    else:
        year = match.group("year2")
        month = match.group("month2")
        day = match.group("day2")
    return f"(Ngày {int(day)} tháng {int(month)} năm {year})"


def _canonical_subject(value: str) -> str:
    """Repair a visible report subject without substituting a stored abstract."""
    text = _clean_line(value)
    if not text:
        return ""
    # Remove only a visible report/date heading; keep the subject words that
    # actually occur in OCR/PDF evidence.
    text = re.sub(
        r"^\s*B[ÁA]O\s+C[ÁA]O(?:\s+NG[ÀA]Y\s+\d{1,2}\s+"
        r"TH[ÁA]NG\s+\d{1,2}\s+N[ĂA]M\s+\d{4})?\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    if not text:
        return ""

    # These are local OCR word/phrase repairs, not a document-specific answer.
    repairs = (
        (r"\bC[ÔO]NG\s+TC\b", "CÔNG TÁC"),
        (r"\bPHNG\s*,?\s*CHNG\b", "PHÒNG CHỐNG"),
        (r"\bTHAM\s+NHNG\b", "THAM NHŨNG"),
        (r"\bLNG\s+PH[IÍ]\b", "LÃNG PHÍ"),
        (r"\bTIU\s+CC\b", "TIÊU CỰC"),
        (r"\bC[ẢA]I\s+C[ÁA]CH\s+T[ƯU]\s+PH[ÁA]P\b", "CẢI CÁCH TƯ PHÁP"),
    )
    for pattern, replacement in repairs:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -–—_=*.;:")
    folded = fold_report_text(text)
    evidence = sum(token in folded for token in _SPECIAL_SUBJECT_EVIDENCE)
    if evidence >= 3:
        text = re.sub(r"^V\s+(?=C[ÔO]NG\s+T[ÁA]C)", "VỀ ", text, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip(" -–—_=*.;:")
    return _clean_line(value)


def _visible_special_subject(values: Iterable[str]) -> str:
    """Return the strongest visible special-report subject from OCR candidates."""
    candidates: list[str] = []
    for value in values:
        parts: list[str] = []
        for line in (_clean_line(item) for item in (value or "").splitlines()):
            if not line:
                continue
            key = fold_report_text(line)
            if key == "bao cao" or _DATE_HEADING_RE.search(key):
                continue
            if _looks_like_body_line(line, collected=len(parts)):
                break
            parts.append(line)
        candidate = _canonical_subject(" ".join(parts))
        folded = fold_report_text(candidate)
        evidence = sum(token in folded for token in _SPECIAL_SUBJECT_EVIDENCE)
        if evidence >= 3:
            candidates.append(candidate)
    if not candidates:
        return ""
    return max(
        candidates,
        key=lambda value: (
            sum(token in fold_report_text(value) for token in _SPECIAL_SUBJECT_EVIDENCE),
            len(fold_report_text(value)),
        ),
    )


def report_abstract_is_garbage(value: str) -> bool:
    text = _clean_line(value)
    if not text:
        return True
    folded = fold_report_text(text)
    if re.fullmatch(r"a\d+(?:\.\d+){4,}", folded.replace(" ", "")):
        return True
    if re.fullmatch(r"(?:a?\d+[.-]){4,}\d+", folded.replace(" ", "")):
        return True
    if re.search(r"&(?:gt|lt|amp|quot);", text, re.IGNORECASE):
        return True
    if re.search(r"\b[wvrx]{5,}\b", folded):
        return True
    if re.match(
        r"^(?:so\s*)?\d{1,6}\s*[-–—]\s*"
        r"(?:cv|bc|kh|qd|nq|hd|tb|ttr|ct)\s*/",
        folded,
    ):
        return True
    if folded.startswith((
        "bao cao nhu sau", "bao cao sau day", "thuc hien cong van",
        "cong van so",
    )):
        return True
    letters = sum(char.isalpha() for char in text)
    symbols = sum(not char.isalnum() and not char.isspace() for char in text)
    if letters < 8 or (letters and symbols / letters > 0.38):
        return True
    words = re.findall(r"[A-Za-zÀ-ỹĐđ]{2,}", text)
    if len(words) < 3:
        return True
    return False


def extract_special_report_title(raw_text: str) -> str:
    """Extract only the fixed title block of daily/periodic landscape reports."""

    lines = [_clean_line(line) for line in (raw_text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    start_index = -1
    for index, line in enumerate(lines[:120]):
        key = fold_report_text(line)
        if _DATE_HEADING_RE.search(key):
            start_index = index
            break
        if (
            key == "bao cao"
            and index + 1 < len(lines)
            and re.match(
                r"^(?:ngay\s+)?\d{1,2}\s+thang\s+\d{1,2}\s+nam\s+\d{4}\b",
                fold_report_text(lines[index + 1]),
            )
        ):
            lines[index] = f"{line} {lines[index + 1]}"
            del lines[index + 1]
            start_index = index
            break

    if start_index < 0:
        return ""

    parts = [_canonical_date_heading(lines[start_index])]
    inline_subject = _canonical_subject(lines[start_index])
    if sum(token in fold_report_text(inline_subject) for token in _SPECIAL_SUBJECT_EVIDENCE) >= 3:
        parts.append(inline_subject)

    for line in lines[start_index + 1 : start_index + 12]:
        if _looks_like_body_line(line, collected=len(parts)):
            break
        if not _looks_like_title_line(line):
            break
        if len(parts) == 2 and sum(
            token in fold_report_text(parts[1]) for token in _SPECIAL_SUBJECT_EVIDENCE
        ) >= 3:
            break
        parts.append(line)
        if len(parts) >= 5:
            break

    if len(parts) < 2:
        return ""

    subject = _canonical_subject(" ".join(parts[1:]))
    if len(fold_report_text(subject)) < 20:
        return ""
    result = f"{parts[0]} {subject}"
    return re.sub(r"\s+", " ", result).strip(" -–—_=*.;:")


def recover_special_report_title_from_candidates(
    values: Iterable[str],
    *,
    document_date: str = "",
) -> str:
    """Combine date and fixed-subject evidence from separate report crops.

    The date stored in the form may repair the tiny ``BÁO CÁO NGÀY...`` line
    only for the archive's table-style daily report layout.  Merely seeing the
    fixed subject is not enough: normal portrait reports can discuss the same
    subject and must never inherit a date that is absent from their title.
    """
    texts = [value for value in values if value and value.strip()]
    for value in texts:
        title = extract_special_report_title(value)
        if title:
            return title

    date_heading = ""
    folded_all = " ".join(fold_report_text(value) for value in texts)
    for value in texts:
        key = fold_report_text(value)
        match = _DATE_HEADING_RE.search(key)
        if match:
            date_heading = (
                f"BÁO CÁO NGÀY {int(match.group('day'))} "
                f"THÁNG {int(match.group('month'))} NĂM {match.group('year')}"
            )
            break

    evidence = sum(
        token in folded_all
        for token in (
            "noi chinh",
            "tham nhung",
            "lang phi",
            "tieu cuc",
            "tu phap",
        )
    )
    table_layout = any(
        token in folded_all
        for token in (
            "a. tinh hinh",
            "a tinh hinh",
            "stt",
            "ten cong viec",
            "tom tat noi dung",
            "don vi tinh",
        )
    )
    if not date_heading and evidence >= 3 and table_layout:
        form_date = canonical_parenthetical_date_from_form(document_date)
        date_match = _PAREN_DATE_RE.search(form_date)
        if date_match:
            date_heading = (
                f"BÁO CÁO NGÀY {int(date_match.group('day'))} "
                f"THÁNG {int(date_match.group('month'))} NĂM {date_match.group('year')}"
            )
    if date_heading and evidence >= 3:
        subject = _visible_special_subject(texts)
        if subject:
            return f"{date_heading} {subject}"
    return ""


def report_title_has_strong_boundary(raw_text: str) -> bool:
    """Return True when a report title is visibly bounded in OCR/PDF text.

    A dedicated crop can produce a plausible title even when the separator is
    missing.  Such a value is useful for review, but it must not be auto-submitted
    unless the crop also contains a horizontal separator or an unmistakable body
    opener after at least one title line.
    """
    lines = [_clean_line(line) for line in (raw_text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return False
    if extract_special_report_title(raw_text):
        return True
    starts = [
        index
        for index, line in enumerate(lines[:160])
        if fold_report_text(line) == "bao cao"
        or bool(re.fullmatch(r"bao cao[:\-–—]?", fold_report_text(line)))
        or fold_report_text(line).startswith("bao cao ")
    ]
    for start in starts:
        collected = 0
        for line in lines[start + 1 : start + 40]:
            if _is_separator(line):
                return collected > 0
            inline = _find_inline_body_boundary(line)
            if inline is not None:
                if _clean_line(line[: inline.start()]):
                    collected += 1
                return collected > 0
            if _looks_like_body_line(line, collected=collected):
                return collected > 0
            key = fold_report_text(line)
            if key.startswith((
                "dang cong san viet nam", "dang uy phuong", "dang bo thanh pho",
                "quan uy quan", "dang bo quan", "so ",
            )):
                continue
            if _looks_like_title_line(line) or collected > 0:
                collected += 1
    return False


def _dedupe_parenthetical_periods(value: str) -> str:
    """Keep one copy of repeated ``(Ngày...)`` / ``(Kỳ báo cáo...)`` text."""
    text = value or ""
    matches = list(re.finditer(
        r"\(\s*(?:(?:K[ỳy]|Ky)\s+b[áa]o\s+c[áa]o\s*:\s*)?"
        r"ng[àáạảãâăa]?y\s+\d{1,2}(?:\s+th[àáạảãa]?ng\s+\d{1,2}\s+"
        r"n[ăâa]?m\s+\d{4}|\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{4})\s*\)",
        text, flags=re.IGNORECASE,
    ))
    if len(matches) < 2:
        return text
    seen: set[str] = set()
    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor:match.start()])
        key = fold_report_text(match.group(0))
        if key not in seen:
            pieces.append(match.group(0))
            seen.add(key)
        cursor = match.end()
    pieces.append(text[cursor:])
    return re.sub(r"\s+", " ", "".join(pieces)).strip()

def _dedupe_report_lines(lines: list[str]) -> list[str]:
    """Remove repeated OCR lines while preserving their first occurrence.

    Dedicated title crops can overlap.  When their text is concatenated, the same
    title line may appear two or three times.  Only near-identical repetitions
    inside a short window are removed; genuine repeated words inside a sentence
    remain untouched.
    """
    result: list[str] = []
    recent: list[str] = []
    for line in lines:
        key = fold_report_text(line)
        if not key:
            continue
        if len(key) >= 8 and key in recent[-5:]:
            continue
        result.append(line)
        recent.append(key)
    return result


def _remove_adjacent_duplicate_phrases(value: str) -> str:
    """Collapse an immediately repeated OCR phrase of at least five words."""
    words = re.findall(r"\S+", value or "")
    if len(words) < 10:
        return re.sub(r"\s+", " ", value or "").strip()
    folded = [fold_report_text(word) for word in words]
    changed = True
    while changed:
        changed = False
        for size in range(min(40, len(words) // 2), 4, -1):
            for index in range(0, len(words) - 2 * size + 1):
                if folded[index : index + size] == folded[index + size : index + 2 * size]:
                    del words[index + size : index + 2 * size]
                    del folded[index + size : index + 2 * size]
                    changed = True
                    break
            if changed:
                break
    return re.sub(r"\s+", " ", " ".join(words)).strip()


def repair_report_title(value: str) -> str:
    """Repair only stable, recurring Báo cáo title patterns.

    This is deliberately not a general spell checker.  A repair is applied only
    when several anchors of a known administrative title are present, so names
    and free prose are never guessed.
    """
    text = _dedupe_parenthetical_periods(
        _remove_adjacent_duplicate_phrases(_clean_line(value))
    )
    if not text:
        return ""

    # Remove a very short OCR-noise prefix (for example ``mm`` or ``|``) only
    # when a clear report-title starter follows immediately.
    starter = re.search(
        r"\b(?:V[ềe]|Tình\s+hình|Tong\s+ket|Tổng\s+kết|Tng\s+kt|"
        r"Kết\s+quả|Nam\s+tình\s+hình)\b",
        text,
        flags=re.IGNORECASE,
    )
    if starter and starter.start() <= 10:
        prefix = text[: starter.start()]
        if not re.search(r"[A-Za-zÀ-ỹĐđ]{3,}", prefix):
            text = text[starter.start() :].strip()
    # Cut an appended prose body, but keep legitimate title wording.
    inline = _find_inline_body_boundary(text)
    if inline is not None and inline.start() >= 8:
        text = text[: inline.start()].strip()

    # The fixed landscape title intentionally includes ``BÁO CÁO NGÀY...``.
    # Strip only a standalone normal heading, never the dated special heading.
    special = extract_special_report_title(text)
    if special:
        return special
    text = re.sub(
        r"^B[ÁA]O\s+C[ÁA]O\b(?!\s+(?:NG[ÀA]Y|TH[ÁA]NG|TU[ẦA]N|QU[ÝY]|N[ĂA]M|\d))"
        r"[\s:|\-–—]*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    key = fold_report_text(text)

    # Repair only local OCR fragments below.  Never return a complete stored
    # title based on anchors such as a document number, year, ward, or record.
    repairs = (
        (r"^Tng\s+kt\b", "Tổng kết"),
        (r"^Tong\s+ket\b", "Tổng kết"),
        (r"\bthc\s+hin\b", "thực hiện"),
        (r"\bNghi\s+quyt\b", "Nghị quyết"),
        (r"\bca\s+Ban\s+Chp\s+hnh\s+Trung\s+ương\s+Đng\b", "của Ban Chấp hành Trung ương Đảng"),
        (r"\bphng\s*,?\s*chng\s+tham\s+nhng\b", "phòng, chống tham nhũng"),
        (r"\blng\s+phí\b", "lãng phí"),
        (r"\btiêu\s+cc\b", "tiêu cực"),
        (r"\bnhim\s+k\b", "nhiệm kỳ"),
    )
    for pattern, replacement in repairs:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" -–—_=*.;:")


def _normal_report_candidate(lines: list[str], start: int) -> str:
    parts: list[str] = []
    start_line = lines[start]
    start_key = fold_report_text(start_line)
    if start_key.startswith("bao cao "):
        # Some documents print the first title words on the same line as the
        # type heading, e.g. ``BÁO CÁO KIỂM ĐIỂM``. Preserve that remainder.
        remainder = re.sub(
            r"^\s*BÁO\s+CÁO\s*[:\-–—]?\s*",
            "",
            start_line,
            count=1,
            flags=re.IGNORECASE,
        ).strip()
        if remainder:
            remainder_key = fold_report_text(remainder)
            if remainder_key.startswith((
                "nhu sau", "sau day", "theo yeu cau", "gui kem",
            )):
                return ""
            parts.append(remainder)
    for line in lines[start + 1 : start + 36]:
        if _is_separator(line):
            break
        key = fold_report_text(line)
        if key == "bao cao" or re.fullmatch(r"bao cao[:\-–—]?", key):
            if parts:
                break
            continue
        if key.startswith((
            "dang cong san viet nam",
            "dang uy phuong",
            "dang bo thanh pho",
            "quan uy quan",
            "dang bo quan",
            "so ",
        )):
            continue

        inline = _find_inline_body_boundary(line)
        if inline:
            prefix = _clean_line(line[: inline.start()])
            if prefix:
                parts.append(prefix)
            break
        if _looks_like_body_line(line, collected=len(parts)):
            break

        period = _canonical_parenthetical_period(line)
        if period:
            if parts:
                parts.append(period)
            continue

        if not parts:
            if not _looks_like_title_line(line):
                continue
            parts.append(line)
            continue

        # A second copy of the first title line means overlapping OCR crops were
        # concatenated.  Stop instead of appending a duplicate title block.
        if fold_report_text(line) == fold_report_text(parts[0]):
            break
        if len(parts) >= 10:
            break
        parts.append(line)

    if not parts:
        return ""
    value = repair_report_title(" ".join(parts))
    if report_abstract_is_garbage(value):
        return ""
    return value


def extract_normal_report_title(raw_text: str, *, document_date: str = "") -> str:
    """Extract the best bounded normal Báo cáo title from all OCR occurrences.

    Overlapping crop OCR can contain multiple ``BÁO CÁO`` headings.  The old
    first-heading rule could select a truncated or duplicated block.  Every
    heading is now parsed independently and the best bounded candidate wins.
    ``document_date`` is intentionally ignored for normal reports.
    """
    del document_date
    lines = [_clean_line(line) for line in (raw_text or "").splitlines()]
    lines = _dedupe_report_lines([line for line in lines if line])
    if not lines:
        return ""

    starts = [
        index
        for index, line in enumerate(lines[:160])
        if fold_report_text(line) == "bao cao"
        or bool(re.fullmatch(r"bao cao[:\-–—]?", fold_report_text(line)))
        or fold_report_text(line).startswith("bao cao ")
    ]
    candidates = [_normal_report_candidate(lines, start) for start in starts]
    candidates = [value for value in candidates if value]
    if not candidates:
        return ""

    def score(value: str) -> tuple[float, int, int]:
        folded = fold_report_text(value)
        penalty = 0.0
        if re.search(r"\b(?:thuc hien|can cu|kinh gui|noi nhan)\b", folded):
            penalty += 0.4
        if len(folded) > 520:
            penalty += 0.3
        period = int(bool(_canonical_parenthetical_period(value)))
        richness = min(len(folded), 420)
        quality = 1.0 - penalty
        return (quality, period, richness)

    return max(candidates, key=score)

def extract_report_title_block(raw_text: str, *, document_date: str = "") -> str:
    """Extract only evidence that is visible in ``raw_text``.

    Form dates are deliberately ignored here. Missing dates for the fixed
    landscape/table template are repaired only by
    :func:`recover_special_report_title_from_candidates`, where table-layout
    evidence is available. This prevents normal reports from acquiring invented
    ``(Ngày...)`` or ``BÁO CÁO NGÀY...`` text.
    """
    special = extract_special_report_title(raw_text)
    if special:
        return special
    return extract_normal_report_title(raw_text, document_date=document_date)



def choose_better_report_title(*values: str) -> str:
    """Choose the best bounded title without rewarding duplication or body text."""
    titles: list[str] = []
    for value in values:
        if not value:
            continue
        title = extract_report_title_block(value)
        if not title and not report_abstract_is_garbage(value):
            title = repair_report_title(value)
        else:
            title = repair_report_title(title) if title else ""
        if title and not report_abstract_is_garbage(title) and title not in titles:
            titles.append(title)
    if not titles:
        return ""

    def key(title: str) -> tuple[int, float, int, int, int]:
        special = int(bool(extract_special_report_title(title)))
        period = int(bool(_canonical_parenthetical_period(title)))
        folded = fold_report_text(title)
        body_penalty = int(_find_inline_body_boundary(title) is not None)
        return (special, report_title_score(title), period, -body_penalty, len(folded))

    return max(titles, key=key)


def report_title_needs_recovery(title: str) -> bool:
    if not title or report_abstract_is_garbage(title):
        return True
    if extract_special_report_title(title):
        return False
    folded = fold_report_text(title)
    if len(folded) < 45:
        return True
    # Common partial endings observed when the generic header crop cuts the
    # second title line.  A dedicated crop should try to recover the remainder.
    return bool(
        re.search(r"\b(?:gan voi|tap trung|trong|va|cua|ve)$", folded)
    )

def special_report_title_score(value: str) -> float:
    title = extract_special_report_title(value)
    if not title:
        return 0.0
    folded = fold_report_text(title)
    score = 0.55
    if _DATE_HEADING_RE.search(folded):
        score += 0.20
    evidence = sum(token in folded for token in _SPECIAL_SUBJECT_EVIDENCE)
    if evidence >= 3:
        score += 0.25
    return min(1.0, score)


def report_title_score(value: str) -> float:
    special = special_report_title_score(value)
    if special:
        return special
    title = extract_normal_report_title(value)
    if not title:
        return 0.0
    score = 0.70
    if _canonical_parenthetical_period(title):
        score += 0.15
    folded_length = len(fold_report_text(title))
    if folded_length >= 55:
        score += 0.08
    if folded_length >= 100:
        score += 0.07
    if not report_abstract_is_garbage(title):
        score += 0.10
    return min(1.0, score)
