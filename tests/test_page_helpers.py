from cataloging_tool.automation.pages import DocumentListPage, external_id_from_url, normalize_lookup


def test_external_id() -> None:
    assert external_id_from_url("https://x/UpdateDoc?id=77") == "77"


def test_status_prefers_not_completed() -> None:
    assert DocumentListPage._extract_status("Bản ghi Chưa hoàn thành") == "Chưa hoàn thành"
    assert DocumentListPage._extract_status("Bản ghi Hoàn thành") == "Hoàn thành"


def test_normalize_profile_code_spacing() -> None:
    assert normalize_lookup(" A29. 125.001 – 10 ") == "a29.125.001-10"
    assert normalize_lookup("A29.125.001-10") == "a29.125.001-10"

from cataloging_tool.automation.pages import ProfileCandidate, choose_profile_candidate


def test_choose_profile_candidate_uses_text_content_normalization() -> None:
    candidates = [
        ProfileCandidate(index=0, text="A29. 125.001 – 10  Tập lưu hồ sơ", href="/DocumentCataloging/ListDocument?IDProfile=7"),
        ProfileCandidate(index=1, text="A29.125.001-11  Hồ sơ khác", href="/DocumentCataloging/ListDocument?IDProfile=8"),
    ]
    selected = choose_profile_candidate(candidates, "A29.125.001-10")
    assert selected is not None
    assert selected.index == 0

import asyncio

from cataloging_tool.automation.pages import DocumentEditPage
from cataloging_tool.domain.errors import SubmissionError


class MissingNumberDocumentEditPage(DocumentEditPage):
    async def _read_field(self, label: str) -> str:
        if label == "Số văn bản":
            raise SubmissionError("missing", step="find_form_field")
        return label


def test_read_form_tolerates_missing_existing_fields() -> None:
    page = MissingNumberDocumentEditPage(page=object(), pdf_acquirer=None)  # type: ignore[arg-type]
    snapshot = asyncio.run(page.read_form())
    assert snapshot.document_number == ""
    assert snapshot.symbol == "Ký hiệu văn bản"
