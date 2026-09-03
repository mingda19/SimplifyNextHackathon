"""Standard domain exceptions and FastAPI exception handlers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas import DomainErrorResponse


Alternative = Mapping[str, Any]


class DomainErrorCode(str, Enum):
    """Stable machine-readable error codes emitted by this service."""

    OUT_OF_STOCK = "OUT_OF_STOCK"
    MOQ_NOT_MET = "MOQ_NOT_MET"
    LEAD_TIME_EXCEEDED = "LEAD_TIME_EXCEEDED"
    LOT_EXPIRED = "LOT_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    HTTP_ERROR = "HTTP_ERROR"


class DomainError(Exception):
    """An expected business failure that maps directly to the error envelope."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str | DomainErrorCode,
        message: str,
        remedy_hint: str,
        alternatives: Sequence[Alternative] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code.value if isinstance(code, DomainErrorCode) else code
        self.message = message
        self.remedy_hint = remedy_hint
        self.alternatives = [dict(alternative) for alternative in alternatives or ()]
        self.headers = dict(headers or {})

    def as_response_model(self) -> DomainErrorResponse:
        """Build the exact four-key public response model."""

        return DomainErrorResponse(
            code=self.code,
            message=self.message,
            remedy_hint=self.remedy_hint,
            alternatives=self.alternatives,
        )


class OutOfStockError(DomainError):
    """The selected vendor cannot fulfil the requested SKU quantity."""

    def __init__(
        self,
        *,
        message: str = "The selected vendor does not have enough stock.",
        remedy_hint: str = "Choose a stocked alternative vendor or reduce the quantity.",
        alternatives: Sequence[Alternative] | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code=DomainErrorCode.OUT_OF_STOCK,
            message=message,
            remedy_hint=remedy_hint,
            alternatives=alternatives,
        )


class MoqNotMetError(DomainError):
    """The requested quantity is below the vendor's minimum order."""

    def __init__(
        self,
        *,
        message: str = "The requested quantity is below the vendor minimum order.",
        remedy_hint: str = "Raise the quantity to the MOQ or choose another vendor.",
        alternatives: Sequence[Alternative] | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=DomainErrorCode.MOQ_NOT_MET,
            message=message,
            remedy_hint=remedy_hint,
            alternatives=alternatives,
        )


# Preserve the domain acronym for callers that prefer the all-caps spelling.
MOQNotMetError = MoqNotMetError


class LeadTimeExceededError(DomainError):
    """The vendor would arrive after projected stockout."""

    def __init__(
        self,
        *,
        message: str = "The vendor lead time exceeds the remaining stock cover.",
        remedy_hint: str = "Choose a faster vendor or revise the replenishment plan.",
        alternatives: Sequence[Alternative] | None = None,
    ) -> None:
        super().__init__(
            status_code=422,
            code=DomainErrorCode.LEAD_TIME_EXCEEDED,
            message=message,
            remedy_hint=remedy_hint,
            alternatives=alternatives,
        )


class LotExpiredError(DomainError):
    """Allocation was attempted against an expired lot."""

    def __init__(
        self,
        *,
        message: str = "The selected inventory lot has expired.",
        remedy_hint: str = "Allocate from a non-expired lot for the same SKU.",
        alternatives: Sequence[Alternative] | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_410_GONE,
            code=DomainErrorCode.LOT_EXPIRED,
            message=message,
            remedy_hint=remedy_hint,
            alternatives=alternatives,
        )


class RateLimitedError(DomainError):
    """A resettable local limiter asked the caller to retry later."""

    def __init__(
        self,
        *,
        retry_after_seconds: int,
        message: str = "Too many requests were made for this operation.",
        remedy_hint: str = "Wait for Retry-After seconds, then retry the request.",
        alternatives: Sequence[Alternative] | None = None,
    ) -> None:
        if retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must be non-negative")
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code=DomainErrorCode.RATE_LIMITED,
            message=message,
            remedy_hint=remedy_hint,
            alternatives=alternatives,
            headers={"Retry-After": str(retry_after_seconds)},
        )


class NotFoundError(DomainError):
    """A requested inventory resource does not exist."""

    def __init__(
        self,
        *,
        message: str,
        remedy_hint: str = "Check the identifier and retry the request.",
        alternatives: Sequence[Alternative] | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code=DomainErrorCode.NOT_FOUND,
            message=message,
            remedy_hint=remedy_hint,
            alternatives=alternatives,
        )


async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    """Serialize a business exception without leaking implementation details."""

    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(exc.as_response_model()),
        headers=exc.headers,
    )


async def request_validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Keep framework request-validation failures inside the same envelope."""

    invalid_fields = sorted(
        {".".join(str(part) for part in error["loc"]) for error in exc.errors()}
    )
    response = DomainErrorResponse(
        code=DomainErrorCode.VALIDATION_ERROR.value,
        message="The request did not match the expected contract.",
        remedy_hint="Correct the listed fields and retry the request.",
        alternatives=[{"action": "correct_request", "fields": invalid_fields}],
    )
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(response),
    )


async def http_exception_handler(
    _request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Normalize FastAPI HTTP exceptions such as route-level 404 responses."""

    code_by_status = {
        status.HTTP_404_NOT_FOUND: DomainErrorCode.NOT_FOUND,
        status.HTTP_405_METHOD_NOT_ALLOWED: DomainErrorCode.METHOD_NOT_ALLOWED,
        status.HTTP_503_SERVICE_UNAVAILABLE: DomainErrorCode.SERVICE_UNAVAILABLE,
    }
    code = code_by_status.get(exc.status_code, DomainErrorCode.HTTP_ERROR)
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    response = DomainErrorResponse(
        code=code.value,
        message=message,
        remedy_hint="Review the request and retry, or use an advertised alternative.",
        alternatives=[],
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(response),
        headers=exc.headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register all standardized handlers on an application instance."""

    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    # Starlette owns routing-level 404/405 exceptions; FastAPI's HTTPException
    # is a subclass, so this one registration normalizes both kinds.
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
