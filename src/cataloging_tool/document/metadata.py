from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from cataloging_tool.domain.models import ParsedField

from .normalizer import fold_vietnamese

_DATE_RE = re.compile(
    r"(?:[^,\n]{1,60},\s*)?ngay\s*[:：]?\s*"
    r"(?P<day>\d{1,2})\s*thang\s*[:：]?\s*"
    r"(?P<month>\d{1,2})\s*nam\s*[:：]?\s*"
    r"(?P<year>20\d{2})",
    re.IGNORECASE,
)

_ROLE_TOKENS = (
    "ban thuong vu",
    "bi thu",
    "pho bi thu",
    "chanh van phong",
    "pho chanh van phong",
    "chu tich",
    "pho chu tich",
    "truong ban",
    "pho truong ban",
    "t/m ",
    "tm ",
    "k/t ",
    "kt ",
    "t/l ",
    "tl ",
    "noi nhan",
    "dang cong san viet nam",
    "dang bo thanh pho",
    "dang uy phuong",
    "van phong dang uy",
    "kinh gui",
    "tran trong",
)

_COMMON_SURNAMES = {
    "nguyen", "tran", "le", "pham", "hoang", "huynh", "phan", "vu", "vo",
    "dang", "bui", "do", "ngo", "duong", "ly", "truong", "dinh", "mai", "cao",
    "luu", "quach", "ton", "lam", "thai", "trinh", "dao", "chau", "ha", "ho",
}


def _clean_lines(text: str) -> list[str]:
    result: list[str] = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" \t|_—–-:;,.•·")
        if line:
            result.append(line)
    return result


def extract_document_date(header_text: str, raw_text: str = "") -> ParsedField:
    """Extract the issue date printed below ``ĐẢNG CỘNG SẢN VIỆT NAM``.

    The national-heading window is authoritative. A generic body date is used
    only when it still occurs in the first 35 lines, preventing dates cited in
    the prose from being written into the form.
    """
    header_lines = _clean_lines(header_text)
    raw_lines = _clean_lines(raw_text)
    sources = [header_lines]
    if raw_lines and raw_lines != header_lines:
        sources.append(raw_lines)
    if not any(sources):
        return ParsedField()

    windows: list[tuple[str, float, str]] = []
    for source_index, lines in enumerate(sources):
        folded = [fold_vietnamese(line) for line in lines]
        for index, line in enumerate(folded[:40]):
            if "dang cong san viet nam" in line:
                start = max(0, index - 1)
                end = min(len(lines), index + 5)
                window = "\n".join(lines[start:end])
                confidence = 0.995 if source_index == 0 else 0.98
                windows.append((window, confidence, "national-heading-date"))
        windows.append(("\n".join(lines[:35]), 0.94, "top-header-date"))
    seen: set[str] = set()
    for text, confidence, source in windows:
        folded_text = fold_vietnamese(text)
        if folded_text in seen:
            continue
        seen.add(folded_text)
        for match in _DATE_RE.finditer(folded_text):
            day = int(match.group("day"))
            month = int(match.group("month"))
            year = int(match.group("year"))
            try:
                parsed = date(year, month, day)
            except ValueError:
                continue
            return ParsedField(parsed.isoformat(), confidence, source)
    return ParsedField()


_SECURITY_LEVELS = (
    ("tuyet mat", "Tuyệt mật"),
    ("toi mat", "Tối mật"),
    ("mat", "Mật"),
)


