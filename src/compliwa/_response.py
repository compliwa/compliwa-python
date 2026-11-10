"""What a successful call returns: the parsed JSON — a plain dict you read with ["key"] — plus the
answer's facts on `last_response` (also reachable, fully typed, with get_last_response(obj))."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx


@dataclass(frozen=True)
class LastResponse:
    status: int
    request_id: Optional[str]
    environment: Optional[str]
    """'test' or 'live': which data the key reached."""
    api_version: Optional[str]
    idempotent_replayed: bool
    """True when this is the stored answer to an earlier call with the same Idempotency-Key."""
    headers: Dict[str, str] = field(repr=False)

    @classmethod
    def of(cls, response: httpx.Response) -> LastResponse:
        h = response.headers
        return cls(
            status=response.status_code,
            request_id=h.get("x-request-id"),
            environment=h.get("compliwa-environment"),
            api_version=h.get("compliwa-api-version"),
            idempotent_replayed=h.get("idempotent-replayed") == "true",
            headers=dict(h.items()),
        )


class ApiDict(Dict[str, Any]):
    """A dict, exactly as the API sent it — with the answer's facts on `.last_response`."""

    last_response: Optional[LastResponse] = None


def wrap(data: Any, response: httpx.Response) -> Any:
    if isinstance(data, dict):
        result = ApiDict(data)
        result.last_response = LastResponse.of(response)
        return result
    return data


def get_last_response(obj: Any) -> Optional[LastResponse]:
    """The facts of the answer that produced `obj` (a result or a page), or None."""
    return getattr(obj, "last_response", None)
