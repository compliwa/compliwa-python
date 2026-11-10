"""Per-call options, accepted by every method as keyword arguments."""

from __future__ import annotations

from typing import Mapping

from typing_extensions import TypedDict


class RequestOptions(TypedDict, total=False):
    idempotency_key: str
    """Your own Idempotency-Key (8–255 visible ASCII characters). One is made for you when the
    operation is idempotent; yours makes a retry safe across restarts too."""
    timeout: float
    """Seconds for this call's attempts (default: the client's, 30)."""
    max_retries: int
    """Retries after the first attempt, when retrying is safe (default: the client's, 2)."""
    extra_headers: Mapping[str, str]