def extract_security_level(header_text: str, raw_text: str = "") -> ParsedField:
    """Return an explicit secrecy marking from the document header.

    A red stamp is not evidence of secrecy. Only short, explicit text labels
    such as ``MẬT``, ``TỐI MẬT`` or ``TUYỆT MẬT`` in the top/header region are
    accepted. Body prose mentioning a secret document is deliberately ignored.
    """
    header_lines = _clean_lines(header_text)[:45]
    raw_lines = _clean_lines(raw_text)[:30]
    sources: list[tuple[list[str], float, str]] = []
    if header_lines:
        sources.append((header_lines, 0.995, "security-header"))
    if raw_lines and raw_lines != header_lines:
        sources.append((raw_lines, 0.96, "security-top-page"))

    for lines, confidence, source in sources:
        for line in lines:
            key = fold_vietnamese(line)
            key = re.sub(r"[^a-z0-9 ]+", " ", key)
            key = re.sub(r"\s+", " ", key).strip()
            key = re.sub(r"^(?:do mat|muc do mat|do bao mat)\s*", "", key).strip()
            if len(key) > 16:
                continue
            for folded_level, display in _SECURITY_LEVELS:
                if key == folded_level:
                    return ParsedField(display, confidence, source)
    return ParsedField()


# FIX_STRICT_DISTRICT_AUTHOR_0127410
# HOTFIX_AUTHOR_HEADER_EVIDENCE_0127414
_DISTRICT_PARENT_MARKERS = (
    "quan uy quan",
    "dang bo quan",
)

_ISSUER_BOUNDARY_TOKENS = (
    # Generic institution boundaries are intentional here.  They are searched
    # only *after* the current prefix was consumed, so they safely stop leaked
    # adjacent header text from another institutional label.
    "dang uy",
    "quan uy",
    "dang bo",
    "dang uy phuong",
    "quan uy quan",
    "dang bo quan",
    "dang bo thanh pho",
    "dang cong san viet nam",
    "cong hoa xa hoi chu nghia viet nam",
    "van phong",
    "so ",
    "bao cao",
    "cong van",
    "nghi quyet",
    "quyet dinh",
    "ke hoach",
    "thong bao",
    "chi thi",
    "to trinh",
    "chuong trinh",
    "quy che",
    "ket luan",
    "kinh gui",
    "can cu",
    "xay dung",
    "lanh dao",
    "de nghi",
    "ve viec",
    "ngay ",
)

_INVALID_UNIT_PHRASES = (
    "bao cao",
    "cong van",
    "nghi quyet",
    "quyet dinh",
    "ke hoach",
    "thong bao",
    "chi thi",
    "to trinh",
    "chuong trinh",
    "xay dung",
    "lanh dao",
    "thuc hien",
    "de nghi",
    "kinh gui",
)

# Once one of these document/body headings is reached, institutional evidence
# appearing later is not allowed to complete the issuing organization.  This
# prevents recipient/body mentions from becoming the author.
_ISSUER_HEADER_STOP_MARKERS = (
    "nghi quyet",
    "quyet dinh",
    "bao cao",
    "thong bao",
    "ke hoach",
    "cong van",
    "chi thi",
    "to trinh",
    "chuong trinh",
    "quy che",
    "ket luan",
    "kinh gui",
    "can cu",
)


@dataclass(frozen=True)
class _UnitChoice:
    value: str = ""
    score: int = 0
    support: int = 0
    conflict: bool = False


@dataclass(frozen=True)
class _AuthorHeaderEvidence:
    local_party: str = ""
    district_committee: str = ""
    district_party: str = ""
    city_party: str = ""
    office: bool = False
    local_hint: bool = False
    parent_hint_kinds: frozenset[str] = frozenset()
    local_conflict: bool = False
    parent_conflict: bool = False

    @property
    def parent_value(self) -> str:
        return self.district_committee or self.district_party or self.city_party

    @property
    def parent_kind(self) -> str:
        if self.district_committee:
            return "district_committee"
        if self.district_party:
            return "district_party"
        if self.city_party:
            return "city_party"
        return ""

    @property
    def has_positive_fact(self) -> bool:
        return bool(
            self.local_party
            or self.parent_value
            or self.office
            or self.local_hint
            or self.parent_hint_kinds
        )

    @property
    def is_conflicted(self) -> bool:
        return self.local_conflict or self.parent_conflict


def _line_has_district_parent(line: str) -> bool:
    key = fold_vietnamese(line)
    return any(marker in key for marker in _DISTRICT_PARENT_MARKERS)


