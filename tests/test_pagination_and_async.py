from __future__ import annotations

import asyncio
from typing import Any, List, Optional

import httpx
import pytest
from conftest import Script, Step, make, make_async

from compliwa import InvalidRequestError, RangeError, get_last_response


def page(ids: List[str], nxt: Optional[str] = None) -> Any:
    return {"object": "list", "data": [{"id": i} for i in ids], "has_more": bool(nxt), "next_cursor": nxt}


def test_one_page_as_sent() -> None:
    script = Script(Step(body=page(["ver_1", "ver_2"], "c2")))
    first = make(script).verifications.list({"limit": 2})
    assert [v["id"] for v in first.data] == ["ver_1", "ver_2"]
    assert first.has_more and first.next_cursor == "c2"
    assert get_last_response(first) is not None
    assert len(script.calls) == 1


def test_iterating_reads_every_page_with_the_same_filters() -> None:
    script = Script(
        Step(body=page(["a", "b"], "c2")), Step(body=page(["c", "d"], "c3")), Step(body=page(["e"]))
    )
    ids = [v["id"] for v in make(script).verifications.list({"status": "completed", "limit": 2})]
    assert ids == ["a", "b", "c", "d", "e"]
    assert [c.url.query for c in script.calls] == [
        b"status=completed&limit=2",
        b"status=completed&limit=2&cursor=c2",
        b"status=completed&limit=2&cursor=c3",
    ]


def test_pages_fetched_only_as_read() -> None:
    script = Script(Step(body=page(["a", "b"], "c2")), Step(body=page(["c"])))
    for item in make(script).cases.list():
        assert item["id"] == "a"
        break
    assert len(script.calls) == 1


def test_to_list_with_a_guard() -> None:
    script = Script(Step(body=page(["a", "b"], "c2")), Step(body=page(["c"])))
    assert [x["id"] for x in make(script).consents.list().to_list()] == ["a", "b", "c"]
    many = Script(Step(body=page(["a", "b", "c"], "c2")))
    with pytest.raises(RangeError):
        make(many).consents.list().to_list(max_items=2)


def test_a_list_without_pages_is_a_plain_answer() -> None:
    script = Script(Step(body={"object": "list", "data": [{"chain": "ethereum"}]}))
    chains = make(script).wallet_screenings.chains.list()
    assert chains["data"][0]["chain"] == "ethereum"


# ------------------------------------------------------------------ async


def test_async_create_and_retry() -> None:
    script = Script(Step(raises=httpx.ConnectError("x")), Step(201, {"id": "ver_1"}))

    async def run() -> None:
        async with make_async(script) as client:
            result = await client.verifications.create({"check": "NG:NIN", "id_number": "1"})
            assert result["id"] == "ver_1"
            assert len(client.sleeps) == 1  # type: ignore[attr-defined]

    asyncio.run(run())
    assert script.calls[0].headers["idempotency-key"] == script.calls[1].headers["idempotency-key"]


def test_async_await_one_page_or_iterate_all() -> None:
    script = Script(Step(body=page(["a"], "c2")), Step(body=page(["b"])), Step(body=page(["x"])))

    async def run() -> None:
        client = make_async(script)
        listing = client.verifications.list({"limit": 1})
        ids = [v["id"] async for v in listing]
        assert ids == ["a", "b"]
        first = await client.verifications.list()
        assert [v["id"] for v in first.data] == ["x"] and not first.has_more
        await client.close()

    asyncio.run(run())


def test_async_errors() -> None:
    script = Script(Step(400, {"code": "validation_failed", "title": "Fix"}))

    async def run() -> None:
        client = make_async(script, max_retries=0)
        with pytest.raises(InvalidRequestError):
            await client.verifications.create({"check": "NG:NIN", "id_number": "1"})

    asyncio.run(run())
