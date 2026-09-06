from __future__ import annotations

import difflib
import re
from dataclasses import replace
from pathlib import Path
import yaml

from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot, ParsedDocument, ParsedField

from .document_header import (
    best_number_symbol,
    clean_cong_van_title,
    cong_van_title_is_clean,
    cong_van_title_is_safe_extension,
    cong_van_title_looks_truncated,
    extract_cong_van_title,
    infer_header_symbol,
)
from .metadata import (
    canonical_author_from_text,
    existing_author_matches_pdf_evidence,
    extract_document_date,
    extract_security_level,
    extract_signer_name,
)
from .normalizer import VietnameseNormalizer, fold_vietnamese
from .ocr import abstract_has_visible_ocr_corruption, vietnamese_text_quality
from .report_title import (
    extract_report_title_block,
    extract_special_report_title,
    repair_report_title,
    report_abstract_is_garbage,
    report_title_has_strong_boundary,
)

DOC_HEADER_MAP = {
    "ke hoach": "Kế hoạch",
    "cong van": "Công văn",
    "quyet dinh": "Quyết định",
    "bao cao": "Báo cáo",
    "thong bao": "Thông báo",
    "nghi quyet": "Nghị quyết",
    "chi thi": "Chỉ thị",
    "huong dan": "Hướng dẫn",
    "to trinh": "Tờ trình",
    "bien ban": "Biên bản",
    "chuong trinh": "Chương trình",
    "quy che": "Quy chế",
    "ket luan": "Kết luận",
}

NUMBER_SYMBOL_RE = re.compile(
    r"(?:^|\b)(?:S[oố0]\s*[:：]?\s*)?(?P<number>\d{1,6})\s*[-–—]\s*"
    r"(?P<symbol>[A-ZĐÂĂÊÔƠƯ0-9]{1,10}(?:\s*/\s*[A-ZĐÂĂÊÔƠƯ0-9]{1,15})+)",
    re.IGNORECASE,
)

STOP_PREFIXES = (
    "kinh gui",
    "can cu",
    "xet ",
    "noi nhan",
    "t/m",
    "tm ",
    "dieu 1",
    "noi dung nhu sau",
)
URGENCY = {"khan", "thuong khan", "hoa toc"}

# OCR may merge the dashed separator and the first prose line into the title
# line.  This boundary is intentionally restricted to unmistakable body
# openers so a valid title is not shortened by ordinary words.
_INLINE_BODY_BOUNDARY_RE = re.compile(
    r"\s+(?=(?:"
    r"Kính\s+gửi|Kinh\s+gui|"
    r"Căn\s+cứ|Can\s+cu|"
    # ``thực hiện nhiệm vụ`` is valid title text.  Treat ``Thực hiện`` as a
    # body opener only when followed by a cited instrument.
    r"(?:Thực\s+hiện|Thc\s+hin|Thc\s+hien|Thuc\s+hien)\s+"
    r"(?:Kế\s+hoạch|Ke\s+hoach|Ké\s+hoch|Công\s+văn|Cong\s+van|"
    r"Quyết\s+định|Quyet\s+dinh|Nghị\s+quyết|Nghi\s+quyet|"
    r"Chương\s+trình|Chuong\s+trinh|Hướng\s+dẫn|Huong\s+dan)|"
    r"Điều\s+1|Dieu\s+1|"
    r"Nơi\s+nhận|Noi\s+nhan"
    r")\b)",
    re.IGNORECASE,
)



def _looks_like_report_heading(line: str) -> bool:
    """Recognise an actual BÁO CÁO heading, not body prose saying báo cáo như sau."""
    key = fold_vietnamese(line)
    if key == "bao cao":
        return True
    if not key.startswith("bao cao "):
        return False
    remainder = key[len("bao cao ") :].strip(" :|-–—")
    if remainder.startswith((
        "nhu sau", "sau day", "theo yeu cau", "gui kem", "de nghi",
    )):
        return False
    return bool(re.match(
        r"^(?:ngay|thang|tuan|quy|nam|kiem diem|tu danh gia|ket qua|"
        r"ve|tinh hinh|tong ket|cong tac|\d{1,2})\b",
        remainder,
    ))