def _district_context(lines: list[str]) -> bool:
    return any(_line_has_district_parent(line) for line in lines)


def _first_boundary_index(text: str) -> int:
    """Return the first generic issuer/title boundary in folded text."""
    candidates: list[int] = []
    padded = f" {text} "
    for token in _ISSUER_BOUNDARY_TOKENS:
        match = re.search(rf"(?<!\w){re.escape(token)}", padded)
        if match:
            candidates.append(max(0, match.start() - 1))
    for marker in ("*", "|", ";", ":"):
        index = text.find(marker)
        if index >= 0:
            candidates.append(index)
    return min(candidates) if candidates else len(text)


def _clean_unit_candidate(value: str) -> str:
    candidate = re.sub(r"\s+", " ", value or "").strip(
        " \t|_—–-:;,.•·*()[]{}"
    )
    if not candidate:
        return ""

    words = re.findall(r"[0-9A-Za-zÀ-ỹĐđ]+(?:[-'][0-9A-Za-zÀ-ỹĐđ]+)?", candidate)
    if not words:
        return ""

    # Numbered wards/districts have an unambiguous one-token unit name. This
    # prevents OCR title text on the same line from leaking into the author.
    if words[0].isdigit():
        return words[0]

    # Single-letter OCR artefacts such as I/l/G are too ambiguous to be a ward
    # or district name.  Do not silently turn a digit recognition failure into
    # a real organization.
    if len(words) == 1 and len(words[0]) == 1 and words[0].isalpha():
        return ""

    if len(words) > 4:
        return ""

    folded_candidate = fold_vietnamese(" ".join(words))
    if any(phrase in folded_candidate for phrase in _INVALID_UNIT_PHRASES):
        return ""

    cleaned = " ".join(words).upper().replace("UỶ", "ỦY")
    if len(cleaned) > 50:
        return ""
    return cleaned


def _strip_repeated_unit_label(candidate: str, canonical_prefix: str) -> str:
    """Remove OCR/form duplication such as a repeated ``PHƯỜNG`` label.

    The prefix parser already consumed the first institutional unit label.  A
    second label at the start of the extracted unit is therefore duplication,
    not part of the ward/district name.
    """
    value = re.sub(r"\s+", " ", candidate or "").strip()
    if not value:
        return ""

    prefix_key = fold_vietnamese(canonical_prefix)
    patterns: tuple[str, ...] = ()
    if prefix_key.endswith(" phuong"):
        patterns = (r"^(?:PHƯỜNG|PHUONG|P\s*\.?)[\s.-]+",)
    elif prefix_key.endswith(" quan"):
        patterns = (r"^(?:QUẬN|QUAN|Q\s*\.?)[\s.-]+",)
    elif prefix_key.endswith(" thanh pho"):
        patterns = (
            r"^(?:THÀNH\s+PHỐ|THANH\s+PHO|TP\s*\.?)[\s.-]+",
        )

    for pattern in patterns:
        value = re.sub(pattern, "", value, count=1, flags=re.IGNORECASE).strip()

    return _clean_unit_candidate(value)


def _issuer_search_text(original: str) -> str:
    """Fold OCR text while keeping character indexes aligned with ``original``."""
    folded = fold_vietnamese(original)
    # Same-length spaces preserve slicing indexes.  Dots are included because
    # Q./P. abbreviations are common OCR/header forms.
    return re.sub(r"[-–—_:;|/*.]+", lambda match: " " * len(match.group(0)), folded)


def _extract_unit_from_line(
    line: str,
    prefix_pattern: str,
    canonical_prefix: str,
) -> str:
    original = re.sub(r"\s+", " ", line or "").strip()
    if not original:
        return ""

    folded = _issuer_search_text(original)
    prefix = re.search(prefix_pattern, folded, re.IGNORECASE)
    if not prefix:
        return ""

    tail_original = original[prefix.end():].lstrip(" \t|_—–-:;,.•·*")
    tail_folded = fold_vietnamese(tail_original)
    boundary = _first_boundary_index(tail_folded)
    candidate = _clean_unit_candidate(tail_original[:boundary])
    candidate = _strip_repeated_unit_label(candidate, canonical_prefix)
    if not candidate:
        return ""
    return f"{canonical_prefix} {candidate}"


