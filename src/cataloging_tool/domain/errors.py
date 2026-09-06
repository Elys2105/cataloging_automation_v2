from __future__ import annotations

import re


def _default_error_code(name: str) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()
    return value.removesuffix("_ERROR") + "_ERROR"


def error_code_for_exception(exc: Exception) -> str:
    return str(getattr(exc, "error_code", "") or _default_error_code(type(exc).__name__))


class CatalogingError(Exception):
    def __init__(
        self,
        message: str,
        *,
        step: str = "",
        retryable: bool = False,
        record_id: int | None = None,
        code: str = "",
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.step = step
        self.retryable = retryable
        self.record_id = record_id
        self.error_code = code.strip().upper() or _default_error_code(type(self).__name__)
        self.field = field


class BrowserNavigationError(CatalogingError):
    pass


class AuthenticationExpiredError(CatalogingError):
    pass


class ProfileNotFoundError(CatalogingError):
    pass


class ProfileInUseError(CatalogingError):
    pass


class WorkItemInUseError(CatalogingError):
    pass


class DocumentNotFoundError(CatalogingError):
    pass


class PdfAcquisitionError(CatalogingError):
    pass


class PdfRenderError(CatalogingError):
    pass


class OcrError(CatalogingError):
    pass


class ParseError(CatalogingError):
    pass


class DocumentValidationError(CatalogingError):
    pass


class SubmissionError(CatalogingError):
    pass


class SubmissionUncertainError(CatalogingError):
    pass


class VerificationError(CatalogingError):
    pass


class OperationCancelledError(CatalogingError):
    pass
