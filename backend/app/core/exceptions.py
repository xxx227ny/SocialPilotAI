import logging
from dataclasses import asdict, dataclass
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SafeProviderFailure:
    """Strict allowlist for provider failure details exposed over HTTP."""

    provider: Literal["qwen", "wanx"]
    phase: Literal["connect", "request", "response", "schema", "delivery"]
    provider_http_status: int | None
    safe_error_code: str
    request_id_digest: str | None
    uncertain: bool
    potentially_billable: bool
    occurred_at: str

    def as_public_dict(self) -> dict[str, object]:
        return asdict(self)


class AppError(Exception):
    """Base exception for expected application errors."""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        *,
        provider_failure: SafeProviderFailure | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.provider_failure = provider_failure
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        error: dict[str, object]
        if exc.provider_failure is not None:
            error = exc.provider_failure.as_public_dict()
        else:
            error = {"message": exc.message}
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": error},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled application error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "服务暂时不可用，请稍后重试"}},
        )
