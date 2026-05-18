"""Stable API business error codes."""

from __future__ import annotations

from fastapi import HTTPException


class ErrorCode:
    """String constants used by the frontend and API clients."""

    BAD_REQUEST = "request.bad_request"
    VALIDATION_FAILED = "request.validation_failed"
    AUTH_REQUIRED = "auth.required"
    AUTH_INVALID_CREDENTIALS = "auth.invalid_credentials"
    AUTH_FORBIDDEN = "auth.forbidden"
    AUTH_ALREADY_BOOTSTRAPPED = "auth.already_bootstrapped"
    RESOURCE_NOT_FOUND = "resource.not_found"
    ORDER_NOT_FOUND = "order.not_found"
    ORDER_CANCEL_FAILED = "order.cancel_failed"
    ORDER_STATUS_NOT_CANCELLABLE = "order.status_not_cancellable"
    ORDER_EXECUTION_FAILED = "order.execution_failed"
    ORDER_REJECTED = "order.rejected"
    RISK_REJECTED = "risk.rejected"
    STRATEGY_NOT_FOUND = "strategy.not_found"
    STRATEGY_CONFIG_INVALID = "strategy.config_invalid"
    INTERNAL_SERVER_ERROR = "server.internal_error"


HTTP_STATUS_ERROR_CODES = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.AUTH_REQUIRED,
    403: ErrorCode.AUTH_FORBIDDEN,
    404: ErrorCode.RESOURCE_NOT_FOUND,
}


class ApiError(HTTPException):
    """HTTP exception carrying a stable business error code."""

    def __init__(
        self,
        status_code: int,
        message: str,
        error_code: str,
        *,
        details=None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail={
                "message": str(message),
                "error_code": str(error_code),
                "details": details,
            },
            headers=headers,
        )


def default_error_code_for_status(status_code: int) -> str:
    """Return the default business code for a bare HTTP status."""
    return HTTP_STATUS_ERROR_CODES.get(int(status_code), f"http.{int(status_code)}")
