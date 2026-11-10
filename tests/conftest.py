"""A scripted API: every request is recorded, every answer comes from the script — no network."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
import pytest

from compliwa import AsyncCompliwa, Compliwa

TEST_KEY = "cw_test_" + "a" * 40


@dataclass
class Step:
    status: int = 200
    body: Any = None
    headers: Dict[str, str] = field(default_factory=dict)
    raises: Optional[Exception] = None


class Script:
    def __init__(self, *steps: Step) -> None:
        self.steps = list(steps)
        self.calls: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if not self.steps:
            raise AssertionError(f"no answer scripted for {request.method} {request.url}")
        step = self.steps.pop(0)
        if step.raises:
            raise step.raises
        content = (
            b""
            if step.body is None
            else (step.body.encode() if isinstance(step.body, str) else json.dumps(step.body).encode())
        )
        headers = {"content-type": "application/json", **step.headers}
        return httpx.Response(step.status, content=content, headers=headers)

    def body(self, n: int) -> Any:
        content = self.calls[n].content
        return json.loads(content) if content else None


def make(script: Script, **options: Any) -> Compliwa:
    client = Compliwa(
        TEST_KEY,
        base_url="https://api.test",
        http_client=httpx.Client(transport=httpx.MockTransport(script)),
        **options,
    )
    client.sleeps = []  # type: ignore[attr-defined]
    client._sleep = client.sleeps.append  # type: ignore[attr-defined,assignment]
    return client


def make_async(script: Script, **options: Any) -> AsyncCompliwa:
    client = AsyncCompliwa(
        TEST_KEY,
        base_url="https://api.test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(script)),
        **options,
    )
    sleeps: List[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client.sleeps = sleeps  # type: ignore[attr-defined]
    client._sleep = sleep  # type: ignore[assignment]
    return client


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COMPLIWA_API_KEY", raising=False)
    monkeypatch.delenv("COMPLIWA_BASE_URL", raising=False)