def _issuer_line_windows(lines: list[str]) -> list[tuple[str, int]]:
    """Return issuer-safe windows with a directness score.

    Direct physical lines are strongest. Adjacent 2/3-line joins are recovery
    candidates for OCR that split an institution label across lines.
    """
    cleaned = [re.sub(r"\s+", " ", line or "").strip() for line in lines]
    cleaned = [line for line in cleaned if line]
    variants: list[tuple[str, int]] = []
    seen: set[str] = set()

    for size, directness in ((1, 5), (2, 3), (3, 2)):
        for index in range(0, len(cleaned) - size + 1):
            value = " ".join(cleaned[index : index + size]).strip()
            if not value or len(value) > 240:
                continue
            key = fold_vietnamese(value)
            if key in seen:
                continue
            seen.add(key)
            variants.append((value, directness))
    return variants


def _issuer_line_variants(lines: list[str]) -> list[str]:
    return [value for value, _ in _issuer_line_windows(lines)]


def _issuer_header_window(lines: list[str]) -> list[str]:
    """Keep only the top institutional/header band, not cited body agencies."""
    cleaned = [re.sub(r"\s+", " ", line or "").strip() for line in lines if line.strip()]
    result: list[str] = []
    issuer_seen = False

    for line in cleaned[:30]:
        key = fold_vietnamese(line)
        has_issuer_token = any(
            marker in key
            for marker in (
                "dang uy",
                "quan uy",
                "dang bo",
                "van phong",
                "dang cong san viet nam",
            )
        )

        # In the standard Party-document layout the issuing organizations are
        # above the document number. Once an issuer token has been seen, the
        # document's own ``Số ...`` line is a hard boundary. This prevents a
        # title such as "V/v ... Quận ủy Quận 6" from being mistaken for the
        # parent organization when the tiny top line OCR is weak.
        number_boundary = bool(
            re.match(r"^s(?:o|0)\s*[:：]?\s*\d", key)
        )
        title_boundary = key.startswith(("v/v ", "vv ", "ve viec "))
        if result and issuer_seen and (
            number_boundary
            or title_boundary
            or any(marker in key for marker in _ISSUER_HEADER_STOP_MARKERS)
        ):
            break

        result.append(line)
        issuer_seen = issuer_seen or has_issuer_token

    return result


def _extract_issuer_unit_candidates(
    lines: list[str],
    prefix_pattern: str,
    canonical_prefix: str,
    canonical_marker: str,
) -> dict[str, tuple[int, int]]:
    """Return candidate -> (score, support) for one institutional unit."""
    candidates: dict[str, tuple[int, int]] = {}
    marker = fold_vietnamese(canonical_marker)

    for line, directness in _issuer_line_windows(lines):
        candidate = _extract_unit_from_line(line, prefix_pattern, canonical_prefix)
        if not candidate:
            continue

        folded_line = fold_vietnamese(line)
        score = directness + (2 if marker in folded_line else 0)
        old_score, old_support = candidates.get(candidate, (0, 0))
        candidates[candidate] = (max(old_score, score), old_support + 1)

    return candidates


def _choose_unit(candidates: dict[str, tuple[int, int]]) -> _UnitChoice:
    if not candidates:
        return _UnitChoice()

    ranked = sorted(
        candidates.items(),
        key=lambda item: (
            -item[1][0],
            -item[1][1],
            len(item[0].split()),
            len(item[0]),
            fold_vietnamese(item[0]),
        ),
    )
    top_value, (top_score, top_support) = ranked[0]
    if len(ranked) == 1:
        return _UnitChoice(top_value, top_score, top_support, False)

    second_value, (second_score, second_support) = ranked[1]
    del second_value

    # Do not pick arbitrarily between two equally plausible OCR unit names.
    if (
        top_score == second_score
        and top_support == second_support
    ) or (
        top_score - second_score <= 1
        and top_support <= second_support
    ):
        return _UnitChoice("", top_score, top_support, True)

    return _UnitChoice(top_value, top_score, top_support, False)


