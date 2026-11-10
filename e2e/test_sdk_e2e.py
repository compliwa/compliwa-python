"""The library against a real Compliwa API — your local one, with a TEST key (sandbox, never charged).

    set COMPLIWA_API_KEY=cw_test_…                 (Windows Command Prompt; export … on macOS/Linux)
    set COMPLIWA_BASE_URL=http://localhost:5010    (the default here)
    python -m pytest e2e

Refuses a live key: these calls create verifications and screenings.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict

import pytest

from compliwa import (
    API_VERSION,
    AsyncCompliwa,
    AuthenticationError,
    Compliwa,
    InvalidRequestError,
    NotFoundError,
    get_last_response,
)

KEY = os.environ.get("COMPLIWA_API_KEY", "")
BASE_URL = os.environ.get("COMPLIWA_BASE_URL", "http://localhost:5010")

if not KEY.startswith("cw_test_"):
    pytest.exit(
        "Set COMPLIWA_API_KEY to a cw_test_ key (dashboard → API keys → Create key, environment Test).",
        returncode=1,
    )


@pytest.fixture(scope="module")
def client() -> Any:
    with Compliwa(KEY, base_url=BASE_URL, app_info={"name": "compliwa-python-e2e"}) as c:
        yield c


@pytest.fixture(scope="module")
def sandbox(client: Compliwa) -> Dict[str, Any]:
    return dict(client.request("GET", "/v1/sandbox"))


def person(sandbox: Dict[str, Any]) -> Dict[str, Any]:
    nin = next(c for c in sandbox["identity"]["checks"] if c["check"] == "NG:NIN")
    found = next(e for e in nin["entries"] if e["effect"] == "found_example")
    who = {k: v for k, v in sandbox["identity"]["example_person"].items() if k != "middle_name"}
    return {"check": "NG:NIN", "id_number": found["id_number"], **who, "consent": True}


def test_the_key(client: Compliwa) -> None:
    key = client.api_key.retrieve()
    facts = get_last_response(key)
    assert key["environment"] == "test"
    assert facts is not None and facts.environment == "test" and facts.request_id
    assert facts.api_version == API_VERSION, "the library was generated from this API version"


def test_a_verification_replayed_read_and_listed(client: Compliwa, sandbox: Dict[str, Any]) -> None:
    reference = f"sdk-py-{uuid.uuid4().hex[:8]}"
    params = {**person(sandbox), "reference": reference}
    key = str(uuid.uuid4())
    created = client.verifications.create(params, idempotency_key=key)  # type: ignore[arg-type]
    assert created["id"].startswith("ver_")
    replay = client.verifications.create(params, idempotency_key=key)  # type: ignore[arg-type]
    assert replay["id"] == created["id"]
    facts = get_last_response(replay)
    assert facts is not None and facts.idempotent_replayed
    assert client.verifications.retrieve(created["id"])["id"] == created["id"]
    assert [v["id"] for v in client.verifications.list({"reference": reference, "limit": 1})] == [
        created["id"]
    ]


def test_a_screening(client: Compliwa) -> None:
    client.screenings.lists.list()
    screening = client.screenings.create({"type": "person", "name": "Ada Okafor"})
    assert screening["id"].startswith("scr_")
    assert client.screenings.retrieve(screening["id"])["id"] == screening["id"]


def test_errors(client: Compliwa) -> None:
    with pytest.raises(InvalidRequestError) as invalid:
        client.verifications.create({"check": "NG:NIN"})  # type: ignore[typeddict-item]
    assert invalid.value.status == 400 and invalid.value.errors and invalid.value.request_id
    with pytest.raises(NotFoundError):
        client.verifications.retrieve("ver_00000000000000000000000000000000")
    with pytest.raises(AuthenticationError) as unauthorized:
        Compliwa("cw_test_" + "x" * 40, base_url=BASE_URL).api_key.retrieve()
    assert unauthorized.value.code == "api_key_invalid"


def test_async_and_french(sandbox: Dict[str, Any]) -> None:
    async def run() -> None:
        async with AsyncCompliwa(KEY, base_url=BASE_URL, language="fr") as client:
            created = await client.verifications.create(person(sandbox))  # type: ignore[arg-type]
            assert created["id"].startswith("ver_")
            first = await client.verifications.list({"limit": 1})
            assert len(first.data) == 1
            with pytest.raises(InvalidRequestError) as invalid:
                await client.verifications.create({})  # type: ignore[typeddict-item]
            assert invalid.value.title

    asyncio.run(run())
