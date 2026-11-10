from __future__ import annotations

import hashlib
import hmac
import json
from typing import Callable

import pytest

from compliwa import WebhookSignatureError, sign_webhook, verify_webhook

SECRET = "whsec_3q2-7wEXAMPLEu8Rp1yZ0nQK5Yc2vJmT4sHb9dLfGxA"
OLD_SECRET = "whsec_previousEXAMPLE0000000000000000000000000"
NOW = 1_762_628_400
EVENT = {
    "id": "wev_1",
    "object": "event",
    "type": "verification.completed",
    "api_version": "0.3.0",
    "created_at": "2025-11-08T19:00:00Z",
    "environment": "test",
    "data": {"object": {"object": "verification", "id": "ver_1"}},
}
BODY = json.dumps(EVENT, separators=(",", ":"))


def sign(secret: str, t: int, raw: str = BODY) -> str:
    """Exactly what the API's signer (compliwaAPI src/modules/webhooks/webhooks.sign.js) computes."""
    return hmac.new(secret.encode(), f"{t}.{raw}".encode(), hashlib.sha256).hexdigest()


def test_a_genuine_webhook() -> None:
    header = f"t={NOW},v1={sign(SECRET, NOW)}"
    assert verify_webhook(BODY, header, SECRET, now=NOW) == EVENT
    assert verify_webhook(BODY.encode(), header, SECRET, now=NOW + 299) == EVENT


def test_either_v1_while_a_rolled_secret_overlaps() -> None:
    header = f"t={NOW},v1={sign(SECRET, NOW)},v1={sign(OLD_SECRET, NOW)}"
    assert verify_webhook(BODY, header, OLD_SECRET, now=NOW)["id"] == "wev_1"
    assert verify_webhook(BODY, header, SECRET, now=NOW)["id"] == "wev_1"


@pytest.mark.parametrize(
    ("call", "code"),
    [
        (
            lambda h: verify_webhook(BODY.replace("ver_1", "ver_2"), h, SECRET, now=NOW),
            "webhook_signature_mismatch",
        ),
        (lambda h: verify_webhook(BODY, h, OLD_SECRET, now=NOW), "webhook_signature_mismatch"),
        (lambda h: verify_webhook(BODY, h, SECRET, now=NOW + 301), "webhook_signature_expired"),
        (lambda h: verify_webhook(BODY, h, SECRET, now=NOW - 301), "webhook_signature_expired"),
        (lambda h: verify_webhook(BODY, h.split(",")[1], SECRET, now=NOW), "webhook_signature_malformed"),
        (lambda h: verify_webhook(BODY, f"t={NOW},v1=xyz", SECRET, now=NOW), "webhook_signature_malformed"),
        (lambda h: verify_webhook(BODY, None, SECRET, now=NOW), "webhook_signature_missing"),
        (lambda h: verify_webhook(EVENT, h, SECRET, now=NOW), "webhook_body_not_raw"),  # type: ignore[arg-type]
        (lambda h: verify_webhook(BODY, h, "cw_test_" + "a" * 40, now=NOW), "webhook_secret_invalid"),
    ],
)
def test_refused(call: Callable[[str], object], code: str) -> None:
    with pytest.raises(WebhookSignatureError) as caught:
        call(f"t={NOW},v1={sign(SECRET, NOW)}")
    assert caught.value.code == code


def test_sign_webhook_as_compliwa_does() -> None:
    header = sign_webhook(BODY, SECRET, timestamp=NOW)
    assert header == f"t={NOW},v1={sign(SECRET, NOW)}"
    assert verify_webhook(BODY, header, SECRET, now=NOW)["type"] == "verification.completed"
    assert verify_webhook(BODY, sign_webhook(EVENT, SECRET), SECRET)["id"] == "wev_1"


def test_the_node_library_and_this_one_agree() -> None:
    """The same vector the Node.js library's tests use (compliwa-node test/webhooks.test.js)."""
    node_body = json.dumps(EVENT, separators=(",", ":"))
    assert sign_webhook(node_body, SECRET, timestamp=NOW) == f"t={NOW},v1={sign(SECRET, NOW, node_body)}"