def _header_has_office_marker(lines: list[str]) -> bool:
    for line in _issuer_line_variants(lines):
        key = fold_vietnamese(line)
        if key == "van phong":
            return True
        if key.startswith("van phong dang uy phuong "):
            return True
        if "dang uy phuong " in key and key.endswith(" van phong"):
            return True
    return False


def _parent_kind_hints(lines: list[str]) -> frozenset[str]:
    hints: set[str] = set()
    for line in _issuer_line_variants(lines):
        key = _issuer_search_text(line)
        if re.search(r"\bquan\s+uy\b", key):
            hints.add("district_committee")
        if re.search(r"\bdang\s+bo\s+(?:quan\b|q\s+)", key):
            hints.add("district_party")
        if re.search(r"\bdang\s+bo\s+(?:thanh\s+pho\b|tp\s+)", key):
            hints.add("city_party")
    return frozenset(hints)


def _local_party_hint(lines: list[str]) -> bool:
    for line in _issuer_line_variants(lines):
        key = _issuer_search_text(line)
        if re.search(r"\bdang\s+uy\s+(?:phuong\b|p\s+)", key):
            return True
    return False


def _author_header_evidence(lines: list[str]) -> _AuthorHeaderEvidence:
    lines = _issuer_header_window(lines)
    if not lines:
        return _AuthorHeaderEvidence()

    local_choice = _choose_unit(
        _extract_issuer_unit_candidates(
            lines,
            r"\bdang\s+uy\s+(?:phuong\b|p\s*\.?\s*)",
            "ĐẢNG ỦY PHƯỜNG",
            "dang uy phuong",
        )
    )
    committee_choice = _choose_unit(
        _extract_issuer_unit_candidates(
            lines,
            r"\bquan\s+uy\s+(?:quan\b|q\s*\.?\s*)",
            "QUẬN ỦY QUẬN",
            "quan uy quan",
        )
    )
    party_choice = _choose_unit(
        _extract_issuer_unit_candidates(
            lines,
            r"\bdang\s+bo\s+(?:quan\b|q\s*\.?\s*)",
            "ĐẢNG BỘ QUẬN",
            "dang bo quan",
        )
    )
    city_choice = _choose_unit(
        _extract_issuer_unit_candidates(
            lines,
            r"\bdang\s+bo\s+(?:thanh\s+pho\b|tp\s*\.?\s*)",
            "ĐẢNG BỘ THÀNH PHỐ",
            "dang bo thanh pho",
        )
    )

    parent_choices = [
        ("district_committee", committee_choice),
        ("district_party", party_choice),
        ("city_party", city_choice),
    ]
    nonempty = [(kind, choice) for kind, choice in parent_choices if choice.value]
    parent_conflict = any(choice.conflict for _, choice in parent_choices)
    chosen_kind = ""
    chosen_parent = _UnitChoice()

    if nonempty:
        ranked = sorted(
            nonempty,
            key=lambda item: (-item[1].score, -item[1].support, item[0]),
        )
        chosen_kind, chosen_parent = ranked[0]
        if len(ranked) > 1:
            second_kind, second = ranked[1]
            del second_kind
            # Parent *kind* is semantically important in this archive: a dossier
            # legitimately mixes ĐẢNG BỘ QUẬN and QUẬN ỦY QUẬN.  A close OCR
            # conflict must stay unresolved instead of defaulting to one kind.
            # Overlapping 1/2/3-line windows are not independent votes. If two
            # different parent kinds have nearly the same directness score, the
            # header is conflicted even when one appears in one extra joined
            # window. Only a clear score margin may resolve the parent kind.
            if chosen_parent.score - second.score <= 1:
                parent_conflict = True
                chosen_kind = ""
                chosen_parent = _UnitChoice()

    district_committee = (
        chosen_parent.value if chosen_kind == "district_committee" else ""
    )
    district_party = chosen_parent.value if chosen_kind == "district_party" else ""
    city_party = chosen_parent.value if chosen_kind == "city_party" else ""

    hints = _parent_kind_hints(lines)
    if len(hints) > 1 and not chosen_kind:
        parent_conflict = True

    return _AuthorHeaderEvidence(
        local_party=local_choice.value,
        district_committee=district_committee,
        district_party=district_party,
        city_party=city_party,
        office=_header_has_office_marker(lines),
        local_hint=_local_party_hint(lines),
        parent_hint_kinds=hints,
        local_conflict=local_choice.conflict,
        parent_conflict=parent_conflict,
    )