class DocumentParser:
    def __init__(self, rules_dir: Path, author: str, security_level: str) -> None:
        self.normalizer = VietnameseNormalizer(rules_dir / "vietnamese_normalization.tsv")
        self.type_codes = yaml.safe_load((rules_dir / "document_types.yaml").read_text(encoding="utf-8"))
        self.author = author
        self.security_level = security_level

    def parse(
        self,
        raw_text: str,
        *,
        source: DataSource,
        source_confidence: float,
        existing_form: FormSnapshot | None = None,
        is_landscape: bool = False,
        special_report_title: str = "",
        header_evidence_text: str = "",
        signature_evidence_text: str = "",
        author_evidence_text: str = "",
    ) -> ParsedDocument:
        text = self.normalizer.normalize_text(raw_text)
        lines = self._prepare_lines(text)
        header_text = self.normalizer.normalize_text(header_evidence_text)
        header_lines = self._prepare_lines(header_text)
        report_scope = [*header_lines[:80], *lines[:80]]
        report_heading_evidence = any(
            _looks_like_report_heading(line) for line in report_scope
        )
        report_evidence = bool(
            special_report_title
            or report_heading_evidence
            or any(
                re.search(r"\b\d{1,6}\s*[-–—]\s*BC\s*/", line, re.IGNORECASE)
                for line in header_lines[:80]
            )
        )
        existing_symbol_hint = (
            self.normalizer.normalize_symbol(existing_form.symbol)
            if existing_form is not None else ""
        )
        existing_code_hint = (
            existing_symbol_hint.split("/", 1)[0].upper()
            if existing_symbol_hint else ""
        )
        header_scope_text = "\n".join(header_lines or lines[:24])
        report_header = (
            best_number_symbol(
                header_scope_text,
                expected_code="BC",
                known_codes=self.type_codes.keys(),
            )
            if report_evidence
            else None
        )
        generic_header = best_number_symbol(
            header_scope_text,
            known_codes=self.type_codes.keys(),
        )
        # A visible report heading plus an own BC header outranks any CV cited in
        # the first body paragraph.  This is the recurring Báo cáo failure shown
        # by records 266/272/276.
        top_header = report_header if report_heading_evidence and report_header else generic_header
        top_header_code = (
            top_header.symbol.split("/", 1)[0].upper()
            if top_header is not None else ""
        )
        if top_header_code == "CV" and not report_heading_evidence and not special_report_title:
            report_evidence = False
        cv_evidence = bool(
            top_header_code == "CV"
            or (
                not report_evidence
                and not top_header_code
                and existing_code_hint == "CV"
            )
        )
        expected_code = (
            top_header_code
            if top_header_code in {"BC", "CV"}
            else "BC" if report_evidence
            else "CV" if cv_evidence
            else ""
        )

        number = symbol = number_line = ""
        number_conf = 0.0
        if header_lines:
            number, symbol, number_conf, number_line = self._parse_number_symbol(
                header_lines,
                prefer_report=report_evidence,
                expected_code=expected_code,
            )
        if not number or not symbol:
            base_number, base_symbol, base_conf, base_line = self._parse_number_symbol(
                lines,
                prefer_report=report_evidence,
                expected_code=expected_code,
            )
            # Focused header evidence is authoritative. A clean cited body
            # instrument must never replace the document's own top number.
            if base_conf > number_conf and number_conf < 0.90:
                number, symbol, number_conf, number_line = (
                    base_number, base_symbol, base_conf, base_line
                )

        # Existing form values are important *parse hints*, not only a late
        # fallback.  Wide Báo cáo scans often OCR the tiny title but miss the
        # number/symbol line; without the BC hint the special parser never runs.
        if existing_form is not None:
            existing_number = (existing_form.document_number or "").strip()
            existing_symbol = self.normalizer.normalize_symbol(existing_form.symbol)
            existing_code = existing_symbol.split("/", 1)[0].upper() if existing_symbol else ""
            allow_existing_header = (
                existing_code == expected_code
                if expected_code
                else not report_evidence or existing_code == "BC"
            )
            if allow_existing_header and not number and re.fullmatch(r"\d{1,6}", existing_number):
                number = existing_number
                number_conf = 0.95
                number_line = f"Số {existing_number}-{existing_symbol}" if existing_symbol else existing_number
            if allow_existing_header and not symbol and re.fullmatch(
                r"[A-ZĐ0-9]{1,10}(?:/[A-ZĐ0-9]{1,15})+", existing_symbol
            ):
                symbol = existing_symbol
                number_conf = max(number_conf, 0.95)

        doc_type, type_conf, type_index = self._parse_type(lines, symbol)
        header_doc_type, header_type_conf, header_type_index = self._parse_type(
            header_lines, symbol
        )
        if header_doc_type and (not doc_type or header_type_conf >= type_conf):
            doc_type = header_doc_type
            type_conf = header_type_conf

        # A dedicated report-title crop is stronger evidence than stale form
        # metadata.  This also fixes records whose old symbol/type says Công văn
        # or Khác while the PDF visibly contains a BÁO CÁO heading.
        if report_evidence and (
            special_report_title
            or report_heading_evidence
            or (symbol.split("/", 1)[0].upper() if symbol else "") == "BC"
        ):
            doc_type = "Báo cáo"
            type_conf = max(type_conf, 0.99)
        header_code = symbol.split("/", 1)[0].upper() if symbol else ""
        if header_code == "CV" or cv_evidence:
            doc_type = "Công văn"
            type_conf = max(type_conf, 0.99 if header_code == "CV" else 0.90)

        abstract, abstract_conf = self._parse_abstract(
            lines,
            doc_type,
            type_index,
            number_line,
            document_number=number,
            symbol=symbol,
            document_header_text=header_text,
            is_landscape=is_landscape,
            special_report_title=special_report_title,
            document_date_hint=(existing_form.document_date if existing_form else ""),
            report_header_text=header_text,
            header_type_index=header_type_index,
        )

        document_date = extract_document_date(header_text, text)
        signer_name = extract_signer_name(signature_evidence_text, text)
        security = extract_security_level(header_text, text)
        author_header_text = self.normalizer.normalize_text(author_evidence_text)
        author = canonical_author_from_text(
            author_header_text or header_text,
            text,
            default_author=self.author,
        )
        author_confidence = 0.99 if author and author_header_text else 0.96 if author else 0.0
        author_source = (
            "focused-author-header"
            if author and author_header_text
            else "document-header"
            if author
            else ""
        )
        security_level = security.value or self.security_level
        security_confidence = security.confidence if security.value else 0.95
        security_source = security.source_text if security.value else "default:no-explicit-security-marking"

        result = ParsedDocument(
            document_number=ParsedField(number, number_conf, number_line),
            symbol=ParsedField(symbol, number_conf, number_line),
            document_type=ParsedField(doc_type, type_conf, ""),
            abstract=ParsedField(abstract, abstract_conf, ""),
            document_date=document_date,
            signer_name=signer_name,
            author=author,
            author_confidence=author_confidence,
            author_source_text=author_source,
            security_level=security_level,
            security_confidence=security_confidence,
            security_source_text=security_source,
            source=source,
            raw_text="\n".join(
                part
                for part in (
                    author_header_text,
                    header_text,
                    text,
                    signature_evidence_text,
                )
                if part
            ),
        )
        result = self._apply_existing_form(result, existing_form)
        field_confidence = min(
            result.document_number.confidence,
            result.symbol.confidence,
            result.document_type.confidence,
            result.abstract.confidence,
        )
        # OCR's average character confidence is not a hard upper bound for a
        # structurally parsed document.  A clear Số/Ký hiệu/heading/separator can
        # be reliable even when the engine reports 0.60.  Keep source confidence
        # as supporting evidence, but do not let it alone create false reviews.
        source_support = 0.70 + 0.30 * max(0.0, min(1.0, source_confidence))
        confirmed_fields = sum(
            "existing-form-confirmed" in field.source_text
            for field in (
                result.document_number,
                result.symbol,
                result.document_type,
                result.abstract,
            )
        )
        if confirmed_fields >= 3:
            source_support = max(source_support, 0.95)

        # A fully bounded structural parse is stronger than the OCR engine's
        # whole-page average.  This is especially important for faint scans:
        # the header crop can clearly identify Số/Ký hiệu, loại văn bản and a
        # Công văn title ending at ``Kính gửi`` even when page OCR confidence
        # is near zero.  Only lift the source support when every required field
        # is independently strong; weak or incomplete parses remain reviewable.
        strong_structural_parse = (
            bool(result.document_number.value)
            and bool(result.symbol.value)
            and bool(result.document_type.value)
            and bool(result.abstract.value)
            and result.document_number.confidence >= 0.90
            and result.symbol.confidence >= 0.90
            and result.document_type.confidence >= 0.90
            and result.abstract.confidence >= 0.90
        )
        if strong_structural_parse:
            source_support = max(source_support, 0.95)

        result.overall_confidence = min(field_confidence, source_support)
        return result

    def _parse_number_symbol(
        self,
        lines: list[str],
        *,
        prefer_report: bool = False,
        expected_code: str = "",
    ) -> tuple[str, str, float, str]:
        """Choose the document's own top header, never a cited body instrument."""
        if not lines:
            return "", "", 0.0, ""
        code = "BC" if prefer_report else expected_code
        candidate = best_number_symbol(
            "\n".join(lines),
            expected_code=code,
            known_codes=self.type_codes.keys(),
        )
        if candidate is None:
            return "", "", 0.0, ""
        confidence = (
            0.995 if candidate.score >= 18.0
            else 0.97 if candidate.score >= 12.0
            else 0.90 if candidate.score >= 7.0
            else 0.78
        )
        return candidate.number, candidate.symbol, confidence, candidate.line

    def _parse_type(self, lines: list[str], symbol: str) -> tuple[str, float, int]:
        for index, line in enumerate(lines[:60]):
            key = fold_vietnamese(line)
            # Special Báo cáo headings can include the date on the same line.
            # Treat them as Báo cáo while the abstract parser preserves the full
            # heading text as requested by the operator.
            if re.search(
                r"\bbao cao\s+(?:ngay|thang|tuan|quy|nam|\d{1,2})\b", key
            ):
                return "Báo cáo", 0.98, index
            for header, display in DOC_HEADER_MAP.items():
                if re.fullmatch(rf"{re.escape(header)}(?:\s*[:\-–—].*)?", key):
                    return display, 0.98, index
                # Tờ trình scans sometimes place the heading, OCR junk, and the
                # first title words on one line: "TỜ TRÌNH à | Về ...".
                # Recognize that line as the heading; prefix cleanup is handled
                # later by the Tờ trình-specific abstract repair.
                if display == "Tờ trình" and key.startswith(header + " "):
                    remainder = key[len(header) :].strip(" :|-–—")
                    if re.match(r"^(?:a\s*\|?\s*)?(?:ve|v |xin |de nghi |bao cao )", remainder):
                        return display, 0.98, index
        code = symbol.split("/", 1)[0].upper() if symbol else ""
        code = code.replace("Đ", "D") if code not in self.type_codes else code
        mapped = self.type_codes.get(code) or self.type_codes.get(code.replace("D", "Đ"))
        return (str(mapped), 0.82, -1) if mapped else ("", 0.0, -1)

    def _parse_abstract(
        self,
        lines: list[str],
        doc_type: str,
        type_index: int,
        number_line: str,
        *,
        document_number: str = "",
        symbol: str = "",
        document_header_text: str = "",
        is_landscape: bool = False,
        special_report_title: str = "",
        document_date_hint: str = "",
        report_header_text: str = "",
        header_type_index: int = -1,
    ) -> tuple[str, float]:
        # Business rule required by the operator:
        # - Công văn: text immediately below Số ...-CV/... until Kính gửi.
        # - Every other type: text below the document-type heading until the
        #   horizontal separator (---/-----/long dash line).
        if doc_type == "Công văn":
            header_lines = self._prepare_lines(
                self.normalizer.normalize_text(document_header_text)
            )
            header_value, header_boundary = self._parse_cong_van(
                header_lines,
                number_line,
                document_number=document_number,
                symbol=symbol,
            )
            base_value, base_boundary = self._parse_cong_van(
                lines,
                number_line,
                document_number=document_number,
                symbol=symbol,
            )
            if header_value and cong_van_title_is_clean(header_value):
                return header_value, (0.995 if header_boundary else 0.90)
            if base_value and cong_van_title_is_clean(base_value):
                return base_value, (0.97 if base_boundary else 0.78)
            return "", 0.0

        # All Báo cáo records use one bounded report-title extractor. It covers:
        # - portrait reports: text below BÁO CÁO through the separator, retaining
        #   the parenthetical (Ngày ... tháng ... năm ...) line;
        # - landscape/daily reports: BÁO CÁO NGÀY ... plus the fixed subject.
        # A dedicated high-resolution OCR hint wins when available.
        if doc_type == "Báo cáo":
            value = repair_report_title(
                self.normalizer.clean_abstract(special_report_title)
            )
            if value and report_abstract_is_garbage(value):
                value = ""
            if not value:
                value = repair_report_title(
                    extract_report_title_block(
                        "\n".join(lines),
                        document_date=document_date_hint,
                    )
                )
            if value and not report_abstract_is_garbage(value):
                evidence_text = "\n".join(
                    part for part in (report_header_text, "\n".join(lines)) if part
                )
                strong = bool(extract_special_report_title(value)) or report_title_has_strong_boundary(
                    evidence_text
                )
                return self.normalizer.clean_abstract(value), (0.99 if strong else 0.70)

        # Focused metadata recovery may see the document heading/title even
        # when whole-page OCR misses it.  For non-Công-văn types, prefer the
        # bounded focused-header title block when available.
        focused_header_lines = self._prepare_lines(
            self.normalizer.normalize_text(document_header_text)
        )

        # Thông báo titles in this archive frequently contain the fixed
        # institutional heading ``KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY``.
        # Raster OCR may lose several vowels and may merge the first body line
        # into the same OCR line.  Repair only that fixed heading/recurring
        # phrases and enforce a body boundary before validation.
        if doc_type == "Thông báo" and (type_index >= 0 or header_type_index >= 0):
            source_lines = focused_header_lines if header_type_index >= 0 else lines
            source_index = header_type_index if header_type_index >= 0 else type_index
            value, strong_boundary = self._parse_below_heading_until_separator(
                source_lines, source_index, doc_type
            )
            value = self._repair_thong_bao_abstract(value)
            if value:
                reliable_shape = self._looks_like_thong_bao_title(value)
                confidence = (
                    0.98 if strong_boundary and reliable_shape
                    else (0.92 if reliable_shape else 0.60)
                )
                return value, confidence

        # Tờ trình has a stable title block directly below TỜ TRÌNH.  Thin
        # separator lines are often lost by raster OCR, while the title itself
        # is still structurally clear.  Repair only conservative, recurring
        # title patterns and treat Kính gửi / a clean "Về..." title as a strong
        # boundary so correct records are not stuck at confidence 0.70.
        if doc_type == "Tờ trình" and (type_index >= 0 or header_type_index >= 0):
            source_lines = focused_header_lines if header_type_index >= 0 else lines
            source_index = header_type_index if header_type_index >= 0 else type_index
            value, strong_boundary = self._parse_below_heading_until_separator(
                source_lines, source_index, doc_type
            )
            value = self._repair_to_trinh_abstract(value)
            if value:
                reliable_shape = self._looks_like_to_trinh_title(value)
                confidence = 0.98 if strong_boundary else (0.90 if reliable_shape else 0.70)
                return value, confidence

        if type_index >= 0 or header_type_index >= 0:
            source_lines = focused_header_lines if header_type_index >= 0 else lines
            source_index = header_type_index if header_type_index >= 0 else type_index
            value, used_separator = self._parse_below_heading_until_separator(
                source_lines,
                source_index,
                doc_type,
            )
            if value:
                # The operator's mandatory rule for every non-CV document is:
                # below the type heading and before the horizontal separator.
                # Missing the separator is allowed only as a review candidate,
                # never as an auto-submit result.
                return value, 0.98 if used_separator else 0.70

        # Last fallback when OCR missed the heading. It is deliberately below the
        # auto-submit threshold because the mandatory title boundary was not seen.
        number_index = next((i for i, line in enumerate(lines) if line == number_line), -1)
        if number_index >= 0:
            start = number_index + 1
            for index in range(start, min(len(lines), start + 8)):
                if self._is_type_header(lines[index], doc_type):
                    value, used_separator = self._parse_below_heading_until_separator(
                        lines,
                        index,
                        doc_type,
                    )
                    return value, 0.78 if used_separator else 0.60
        return "", 0.0


    def _repair_thong_bao_abstract(self, value: str) -> str:
        """Repair and bound recurring Thông báo title blocks.

        This method deliberately avoids general spell-checking.  It repairs the
        fixed institutional heading and a short set of recurring administrative
        phrases, then removes any body text merged after the title.
        """
        text = self.normalizer.clean_abstract(value)
        if not text:
            return ""

        text = self._truncate_at_body_boundary(text)
        text = re.sub(
            r"^\s*TH(?:Ô|O)NG\s+B(?:Á|A)O\b[\s:|\-–—]*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

        # The normalizer already handles this heading in multiline OCR.  Run a
        # second bounded substitution here because existing form values may be
        # a single OCR-damaged line.
        text = re.sub(
            r"^\s*K(?:Ế|E)?T?\s+L(?:U|Ư)(?:Ậ|A)?N\s+"
            r"(?:(?:C(?:Ủ|U)A|CA)\s+)?BAN\s+"
            r"TH(?:ƯỜ|ƯƠ|UƠ|UO|Ư|U)?NG\s+V(?:Ụ|U)\s+"
            r"(?:Đ|D|P)?(?:Ả|A)?NG\s+(?:Ủ|U)?Y\b",
            "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY",
            text,
            flags=re.IGNORECASE,
        )

        repairs = (
            (r"\bV(?:ề|è|e)?\s+(?=đánh\s+giá)", "Về "),
            (r"\b(?:kt|kết)\s+qu(?:ả|ă|a)\b", "kết quả"),
            (r"\b(?:the|thc|thực)\s+hi(?:ệ|e)?n?\s+nhim\s+v\b", "thực hiện nhiệm vụ"),
            (r"\bđi\s+v(?:ó|o|ớ)i\s+đng\s+chí\b", "đối với đồng chí"),
            (r"\bH\s+đồng\s+nhân\s+dân\b", "Hội đồng nhân dân"),
            (r"\bvà\s+y\s+ban\s+nhân\s+dân\b", "và Ủy ban nhân dân"),
            (r"\bPhó\s+Chánh\s+V(?:ă|a|ã)n\s+phòng\b", "Phó Chánh Văn phòng"),
            (r"\bTrn\s+Th\b", "Trần Thị"),
            (r"\bBí\s+thưr\b", "Bí thư"),
            (r"\bChi\s+b\b", "Chi bộ"),
            (r"\bPhó\s+Trưng\s+Ban\b", "Phó Trưởng Ban"),
            (r"\bQun\s+lý\b", "Quản lý"),
            (r"\bBinh\s+Tiên\b", "Bình Tiên"),
        )
        for pattern, replacement in repairs:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        return self.normalizer.clean_abstract(self._truncate_at_body_boundary(text))

    @staticmethod
    def _looks_like_thong_bao_title(value: str) -> bool:
        key = fold_vietnamese(value)
        if len(value) < 16 or len(value) > 700:
            return False
        if key.startswith(("kinh gui", "can cu", "thuc hien", "noi nhan")):
            return False
        fixed = "ket luan cua ban thuong vu dang uy"
        if key.startswith(fixed):
            remainder = key[len(fixed):].strip()
            # The institutional heading alone is not the abstract. It must be
            # followed by the actual conclusion/title, normally beginning Về.
            return len(remainder) >= 8 and (remainder.startswith("ve ") or len(remainder.split()) >= 4)
        return key.startswith(("ve ", "thong bao ")) and len(key.split()) >= 4

    @staticmethod
    def _truncate_at_body_boundary(value: str) -> str:
        text = value or ""
        match = _INLINE_BODY_BOUNDARY_RE.search(text)
        if match and match.start() >= 8:
            text = text[: match.start()]
        return VietnameseNormalizer.clean_abstract(text)


    def _repair_to_trinh_abstract(self, value: str) -> str:
        """Repair bounded Tờ trình titles without spell-checking free prose.

        The recurring errors in this archive are missing Vietnamese letters in
        a handful of standard Đại hội / tổ chức titles.  Matching is therefore
        anchor-based and conservative: a canonical title is emitted only when
        all identifying anchors are present.  Other Tờ trình titles keep their
        OCR text after prefix/junk cleanup.
        """
        text = self.normalizer.clean_abstract(value)
        if not text:
            return ""

        # OCR sometimes returns the heading and a few stray glyphs on the same
        # line: "TỜ TRÌNH à | Về ...".  Remove the heading and only the short
        # junk run before the real title.
        text = re.sub(
            r"^\s*T(?:Ờ|O)\s*TR(?:Ì|I)NH\b",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        title_start = re.search(r"\b(?:Về|Ve|V)\b", text, flags=re.IGNORECASE)
        if title_start and title_start.start() <= 12:
            prefix = text[: title_start.start()]
            if not re.search(r"[A-Za-zÀ-ỹ]{3,}", prefix):
                text = text[title_start.start() :]
        text = re.sub(r"^[|¦Il1àáạa:;,.\-–—_=*\s]+(?=V(?:ề|e|\s)\b)", "", text, flags=re.IGNORECASE)
        text = self.normalizer.clean_abstract(text)

        # Bound a stale/overlong existing form value before body content.
        text = re.split(
            r"\s+(?=(?:Kính\s+gửi|Kinh\s+gui|Căn\s+cứ|Can\s+cu|"
            r"Thực\s+hiện|Thc\s+hin|Điều\s+1|\d+[.)]\s))",
            text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()

        # General, scope-limited OCR phrase repairs.  These rules repair
        # recurring Vietnamese fragments only; they never return a stored title
        # or depend on record id/number/abstract.
        repairs = (
            (r"^V\s+(?:ch|chi)\s*(?:đ|d)?nh\s+(?:đ|d|di)\s*biu\b", "Về chỉ định đại biểu"),
            (r"\bch\s+(?:đ|d)nh\s+(?:đ|d|di|đi)\s*biu\s+(?:đ|d|di|đi)\s+hi\s+(?:đ|d|di|đi)\s*biu\b", "chỉ định đại biểu dự Đại hội đại biểu"),
            (r"\b(?:đ|d)\s+(?:đ|d|di|đi)\s+hi\s+(?:đ|d|di|đi)\s*biu\b", "dự Đại hội đại biểu"),
            (r"\b(?:đ|d|di|đi)\s*biu\b", "đại biểu"),
            (r"\bch[ií]nh\s+thc\b", "chính thức"),
            (r"\b(?:Đ|D|P)ng\s+b\s+ph(?:ư[ơờ]?|u[oờ]?)?ng\b", "Đảng bộ phường"),
            (r"\bln\s+th\b", "lần thứ"),
            (r"\bnhim\s+k\b", "nhiệm kỳ"),
            (r"^v\s+", "Về "),
        )
        for pattern, replacement in repairs:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return self.normalizer.clean_abstract(text)

    @staticmethod
    def _looks_like_to_trinh_title(value: str) -> bool:
        key = fold_vietnamese(value)
        if len(value) < 12 or len(value) > 700:
            return False
        if key.startswith(("kinh gui", "can cu", "noi nhan", "dieu 1")):
            return False
        return key.startswith(("ve ", "xin ", "de nghi ", "bao cao "))


    def _parse_landscape_bao_cao(
        self,
        lines: list[str],
        number_line: str,
        *,
        is_landscape: bool,
    ) -> str:
        """Return only the daily/periodic Báo cáo title block.

        The dedicated extractor owns the boundary rules so generic OCR and
        high-resolution crop OCR cannot diverge.  ``number_line`` and
        ``is_landscape`` remain in the signature for compatibility and future
        diagnostics.
        """
        del number_line, is_landscape
        return self.normalizer.clean_abstract(
            extract_report_title_block("\n".join(lines))
        )

    def _parse_cong_van(
        self,
        lines: list[str],
        number_line: str,
        *,
        document_number: str = "",
        symbol: str = "",
    ) -> tuple[str, bool]:
        del number_line
        if not lines:
            return "", False
        title = extract_cong_van_title(
            "\n".join(lines),
            expected_number=document_number,
            expected_symbol=symbol,
            known_codes=self.type_codes.keys(),
        )
        value = self.normalizer.clean_abstract(title.value)
        return (
            (value, title.strong_boundary)
            if self._valid_abstract(value)
            else ("", title.strong_boundary)
        )

    def _parse_below_heading_until_separator(
        self,
        lines: list[str],
        type_index: int,
        doc_type: str,
    ) -> tuple[str, bool]:
        window = lines[type_index + 1 : type_index + 32]
        separator_index = next(
            (index for index, line in enumerate(window) if self._is_separator(line)),
            -1,
        )
        segment = window[:separator_index] if separator_index >= 0 else window
        parts: list[str] = []
        strong_boundary = separator_index >= 0

        same_line = self._remove_type_prefix(lines[type_index], doc_type)
        if same_line:
            parts.append(same_line)

        for line in segment:
            if self._is_separator(line):
                strong_boundary = True
                break
            if self._is_type_header(line, doc_type):
                continue
            if self._is_header_noise(line):
                continue

            # PDF.js/Tesseract occasionally merges the final title line and the
            # first body line. Preserve the title prefix and stop immediately.
            boundary_match = _INLINE_BODY_BOUNDARY_RE.search(line)
            if boundary_match:
                prefix = self.normalizer.clean_abstract(line[: boundary_match.start()])
                if prefix:
                    parts.append(prefix)
                strong_boundary = bool(parts)
                break

            if separator_index < 0 and self._is_stop_line(line, collected=len(parts)):
                # OCR engines may omit a thin dashed line. A body opener directly
                # after a non-empty title block is an equivalent strong boundary.
                strong_boundary = bool(parts) and self._is_strong_abstract_boundary(line)
                break
            parts.append(line)

        value = self._truncate_at_body_boundary(
            self.normalizer.clean_abstract(" ".join(parts))
        )
        return (value, strong_boundary) if self._valid_abstract(value) else ("", strong_boundary)

    @classmethod
    def _prepare_lines(cls, text: str) -> list[str]:
        result: list[str] = []
        for raw in text.splitlines():
            if cls._is_separator(raw):
                result.append("-----")
                continue
            line = cls._clean_line(raw)
            if line:
                result.append(line)
        return result

    @staticmethod
    def _is_separator(line: str) -> bool:
        compact = re.sub(r"\s+", "", line or "")
        if len(compact) < 3:
            return False
        return all(char in "-–—_=*·•." for char in compact)

    @staticmethod
    def _is_type_header(line: str, doc_type: str = "") -> bool:
        key = fold_vietnamese(line)
        for header, display in DOC_HEADER_MAP.items():
            if doc_type and display != doc_type:
                continue
            if key == header:
                return True
        return False

    @staticmethod
    def _existing_abstract_corroborated_by_fragment(
        existing_abstract: str,
        parsed_abstract: str,
    ) -> bool:
        """Return True when OCR captured a substantial title fragment.

        OCR can lose an opening title line while preserving the remaining
        lines.  If the document header already agrees with the form, a clean
        longer form title is corroborated by that fragment.  This deliberately
        requires a long, high-coverage token alignment so a short generic phrase
        cannot rescue an unrelated stale value.
        """
        existing_key = fold_vietnamese(existing_abstract)
        parsed_key = fold_vietnamese(parsed_abstract)
        if not existing_key or not parsed_key:
            return False
        if len(parsed_key) < 35 or len(parsed_key) > len(existing_key):
            return False

        existing_tokens = re.findall(r"[a-z0-9]+", existing_key)
        parsed_tokens = re.findall(r"[a-z0-9]+", parsed_key)
        if len(parsed_tokens) < 8 or len(existing_tokens) < len(parsed_tokens):
            return False
        if len(parsed_tokens) / max(1, len(existing_tokens)) < 0.35:
            return False

        matcher = difflib.SequenceMatcher(
            None, existing_tokens, parsed_tokens, autojunk=False
        )
        blocks = [block for block in matcher.get_matching_blocks() if block.size]
        matched_tokens = sum(block.size for block in blocks)
        longest_block = max((block.size for block in blocks), default=0)
        if not blocks:
            return False
        tail = blocks[-1]
        reaches_parsed_end = tail.b + tail.size >= len(parsed_tokens) - 1
        reaches_existing_end = tail.a + tail.size >= len(existing_tokens) - 1
        return (
            matched_tokens / len(parsed_tokens) >= 0.75
            and longest_block >= 6
            and reaches_parsed_end
            and reaches_existing_end
        )

    def _apply_existing_form(self, result: ParsedDocument, form: FormSnapshot | None) -> ParsedDocument:
        """Reconcile OCR with fields already stored by the website.

        A completed record often contains a clean, authoritative value while a
        fresh raster OCR pass has a lower numeric confidence.  Use the existing
        value only when it is valid and corroborates the OCR/structure; never let
        a visibly corrupted old abstract overwrite a good OCR result.
        """
        if form is None:
            return result

        existing_number = (form.document_number or "").strip()
        existing_symbol = self.normalizer.normalize_symbol(form.symbol)
        existing_type = (form.document_type or "").strip()
        existing_date = (form.document_date or "").strip()
        existing_signer = re.sub(r"\s+", " ", form.signer_name or "").strip()
        existing_security = re.sub(r"\s+", " ", form.security_level or "").strip()
        existing_author_raw = re.sub(r"\s+", " ", form.author or "").strip()
        existing_author = canonical_author_from_text(
            existing_author_raw,
            existing_author_raw,
            default_author="",
        )
        existing_abstract = self.normalizer.clean_abstract(
            self.normalizer.normalize_text(form.abstract)
        )
        if result.document_type.value == "Tờ trình":
            existing_abstract = self._repair_to_trinh_abstract(existing_abstract)
        elif result.document_type.value == "Thông báo":
            existing_abstract = self._repair_thong_bao_abstract(existing_abstract)
        elif result.document_type.value == "Báo cáo":
            existing_abstract = repair_report_title(existing_abstract)
            if report_abstract_is_garbage(existing_abstract):
                existing_abstract = ""
        elif result.document_type.value == "Công văn":
            existing_abstract = clean_cong_van_title(existing_abstract)
        else:
            existing_abstract = self._truncate_at_body_boundary(existing_abstract)

        if re.fullmatch(r"\d{1,6}", existing_number):
            if not result.document_number.value or result.document_number.value == existing_number:
                result.document_number = ParsedField(
                    existing_number,
                    max(0.98, result.document_number.confidence),
                    "existing-form-confirmed:number",
                )

        if re.fullmatch(r"[A-ZĐ0-9]{1,10}(?:/[A-ZĐ0-9]{1,15})+", existing_symbol):
            if not result.symbol.value or result.symbol.value == existing_symbol:
                result.symbol = ParsedField(
                    existing_symbol,
                    max(0.98, result.symbol.confidence),
                    "existing-form-confirmed:symbol",
                )

        placeholder_types = {"", "Khác", "--Tên thể loại văn bản--"}
        if existing_type not in placeholder_types:
            symbol_code = result.symbol.value.split("/", 1)[0].upper() if result.symbol.value else ""
            mapped_type = str(self.type_codes.get(symbol_code, ""))
            if (
                not result.document_type.value
                or existing_type == result.document_type.value
                or existing_type == mapped_type
            ):
                result.document_type = ParsedField(
                    existing_type,
                    max(0.98, result.document_type.confidence),
                    "existing-form-confirmed:type",
                )

        parsed_abstract = self.normalizer.clean_abstract(result.abstract.value)
        if result.document_type.value == "Tờ trình":
            parsed_abstract = self._repair_to_trinh_abstract(parsed_abstract)
            result.abstract = replace(result.abstract, value=parsed_abstract)
        elif result.document_type.value == "Thông báo":
            parsed_abstract = self._repair_thong_bao_abstract(parsed_abstract)
            result.abstract = replace(result.abstract, value=parsed_abstract)
        elif result.document_type.value == "Báo cáo":
            parsed_abstract = repair_report_title(parsed_abstract)
            if report_abstract_is_garbage(parsed_abstract):
                parsed_abstract = ""
            result.abstract = replace(result.abstract, value=parsed_abstract)
        elif result.document_type.value == "Công văn":
            parsed_abstract = clean_cong_van_title(parsed_abstract)
            result.abstract = replace(result.abstract, value=parsed_abstract)
        else:
            parsed_abstract = self._truncate_at_body_boundary(parsed_abstract)
            result.abstract = replace(result.abstract, value=parsed_abstract)
        parsed_is_special_report = (
            result.document_type.value == "Báo cáo"
            and bool(extract_special_report_title(parsed_abstract))
        )
        existing_clean = (
            self._valid_existing(existing_abstract, "abstract")
            and not abstract_has_visible_ocr_corruption(existing_abstract)
        )
        parsed_clean = (
            self._valid_abstract(parsed_abstract)
            and not abstract_has_visible_ocr_corruption(parsed_abstract)
        )
        if result.document_type.value == "Công văn":
            existing_clean = existing_clean and cong_van_title_is_clean(existing_abstract)
            parsed_clean = parsed_clean and cong_van_title_is_clean(parsed_abstract)

        header_fields_confirmed = all(
            "existing-form-confirmed" in field.source_text
            for field in (
                result.document_number,
                result.symbol,
                result.document_type,
            )
        )
        parsed_fragment_corroborates_existing = (
            existing_clean
            and parsed_clean
            and header_fields_confirmed
            and self._existing_abstract_corroborated_by_fragment(
                existing_abstract, parsed_abstract
            )
        )

        report_parsed_authoritative = (
            result.document_type.value == "Báo cáo"
            and bool(parsed_abstract)
            and result.abstract.confidence >= 0.90
            and not report_abstract_is_garbage(parsed_abstract)
        )
        cv_parsed_authoritative = (
            result.document_type.value == "Công văn"
            and bool(parsed_abstract)
            and result.abstract.confidence >= 0.90
            and cong_van_title_is_clean(parsed_abstract)
            and not cong_van_title_looks_truncated(parsed_abstract)
            and fold_vietnamese(parsed_abstract).startswith(("ve ", "v/v ", "bao cao ve "))
        )
        existing_safely_extends_parsed_cv = (
            result.document_type.value == "Công văn"
            and existing_clean
            and parsed_clean
            and header_fields_confirmed
            and cong_van_title_is_safe_extension(existing_abstract, parsed_abstract)
        )

        if existing_safely_extends_parsed_cv:
            # A user-corrected website value must not be shortened again by a
            # fresh OCR pass that recovered only the first wrapped line(s).
            # The extension predicate rejects recipient/body openers, so this
            # does not resurrect old body leakage.
            result.abstract = ParsedField(
                existing_abstract,
                max(0.98, result.abstract.confidence),
                "existing-form-confirmed:abstract-complete-extension",
            )
        elif parsed_fragment_corroborates_existing:
            result.abstract = ParsedField(
                existing_abstract,
                max(0.96, result.abstract.confidence),
                "existing-form-confirmed:abstract-fragment",
            )
        elif report_parsed_authoritative or cv_parsed_authoritative:
            result.abstract = ParsedField(
                parsed_abstract,
                max(0.97, result.abstract.confidence),
                (
                    "bounded-report-header"
                    if report_parsed_authoritative
                    else "bounded-cong-van-header"
                ),
            )
        elif existing_clean and not parsed_clean:
            result.abstract = ParsedField(
                existing_abstract, 0.95, "existing-form-confirmed:abstract-rescue"
            )
        elif existing_clean and parsed_clean:
            similarity = difflib.SequenceMatcher(
                None, fold_vietnamese(existing_abstract), fold_vietnamese(parsed_abstract)
            ).ratio()
            existing_quality = vietnamese_text_quality(existing_abstract)
            parsed_quality = vietnamese_text_quality(parsed_abstract)
            parsed_key = fold_vietnamese(parsed_abstract)
            existing_key = fold_vietnamese(existing_abstract)
            parsed_is_prefix = (
                not parsed_is_special_report
                and len(parsed_key) >= 18
                and existing_key.startswith(parsed_key)
                and len(existing_key) >= len(parsed_key) + 12
            )
            if similarity >= 0.72 or parsed_is_prefix or parsed_is_special_report:
                parsed_is_authoritative = result.abstract.confidence >= 0.90
                if parsed_is_special_report or parsed_is_authoritative:
                    # A bounded title parser is authoritative. A previous run may
                    # have appended prose body to a correct title; never restore
                    # that longer value merely because it starts with the title.
                    chosen = parsed_abstract
                elif parsed_is_prefix:
                    chosen = existing_abstract
                else:
                    chosen = existing_abstract if existing_quality >= parsed_quality else parsed_abstract
                result.abstract = ParsedField(
                    chosen,
                    max(0.95, result.abstract.confidence),
                    "existing-form-confirmed:abstract",
                )
            elif parsed_quality < 0.35 and existing_quality >= 0.45:
                result.abstract = ParsedField(
                    existing_abstract, 0.94, "existing-form-confirmed:abstract-better"
                )
        elif not result.abstract.value and self._valid_existing(existing_abstract, "abstract"):
            # Keep the legacy fallback for incomplete records, but deliberately
            # below the auto-submit threshold when the old value itself is not
            # clean enough to confirm.
            result.abstract = ParsedField(
                existing_abstract, 0.60, "existing-form-unconfirmed"
            )

        if existing_author:
            if not result.author:
                # A syntactically valid existing form value may still be stale
                # (for example a previous ward/city value left on the website).
                # Rescue only when concrete institution facts from the PDF
                # corroborate the existing author and none conflict.
                if existing_author_matches_pdf_evidence(
                    existing_author,
                    result.raw_text,
                ):
                    result.author = existing_author
                    result.author_confidence = 1.0
                    result.author_source_text = "existing-form-confirmed:author-rescue"
                else:
                    result.author_source_text = "existing-form-rejected:author-not-corroborated"
            elif fold_vietnamese(result.author) == fold_vietnamese(existing_author):
                result.author = existing_author
                result.author_confidence = max(1.0, result.author_confidence)
                result.author_source_text = "existing-form-confirmed:author"
            else:
                # PDF header evidence is authoritative on conflicts. Do not let
                # an old but well-formed form value overwrite a newly recovered
                # issuer from the current document.
                result.author_source_text = (
                    f"{result.author_source_text}:existing-form-conflict-ignored"
                    if result.author_source_text
                    else "pdf-author:existing-form-conflict-ignored"
                )

        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", existing_date):
            # Never overwrite a valid date already stored by the website.
            result.document_date = ParsedField(
                existing_date, 1.0, "existing-form-confirmed:document-date"
            )

        if existing_signer and fold_vietnamese(existing_signer) not in {
            "ten nguoi ky van ban", "khong xac dinh"
        }:
            # Existing signer is authoritative; OCR only fills an empty field.
            result.signer_name = ParsedField(
                existing_signer, 1.0, "existing-form-confirmed:signer"
            )

        valid_security = {
            "thuong": "Thường",
            "mat": "Mật",
            "toi mat": "Tối mật",
            "tuyet mat": "Tuyệt mật",
        }
        existing_security_key = fold_vietnamese(existing_security)
        explicit_pdf_security = result.security_source_text.startswith("security-")
        if existing_security_key in valid_security and not explicit_pdf_security:
            # Preserve an already stored classification when the PDF has no
            # explicit secrecy label. This avoids silently downgrading a real
            # classified record merely because OCR missed the marking.
            result.security_level = valid_security[existing_security_key]
            result.security_confidence = 1.0
            result.security_source_text = "existing-form-confirmed:security"

        return result


    @staticmethod
    def _clean_line(line: str) -> str:
        return re.sub(r"\s+", " ", line).strip(" -–—_=*.;: ")

    @staticmethod
    def _remove_type_prefix(line: str, doc_type: str = "") -> str:
        key = fold_vietnamese(line)
        for header, display in DOC_HEADER_MAP.items():
            if doc_type and display != doc_type:
                continue
            if key == header:
                return ""
            if key.startswith(header + " "):
                words = line.split()
                return " ".join(words[len(header.split()) :]).strip(" :–—-")
        return ""

    @staticmethod
    def _is_header_noise(line: str) -> bool:
        key = fold_vietnamese(line)
        return (
            key in URGENCY
            or key.startswith("dang cong san viet nam")
            or key.startswith("dang uy phuong")
            or key.startswith("dang bo thanh pho")
            or bool(re.match(
                r"^(?:[^,]{1,60},\s*)?ngay\s+\d{1,2}\s+thang\s+\d{1,2}\s+nam\s+20\d{2}",
                key,
            ))
            or bool(NUMBER_SYMBOL_RE.fullmatch(line.upper()))
        )

    @staticmethod
    def _is_strong_abstract_boundary(line: str) -> bool:
        if DocumentParser._is_separator(line):
            return True
        key = fold_vietnamese(line)
        if key.startswith((
            "can cu",
            "xet ",
            "dieu 1",
            "kinh gui",
            "noi nhan",
            "thuc hien ke hoach",
            "thuc hien cong van",
            "thuc hien quyet dinh",
            "thuc hien nghi quyet",
        )):
            return True
        return bool(re.match(r"^(?:\d+|[ivxlcdm]+)[.)]\s+", key))

    @staticmethod
    def _is_stop_line(line: str, collected: int) -> bool:
        if DocumentParser._is_separator(line):
            return True
        key = fold_vietnamese(line)
        if key.startswith(STOP_PREFIXES):
            return True
        if re.match(r"^(\d+|[ivx]+)[.)]\s+", key):
            return True
        if collected > 0 and re.match(
            r"^thuc hien\s+(cong van|ke hoach|quyet dinh|nghi quyet)",
            key,
        ):
            return True
        if collected > 0 and "nhu sau" in key and key.startswith(
            ("ban thuong vu", "dang uy", "noi dung")
        ):
            return True
        return False

    @staticmethod
    def _valid_existing(value: str, field: str) -> bool:
        if not value or value in {"...", "-", "--"}:
            return False
        if field == "abstract":
            return len(value) >= 8 and not fold_vietnamese(value).startswith(STOP_PREFIXES)
        return len(value) <= 100

    @staticmethod
    def _valid_abstract(value: str) -> bool:
        if len(value) < 8 or len(value) > 800:
            return False
        key = fold_vietnamese(value)
        return not key.startswith(STOP_PREFIXES) and "trich yeu noi dung" not in key
