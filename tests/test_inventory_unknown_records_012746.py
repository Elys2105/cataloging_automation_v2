from __future__ import annotations

import asyncio
import inspect

from cataloging_tool.automation.pages import (
    DocumentListItem,
    DocumentListPage,
    choose_document_record_url,
    external_id_from_url,
    reported_total_from_texts,
    update_doc_url_from_view,
)


BASE = (
    "https://kholuutru-khoidang.tphcm.gov.vn/"
    "DocumentCataloging/ListDocument?IDProfile=14630&pageIndex=2&pageSize=10"
)


def test_unknown_row_docview_href_is_inventoried() -> None:
    result = choose_document_record_url(
        BASE,
        ["/DocumentCataloging/DocView?id=536681"],
    )
    assert result == (
        "https://kholuutru-khoidang.tphcm.gov.vn/"
        "DocumentCataloging/DocView?id=536681"
    )


def test_unknown_row_docview_inside_onclick_is_inventoried() -> None:
    result = choose_document_record_url(
        BASE,
        ["window.location.href='/DocumentCataloging/DocView?id=536681&amp;mode=0'"],
    )
    assert result.endswith("/DocumentCataloging/DocView?id=536681&mode=0")


def test_javascript_docview_call_is_inventoried() -> None:
    result = choose_document_record_url(
        BASE,
        ["javascript:DocView(536681)"],
    )
    assert result.endswith("/DocumentCataloging/DocView?id=536681")


def test_named_document_id_attribute_is_inventoried() -> None:
    result = choose_document_record_url(
        BASE,
        ['<button class="view" data-document-id="536681"></button>'],
    )
    assert result.endswith("/DocumentCataloging/DocView?id=536681")


def test_update_route_is_preferred_when_row_has_view_and_edit() -> None:
    result = choose_document_record_url(
        BASE,
        [
            "/DocumentCataloging/DocView?id=536681",
            "/DocumentCataloging/UpdateDoc?id=536681",
        ],
    )
    assert "/UpdateDoc?id=536681" in result


def test_docview_can_be_derived_to_update_route_without_losing_id() -> None:
    source = (
        "https://kholuutru-khoidang.tphcm.gov.vn/"
        "DocumentCataloging/DocView?id=536681&mode=0"
    )
    assert update_doc_url_from_view(source) == (
        "https://kholuutru-khoidang.tphcm.gov.vn/"
        "DocumentCataloging/UpdateDoc?id=536681&mode=0"
    )


def test_external_id_accepts_site_query_key_variants() -> None:
    assert external_id_from_url("https://host/DocView?ID=536681") == "536681"
    assert external_id_from_url("https://host/DocView?IDDocument=536681") == "536681"


def test_site_total_label_is_read_without_confusing_total_pdf_pages() -> None:
    body = (
        "Tổng số lượng trang trong hồ sơ 212 "
        "Danh sách thành phần hồ sơ Có tổng cộng 29 bản ghi"
    )
    assert reported_total_from_texts([body]) == 29
    assert reported_total_from_texts(["1 - 10 của 29"]) == 29


def test_inventory_no_longer_depends_only_on_updatedoc_links() -> None:
    inventory_source = inspect.getsource(DocumentListPage.inventory_all)
    row_source = inspect.getsource(DocumentListPage._row_document_url)
    open_source = inspect.getsource(DocumentListPage.open_record)
    total_source = inspect.getsource(DocumentListPage._reported_total_records)

    assert "_row_document_url" in inventory_source
    assert "outerHTML" in row_source
    assert "DocView" in row_source or "choose_document_record_url" in row_source
    assert "docview" in open_source.casefold()
    assert "Chỉnh sửa" in open_source
    assert 'locator("body")' in total_source


class _BodyLocator:
    async def wait_for(self, **_kwargs) -> None:
        return None


class _InterruptedNavigationPage:
    def __init__(self) -> None:
        self.url = "https://example.test/DocumentCataloging/DocView?id=111111"
        self.goto_calls = 0
        self.locator_selectors: list[str] = []

    async def evaluate(self, _script: str):
        return "complete"

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        await asyncio.sleep(0)

    async def goto(self, url: str, **_kwargs) -> None:
        self.goto_calls += 1
        if self.goto_calls == 1:
            raise RuntimeError("interrupted by another navigation")
        self.url = url

    def locator(self, selector: str):
        self.locator_selectors.append(selector)
        assert selector == "body"
        return _BodyLocator()


def test_transient_update_navigation_retries_without_clicking_stale_docview() -> None:
    page = _InterruptedNavigationPage()
    item = DocumentListItem(
        external_id="536069",
        edit_url="https://example.test/DocumentCataloging/UpdateDoc?id=536069",
        row_text="",
        position=1,
    )

    asyncio.run(DocumentListPage(page).open_record(item))

    assert page.goto_calls == 2
    assert page.url.endswith("/DocumentCataloging/UpdateDoc?id=536069")
    assert page.locator_selectors == ["body"]
