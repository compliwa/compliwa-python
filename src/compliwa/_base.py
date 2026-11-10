"""What the sync and async clients share: the key, the headers, and when a retry is safe.

- Authorization: Bearer <key>; a cw_test_ key reaches the sandbox, a cw_live_ key real customers
- a write the API makes idempotent (x-sdk `idempotent`) carries an Idempotency-Key — made for you,
  or yours — the SAME on every retry, so a check is never run or charged twice
- retried, with back-off and jitter, only when safe and useful:
    reads and idempotent writes   no answer, 429, 409 idempotency_key_in_use, 500 / 502 / 503 / 504
    any other write               429 only (refused before it ran); after a lost answer the error
                                  says it may or may not have run
  waiting as long as Retry-After says (at most a minute). Never on another 4xx.
"""

from __future__ import annotations

import email.utils
import json
import os
import platform
import random
import re
import time
import uuid
from typing import Any, Dict, Mapping, Optional, Tuple

import httpx

from ._errors import APIConnectionError, APITimeoutError, CompliwaError, error_from_response
from ._version import VERSION

DEFAULT_BASE_URL = "https://api.compliwa.com"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2
MAX_RETRY_AFTER = 60.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_KEY_SHAPE = re.compile(r"^cw_(test|live)_[A-Za-z0-9_-]{8,}$")


def resolve_api_key(api_key: Optional[str]) -> str:
    key = api_key if api_key is not None else os.environ.get("COMPLIWA_API_KEY")
    if not key:
        raise CompliwaError(
            "No API key: pass one, or set COMPLIWA_API_KEY (create one in the dashboard: API keys)."
        )
    if not _KEY_SHAPE.match(key):
        hint = (
            " That is a webhook signing secret: it goes to verify_webhook(), not here."
            if key.startswith("whsec_")
            else ""
        )
        raise CompliwaError(f"An API key starts with cw_test_ or cw_live_.{hint}")
    return key


def user_agent(app_info: Optional[Mapping[str, str]]) -> str:
    agent = f"compliwa-python/{VERSION} python/{platform.python_version()} httpx/{httpx.__version__}"
    if app_info and app_info.get("name"):
        agent += f" {app_info['name']}" + (f"/{app_info['version']}" if app_info.get("version") else "")
    return agent


def backoff(attempt: int) -> float:
    """Seconds before retry `attempt` (1, 2 …): 0.5, 1, 2 … at most 8, ±25%."""
    base = min(0.5 * 2.0 ** (attempt - 1), 8.0)
    return base * (0.75 + random.random() * 0.5)


def retry_after_seconds(header: Optional[str]) -> Optional[float]:
    if not header:
        return None
    try:
        return max(0.0, float(header))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


def clean_query(params: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            out[key] = [str(v) for v in value]
        else:
            out[key] = value
    return out


class RequestPlan:
    """One logical call: everything that stays the same across its attempts."""

    def __init__(
        self,
        *,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[bytes],
        query: Dict[str, Any],
        retry_safe: bool,
        max_retries: int,
        timeout: float,
    ) -> None:
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.query = query
        self.retry_safe = retry_safe
        self.max_retries = max_retries
        self.timeout = timeout

    def connection_error(self, cause: Exception) -> CompliwaError:
        unknown = (
            "" if self.retry_safe else " — it may or may not have run: read it back before sending it again"
        )
        if isinstance(cause, httpx.TimeoutException):
            error: CompliwaError = APITimeoutError(
                f"No answer from the Compliwa API within {self.timeout:g} s{unknown}", code="timeout"
            )
        else:
            error = APIConnectionError(
                f"Could not reach the Compliwa API: {cause}{unknown}", code="connection_failed"
            )
        error.__cause__ = cause
        return error

    def judge(
        self, response: httpx.Response, attempt: int
    ) -> Tuple[Any, Optional[float], Optional[CompliwaError]]:
        """(parsed body, seconds to wait before retrying or None, the error to raise or None)."""
        parsed: Any = None
        if response.content:
            try:
                parsed = json.loads(response.content)
            except ValueError:
                parsed = response.text
        if response.is_success:
            return parsed if parsed is not None else {}, None, None

        wait = retry_after_seconds(response.headers.get("retry-after"))
        in_use = (
            response.status_code == 409
            and isinstance(parsed, dict)
            and parsed.get("code") == "idempotency_key_in_use"
        )
        retryable = response.status_code == 429 or (
            self.retry_safe and (response.status_code in RETRY_STATUSES or in_use)
        )
        if retryable and attempt < self.max_retries and (wait is None or wait <= MAX_RETRY_AFTER):
            return parsed, wait if wait is not None else backoff(attempt + 1), None
        error = error_from_response(
            response.status_code,
            parsed,
            request_id=response.headers.get("x-request-id"),
            retry_after=None if wait is None else int(-(-wait // 1)),
        )
        return parsed, None, error


class BaseClient:
    def __init__(
        self,
        api_key: Optional[str],
        *,
        base_url: Optional[str],
        timeout: Optional[float],
        max_retries: Optional[int],
        language: Optional[str],
        app_info: Optional[Mapping[str, str]],
    ) -> None:
        self._api_key = resolve_api_key(api_key)
        self.base_url = (base_url or os.environ.get("COMPLIWA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = DEFAULT_TIMEOUT if timeout is None else float(timeout)
        self.max_retries = DEFAULT_MAX_RETRIES if max_retries is None else int(max_retries)
        self.language = language
        self._user_agent = user_agent(app_info)

    @property
    def environment(self) -> str:
        """'test' (sandbox, never charged) or 'live' — decided by the key."""
        return "live" if self._api_key.startswith("cw_live_") else "test"

    def __repr__(self) -> str:  # never the key
        return f"{type(self).__name__}(environment={self.environment!r}, base_url={self.base_url!r})"

    def _plan(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: Optional[Mapping[str, Any]] = None,
        idempotent: bool = False,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> RequestPlan:
        method = method.upper()
        if not path.startswith("/"):
            raise ValueError("The path starts with /, e.g. /v1/verifications")
        safe = method in ("GET", "HEAD")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": self._user_agent,
        }
        if self.language:
            headers["Accept-Language"] = self.language
        payload: Optional[bytes] = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if not safe:
            key = idempotency_key or (str(uuid.uuid4()) if idempotent else None)
            if key:
                headers["Idempotency-Key"] = key
        headers.update(extra_headers or {})
        return RequestPlan(
            method=method,
            url=f"{self.base_url}{path}",
            headers=headers,
            body=payload,
            query=clean_query(query),
            retry_safe=safe or idempotent,
            max_retries=self.max_retries if max_retries is None else max_retries,
            timeout=self.timeout if timeout is None else float(timeout),
        )
