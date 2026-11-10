"""Every failure is a CompliwaError, carrying what the API said (RFC 9457 problem details).

    err.status       the HTTP status (0 when no answer came)
    err.code         Compliwa's stable code — branch on this ("api_key_invalid", "scope_missing" …)
    err.title        a short sentence, in the language you asked for
    err.detail       what went wrong and how to fix it
    err.errors       for a 400: [{"path": ..., "message": ...}] per field
    err.request_id   X-Request-Id — quote it to Compliwa support
    err.retry_after  seconds, when the API said to wait
    err.body         the answer's body as sent

Kinds, so you can catch only what you handle:
    AuthenticationError 401 · PermissionDeniedError 403 · NotFoundError 404 · ConflictError 409 ·
    InvalidRequestError 400 / 422 · RateLimitError 429 · APIError 5xx and anything else ·
    APIConnectionError (no answer) and its APITimeoutError · WebhookSignatureError
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class CompliwaError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: Optional[str] = None,
        title: Optional[str] = None,
        detail: Optional[str] = None,
        errors: Optional[List[Dict[str, Any]]] = None,
        request_id: Optional[str] = None,
        retry_after: Optional[int] = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.errors: List[Dict[str, Any]] = errors or []
        self.request_id = request_id
        self.retry_after = retry_after
        self.body = body

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status}, code={self.code!r}, message={self.message!r})"


class AuthenticationError(CompliwaError):
    """401 — the key is missing, malformed, revoked or expired."""


class PermissionDeniedError(CompliwaError):
    """403 — the key lacks a scope (scope_missing), or the action is for a person."""


class NotFoundError(CompliwaError):
    """404."""


class ConflictError(CompliwaError):
    """409 — the object is not in a state that allows this."""


class InvalidRequestError(CompliwaError):
    """400 or 422 — fix the request; `errors` says which fields."""


class RateLimitError(CompliwaError):
    """429 after the retries — `retry_after` says how long to wait."""


class APIError(CompliwaError):
    """5xx after the retries, or any other unexpected answer."""


class APIConnectionError(CompliwaError):
    """No answer came: the network, DNS, TLS — or, for APITimeoutError, the time ran out."""


class APITimeoutError(APIConnectionError):
    """No answer within the timeout."""


class WebhookSignatureError(CompliwaError):
    """verify_webhook() refused the request: not signed by Compliwa, changed, or too old."""


_BY_STATUS = {
    400: InvalidRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: InvalidRequestError,
    429: RateLimitError,
}


def error_from_response(
    status: int, body: Any, *, request_id: Optional[str], retry_after: Optional[int]
) -> CompliwaError:
    problem = body if isinstance(body, dict) else {}
    kind = _BY_STATUS.get(status, APIError)
    title = problem.get("title")
    detail = problem.get("detail")
    if detail is None and isinstance(body, str) and body:
        detail = body[:300]
    message = ": ".join(part for part in (title, detail) if part) or f"The Compliwa API answered {status}"
    errors = problem.get("errors")
    return kind(
        message,
        status=status,
        code=problem.get("code"),
        title=title,
        detail=detail,
        errors=errors if isinstance(errors, list) else [],
        request_id=request_id,
        retry_after=retry_after,
        body=body,
    )
