from __future__ import annotations

import re

import httpx
import pytest
from conftest import TEST_KEY, Script, Step, make

import compliwa
from compliwa import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    Compliwa,
    CompliwaError,
    InvalidRequestError,
    NotFoundError,
    RateLimitError,
    get_last_response,
)


def test_the_key_required_shaped_never_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(CompliwaError, match="No API key"):
        Compliwa()
    with pytest.raises(CompliwaError, match="starts with cw_test_ or cw_live_"):
        Compliwa("sk_live_123")
    with pytest.raises(CompliwaError, match="webhook signing secret"):
        Compliwa("whsec_abcdefghijkl")
    monkeypatch.setenv("COMPLIWA_API_KEY", TEST_KEY)
    assert Compliwa().environment == "test"
    live = Compliwa("cw_live_" + "b" * 40)
    assert live.environment == "live"
    assert live.base_url == "https://api.compliwa.com"
    assert "bbbb" not in repr(live) and "bbbb" not in str(live)


def test_an_oauth_access_token_works_like_a_key() -> None:
    assert Compliwa("cwat_live_" + "c" * 40).environment == "live"
    assert Compliwa("cwat_test_" + "c" * 40).environment == "test"
    with pytest.raises(CompliwaError, match="starts with cw_test_ or cw_live_"):
        Compliwa("cwrt_test_" + "c" * 40)  # a refresh token is for the token endpoint only


def test_every_operation_is_a_method() -> None:
    client = make(Script())
    assert len(compliwa.OPERATIONS) >= 60
    for op in compliwa.OPERATIONS:
        target = client
        for part in op["python"].split("."):
            target = getattr(target, part)
        assert callable(target), op["python"]


def test_a_create_body_key_idempotency_answer_and_facts() -> None:
    script = Script(
        Step(
            201,
            {"id": "ver_1", "object": "verification"},
            {"x-request-id": "req_1", "compliwa-environment": "test", "compliwa-api-version": "0.3.0"},
        )
    )
    client = make(script, app_info={"name": "acme", "version": "1.0"})
    result = client.verifications.create({"check": "NG:NIN", "id_number": "12345678901"})

    assert dict(result) == {"id": "ver_1", "object": "verification"}
    facts = get_last_response(result)
    assert facts is not None and facts.status == 201 and facts.request_id == "req_1"
    assert facts.environment == "test" and facts.api_version == "0.3.0"

    call = script.calls[0]
    assert call.method == "POST" and str(call.url) == "https://api.test/v1/verifications"
    assert call.headers["authorization"] == f"Bearer {TEST_KEY}"
    assert re.fullmatch(r"[0-9a-f-]{36}", call.headers["idempotency-key"])
    assert re.match(
        r"compliwa-python/\d+\.\d+\.\d+ python/\S+ httpx/\S+ acme/1\.0$", call.headers["user-agent"]
    )
    assert script.body(0) == {"check": "NG:NIN", "id_number": "12345678901"}


def test_ids_in_the_path_encoded_params_after_them() -> None:
    script = Script(Step(body={"id": "trt_1"}), Step(body={"id": "cas_1"}))
    client = make(script)
    client.travel_rule.transfers.confirm("trt_1", {"txid": "abc"})
    client.cases.retrieve("cas_1/../x")
    assert script.calls[0].url.path == "/v1/travel-rule/transfers/trt_1/confirm"
    assert script.body(0) == {"txid": "abc"}
    assert script.calls[1].url.raw_path == b"/v1/cases/cas_1%2F..%2Fx"
    with pytest.raises(TypeError, match="case_id should be an id string"):
        client.cases.retrieve("")
    with pytest.raises(TypeError, match="params should be a dict"):
        client.verifications.create("oops")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="unknown option"):
        client.verifications.create({}, check="NG:NIN")  # type: ignore[call-arg]


def test_filters_become_the_query_empty_ones_left_out() -> None:
    script = Script(Step(body={"object": "list", "data": [], "has_more": False, "next_cursor": None}))
    client = make(script)
    client.screenings.list({"outcome": "possible_match", "reference": None, "limit": 5})
    assert script.calls[0].url.query == b"outcome=possible_match&limit=5"
    assert "idempotency-key" not in script.calls[0].headers


def test_keyword_named_filters_work() -> None:
    script = Script(Step(body={"object": "list", "data": [], "has_more": False, "next_cursor": None}))
    make(script).transactions.list({"from": "2026-01-01", "to": "2026-02-01"})
    assert script.calls[0].url.params["from"] == "2026-01-01"


def test_your_idempotency_key_the_same_on_every_retry() -> None:
    script = Script(Step(503, {}), Step(500, {}), Step(201, {"id": "scr_1"}))
    client = make(script)
    client.screenings.create({"type": "person", "name": "Ada"}, idempotency_key="onboarding-ada-1")
    assert [c.headers["idempotency-key"] for c in script.calls] == ["onboarding-ada-1"] * 3
    assert len(client.sleeps) == 2  # type: ignore[attr-defined]


