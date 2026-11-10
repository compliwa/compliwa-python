"""Check that a webhook came from Compliwa, unchanged and recent, and read its event.

    @app.post("/webhooks/compliwa")
    def compliwa_webhook():
        try:
            event = verify_webhook(
                request.get_data(),                       # the RAW bytes received
                request.headers.get("Compliwa-Signature"),
                os.environ["COMPLIWA_WEBHOOK_SECRET"],
            )
        except WebhookSignatureError:
            abort(400)
        # Deliveries can repeat: skip an event["id"] you have already handled.
        return "", 204

The header: Compliwa-Signature: t=<unix seconds>,v1=<hex>[,v1=<hex>]
    v1 = HMAC-SHA256("<t>.<raw body>") keyed with the whole "whsec_…" secret. While a rolled secret
    overlaps there are two v1 values: either may match. A t further than `tolerance` seconds (300)
    from now is refused, so a captured request cannot be replayed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any, Dict, Optional, Union

from ._errors import WebhookSignatureError

SIGNATURE_HEADER = "Compliwa-Signature"
DEFAULT_TOLERANCE = 300
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _fail(code: str, message: str) -> WebhookSignatureError:
    return WebhookSignatureError(message, code=code)


def _signature(secret: str, timestamp: int, body: bytes) -> bytes:
    return hmac.new(
        secret.encode("utf-8"), str(timestamp).encode("ascii") + b"." + body, hashlib.sha256
    ).digest()


def verify_webhook(
    payload: Union[bytes, bytearray, str],
    header: Optional[str],
    secret: str,
    *,
    tolerance: int = DEFAULT_TOLERANCE,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Return the event, or raise WebhookSignatureError.

    payload: the raw body exactly as received (bytes, or the str as sent) — JSON parsed and dumped
    again no longer matches. now: Unix seconds, for tests.
    """
    if not isinstance(secret, str) or not secret.startswith("whsec_"):
        raise _fail(
            "webhook_secret_invalid",
            "The webhook secret starts with whsec_ (the endpoint's signing secret, not an API key).",
        )
    if not header:
        raise _fail("webhook_signature_missing", f"No {SIGNATURE_HEADER} header.")
    if isinstance(payload, str):
        body = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray)):
        body = bytes(payload)
    else:
        raise _fail(
            "webhook_body_not_raw",
            "Pass the raw body (bytes or str), e.g. Flask request.get_data() — "
            "a parsed object cannot be checked.",
        )

    timestamp: Optional[int] = None
    signatures = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t" and value.isdigit():
            timestamp = int(value)
        elif key == "v1" and _HEX64.match(value):
            signatures.append(bytes.fromhex(value))
    if timestamp is None or not signatures:
        raise _fail("webhook_signature_malformed", f"The {SIGNATURE_HEADER} header is not t=…,v1=….")

    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance:
        raise _fail(
            "webhook_signature_expired",
            f"The signature is {abs(current - timestamp):.0f} s from now — more than {tolerance} s. "
            "Check the server clock, or this is a replay.",
        )

    expected = _signature(secret, timestamp, body)
    if not any(hmac.compare_digest(given, expected) for given in signatures):
        raise _fail(
            "webhook_signature_mismatch",
            "No signature matches: check the secret (this endpoint's, this environment's) and that the "
            "body is the raw bytes received.",
        )
    try:
        event = json.loads(body)
    except ValueError:
        raise _fail("webhook_body_invalid", "The body is signed but is not JSON.") from None
    if not isinstance(event, dict):
        raise _fail("webhook_body_invalid", "The body is signed but is not an event.")
    return event


def sign_webhook(
    payload: Union[bytes, str, Dict[str, Any]], secret: str, *, timestamp: Optional[int] = None
) -> str:
    """Sign a payload as Compliwa does — for testing your own webhook handler. Returns the header value."""
    if isinstance(payload, dict):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    elif isinstance(payload, str):
        body = payload.encode("utf-8")
    else:
        body = payload
    t = int(time.time()) if timestamp is None else timestamp
    return f"t={t},v1={_signature(secret, t, body).hex()}"