def _canonical_author_from_evidence(evidence: _AuthorHeaderEvidence) -> str:
    if evidence.is_conflicted:
        return ""

    local_party = evidence.local_party
    if not local_party:
        return ""

    if evidence.office:
        return f"VĂN PHÒNG {local_party}"

    if evidence.district_committee:
        return f"{local_party} {evidence.district_committee}"

    if evidence.district_party:
        return f"{local_party} {evidence.district_party}"

    if evidence.city_party:
        return f"{local_party} {evidence.city_party}"

    return ""


def _canonical_author_from_header(lines: list[str]) -> str:
    return _canonical_author_from_evidence(_author_header_evidence(lines))


def _merged_header_lines(*sources: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for source in sources:
        for line in _issuer_header_window(source):
            key = fold_vietnamese(line)
            if key in seen:
                continue
            seen.add(key)
            merged.append(line)

    return merged


def canonical_author_from_text(
    header_text: str,
    raw_text: str,
    *,
    default_author: str,
) -> str:
    """Canonicalize the issuer from institutional evidence in the PDF header.

    The current document header is authoritative. ``default_author`` is kept
    only for API compatibility and is never used as a fallback.
    """
    del default_author
    header_lines = _clean_lines(header_text)
    raw_lines = _clean_lines(raw_text)
    sources = [lines for lines in (header_lines, raw_lines) if lines]

    for lines in sources:
        author = _canonical_author_from_header(lines)
        if author:
            return author

    # Complementary evidence may live in different OCR/text-layer sources, but
    # only their bounded top-header windows may be merged.  If the sources
    # disagree on ĐẢNG BỘ vs QUẬN ỦY, the evidence object marks a conflict and
    # this deliberately returns empty rather than choosing by order.
    if len(sources) >= 2:
        author = _canonical_author_from_header(_merged_header_lines(*sources))
        if author:
            return author

    return ""


def existing_author_matches_pdf_evidence(existing_author: str, pdf_evidence_text: str) -> bool:
    """Return True only when a website author is corroborated by PDF facts.

    A correct existing value may rescue OCR, but a local-party match alone is
    not enough for district/city documents.  The PDF must also expose the same
    parent kind (and the same parent value when readable).  This prevents a
    stale ĐẢNG BỘ value from being reused on a QUẬN ỦY document in the same
    dossier, and vice versa.
    """
    existing_lines = _clean_lines(existing_author)
    pdf_lines = _clean_lines(pdf_evidence_text)

    existing = _author_header_evidence(existing_lines)
    pdf = _author_header_evidence(pdf_lines)

    if (
        not existing.has_positive_fact
        or not pdf.has_positive_fact
        or existing.is_conflicted
        or pdf.is_conflicted
    ):
        return False

    if existing.local_party:
        if not pdf.local_party:
            return False
        if fold_vietnamese(pdf.local_party) != fold_vietnamese(existing.local_party):
            return False

    if existing.parent_value:
        # Exact parent value is strongest when available.
        if pdf.parent_value:
            if pdf.parent_kind != existing.parent_kind:
                return False
            if fold_vietnamese(pdf.parent_value) != fold_vietnamese(existing.parent_value):
                return False
        else:
            # If OCR missed only the unit name/number, the same explicit parent
            # kind is enough to corroborate the existing field.  No parent hint
            # means no rescue: the archive mixes both kinds within one dossier.
            if existing.parent_kind not in pdf.parent_hint_kinds:
                return False

    if pdf.office and not existing.office:
        return False
    if existing.office and not pdf.office:
        return False

    return True



def _looks_like_person_name(line: str) -> bool:
    if not line or any(char.isdigit() for char in line):
        return False
    key = fold_vietnamese(line)
    if any(token in key for token in _ROLE_TOKENS):
        return False
    if any(mark in line for mark in ("/", "@", "=", "<", ">", "_")):
        return False
    words = re.findall(r"[A-Za-zÀ-ỹĐđ]+(?:[-'][A-Za-zÀ-ỹĐđ]+)?", line)
    if not 2 <= len(words) <= 6:
        return False
    if len(" ".join(words)) < 6 or len(" ".join(words)) > 70:
        return False
    first = fold_vietnamese(words[0])
    if first not in _COMMON_SURNAMES:
        return False
    # A personal name may be title case or all capitals. Reject prose fragments.
    title_like = sum(word[:1].isupper() for word in words)
    uppercase_like = sum(word.isupper() and len(word) > 1 for word in words)
    return title_like >= len(words) - 1 or uppercase_like >= len(words) - 1


def _normalise_person_name(line: str) -> str:
    value = re.sub(r"\s+", " ", line).strip(" \t|_—–-:;,.•·")
    if value.isupper():
        # str.title keeps Vietnamese letters and makes all-uppercase OCR usable.
        value = value.title()
    return value


def extract_signer_name(signature_text: str, raw_text: str = "") -> ParsedField:
    """Extract the personal name next to/below the signature and red stamp.

    ``signature_text`` should be OCR/text from the bottom of the final page.
    The full document is only a guarded fallback and only its final lines are
    considered, so names in the body or recipient block cannot win.
    """
    primary_lines = _clean_lines(signature_text)
    fallback_lines = _clean_lines(raw_text)[-35:]
    candidates: list[tuple[float, str, str]] = []

    for source_lines, base, source in (
        (primary_lines[-45:], 1.0, "signature-region"),
        (fallback_lines, 0.72, "document-tail"),
    ):
        if not source_lines:
            continue
        folded = [fold_vietnamese(line) for line in source_lines]
        role_indexes = [
            index
            for index, key in enumerate(folded)
            if any(
                marker in key
                for marker in (
                    "ban thuong vu", "bi thu", "chanh van phong",
                    "chu tich", "truong ban", "pho bi thu", "pho chanh van phong",
                )
            )
        ]
        for index, line in enumerate(source_lines):
            if not _looks_like_person_name(line):
                continue
            if not role_indexes:
                # A person-looking line in the document tail may be a recipient,
                # attendee or body reference. Without a nearby signature role we
                # do not have enough evidence to write a signer automatically.
                continue
            nearest = min(abs(index - role_index) for role_index in role_indexes)
            if nearest > 8:
                continue
            distance_bonus = max(0.0, 0.20 - nearest * 0.02)
            end_bonus = 0.12 * (index + 1) / max(1, len(source_lines))
            name = _normalise_person_name(line)
            candidates.append((base + distance_bonus + end_bonus, name, source))

    if not candidates:
        return ParsedField()
    score, value, source = max(candidates, key=lambda item: item[0])
    confidence = 0.97 if source == "signature-region" and score >= 1.10 else 0.90 if source == "signature-region" else 0.78
    return ParsedField(value, confidence, source)


__all__ = [
    "canonical_author_from_text",
    "existing_author_matches_pdf_evidence",
    "extract_document_date",
    "extract_signer_name",
    "extract_security_level",
]