def test_a_generated_key_is_kept_across_retries() -> None:
    script = Script(Step(raises=httpx.ConnectError("refused")), Step(201, {"id": "ver_1"}))
    make(script).verifications.create({"check": "NG:NIN", "id_number": "12345678901"})
    assert len(script.calls) == 2
    assert script.calls[0].headers["idempotency-key"] == script.calls[1].headers["idempotency-key"]


def test_retry_after_honoured_and_409_in_use_retried() -> None:
    script = Script(
        Step(429, {"code": "rate_limited"}, {"retry-after": "3"}),
        Step(409, {"code": "idempotency_key_in_use"}, {"retry-after": "1"}),
        Step(200, {"id": "ver_1"}),
    )
    client = make(script)
    client.verifications.create({"check": "NG:NIN", "id_number": "1"})
    assert client.sleeps == [3.0, 1.0]  # type: ignore[attr-defined]


def test_a_write_the_api_does_not_make_idempotent() -> None:
    script = Script(Step(raises=httpx.ConnectError("refused")))
    with pytest.raises(APIConnectionError, match="may or may not have run"):
        make(script).transactions.create({"transaction_id": "t1"})  # type: ignore[typeddict-item]
    assert len(script.calls) == 1 and "idempotency-key" not in script.calls[0].headers

    bad_gateway = Script(Step(502, {}))
    with pytest.raises(APIError):
        make(bad_gateway).transactions.create({})  # type: ignore[typeddict-item]
    assert len(bad_gateway.calls) == 1

    limited = Script(Step(429, {}), Step(201, {"id": "txn_1"}))
    make(limited).transactions.create({})  # type: ignore[typeddict-item]
    assert len(limited.calls) == 2


def test_reads_retry_up_to_max_retries() -> None:
    script = Script(Step(500), Step(502), Step(503, {"code": "unavailable"}))
    with pytest.raises(APIError) as caught:
        make(script).verifications.retrieve("ver_1")
    assert caught.value.status == 503 and len(script.calls) == 3

    once = Script(Step(500))
    with pytest.raises(APIError):
        make(once).verifications.retrieve("ver_1", max_retries=0)
    assert len(once.calls) == 1


def test_a_long_retry_after_is_not_waited_out() -> None:
    script = Script(Step(429, {"code": "rate_limited"}, {"retry-after": "3600"}))
    with pytest.raises(RateLimitError) as caught:
        make(script).verifications.list()
    assert caught.value.retry_after == 3600 and len(script.calls) == 1


def test_errors_carry_what_the_api_said() -> None:
    problem = {
        "title": "Some fields need fixing",
        "status": 400,
        "code": "validation_failed",
        "detail": "id_number: 11 digits",
        "errors": [{"path": "id_number", "message": "11 digits"}],
    }
    script = Script(
        Step(400, problem, {"x-request-id": "req_9"}),
        Step(401, {"code": "api_key_revoked", "title": "This key was revoked"}),
        Step(404, {"code": "not_found"}),
        Step(502, "<html>bad gateway</html>", {"content-type": "text/html"}),
    )
    client = make(script, max_retries=0)
    with pytest.raises(InvalidRequestError) as invalid:
        client.verifications.create({"check": "NG:NIN", "id_number": "1"})
    assert invalid.value.code == "validation_failed" and invalid.value.request_id == "req_9"
    assert invalid.value.errors == problem["errors"]
    assert str(invalid.value) == "Some fields need fixing: id_number: 11 digits"
    with pytest.raises(AuthenticationError) as auth:
        client.api_key.retrieve()
    assert auth.value.code == "api_key_revoked"
    with pytest.raises(NotFoundError):
        client.cases.retrieve("cas_x")
    with pytest.raises(APIError) as gateway:
        client.cases.retrieve("cas_x")
    assert "bad gateway" in (gateway.value.detail or "")


def test_a_timeout_is_an_api_timeout_error() -> None:
    script = Script(Step(raises=httpx.ReadTimeout("slow")))
    with pytest.raises(APITimeoutError) as caught:
        make(script, max_retries=0, timeout=5).api_key.retrieve()
    assert caught.value.code == "timeout" and "5 s" in str(caught.value)


def test_request_any_endpoint() -> None:
    script = Script(Step(body={"object": "sandbox"}))
    client = make(script)
    answer = client.request("get", "/v1/sandbox", query={"a": 1})
    assert answer["object"] == "sandbox"
    assert str(script.calls[0].url) == "https://api.test/v1/sandbox?a=1"
    with pytest.raises(ValueError, match="starts with /"):
        client.request("GET", "v1/x")


def test_accept_language() -> None:
    script = Script(Step(body={}))
    make(script, language="fr").api_key.retrieve()
    assert script.calls[0].headers["accept-language"] == "fr"


def test_context_manager_closes_its_own_client() -> None:
    with Compliwa(TEST_KEY) as client:
        assert client.environment == "test"
    assert client._http.is_closed
