"""Checked by `mypy` (strict), never run: proves the published types say what the library does."""

from __future__ import annotations

from typing import Optional

from compliwa import AsyncCompliwa, Compliwa, CompliwaError, LastResponse, get_last_response, verify_webhook
from compliwa.types import Verification


def sync_usage(client: Compliwa) -> None:
    verification: Verification = client.verifications.create({"check": "NG:NIN", "id_number": "12345678901"})
    outcome = verification["outcome"]
    facts: Optional[LastResponse] = get_last_response(verification)

    page = client.verifications.list({"limit": 10})
    first: Verification = page.data[0]
    for item in client.verifications.list({"status": "completed"}):
        reveal_id: str = item["id"]

    transfer = client.travel_rule.transfers.retrieve("trt_1")
    status: str = transfer["status"]

    client.transactions.list({"from": "2026-01-01"})

    client.cases.retrieve()  # type: ignore[call-arg]
    client.checks.create({})  # type: ignore[attr-defined]
    client.verifications.create({"check": "XX:NOPE", "id_number": "1"})  # type: ignore[typeddict-item]

    try:
        client.api_key.retrieve(timeout=5)
    except CompliwaError as error:
        code: Optional[str] = error.code

    event = verify_webhook(b"{}", "t=1,v1=00", "whsec_x")
    del outcome, facts, first, reveal_id, status, code, event


async def async_usage(client: AsyncCompliwa) -> None:
    verification: Verification = await client.verifications.create({"check": "NG:NIN", "id_number": "1"})
    page = await client.verifications.list()
    async for item in client.verifications.list():
        verification = item
    del verification, page
