# Compliwa for Python

The official Python library for the [Compliwa API](https://compliwa.com/developers/api): identity
checks, sanctions and PEP screening, business checks, consent records, monitoring, cases, the Travel
Rule and signed webhooks — from your server, sync or async.

```python
from compliwa import Compliwa

client = Compliwa()  # reads COMPLIWA_API_KEY

verification = client.verifications.create({
    "check": "NG:NIN",
    "id_number": "12345678901",
    "first_name": "Ada",
    "last_name": "Okafor",
    "date_of_birth": "1990-05-14",
    "consent": True,
})

print(verification["id"], verification["outcome"])
```

Every method is generated from the API's own contract, so it covers each endpoint an API key can
call, with types for every request and answer. The names match the Node.js library
([compliwa-node](https://github.com/compliwa/compliwa-node)), in Python style.

## Install

```
pip install compliwa
```

Python 3.10 or newer. Depends on `httpx` and `typing_extensions`.

## Your API key

Create one in the dashboard under **API keys**. The key decides where your calls go:

| Key        | Reaches                                                        |
| ---------- | -------------------------------------------------------------- |
| `cw_test_` | The sandbox: test data that answers predictably, never charged |
| `cw_live_` | Real customers, counted against your plan                      |

Keep it in an environment variable or your secret manager, never in code. `Compliwa()` with no
argument reads `COMPLIWA_API_KEY`. The sandbox's test numbers are listed at `GET /v1/sandbox` and on
the [Sandbox page](https://compliwa.com/developers/api/sandbox).

## How methods read

`client.<resource>.<method>(*ids, params, **options)`

```python
client.screenings.create({"type": "person", "name": "Ada Okafor"})
client.screenings.retrieve("scr_…")
client.travel_rule.transfers.confirm("trt_…", {"txid": "…"})
client.cases.items.create("cas_…", {"type": "screening", "id": "scr_…"})
```

- **ids** come first, in the order of the path.
- **params** is a dict: the body for a create or an action, the filters for a list.
- **options** (keywords): `idempotency_key`, `timeout`, `max_retries`, `extra_headers`.

Answers are plain dicts, exactly as the API sent them, typed as `TypedDict`s in `compliwa.types`, so
your editor completes the fields and `mypy` checks them. Every operation, with every field, is in
[the API reference](https://compliwa.com/developers/api), which shows each call in Python.

## Async

```python
import asyncio
from compliwa import AsyncCompliwa

async def main() -> None:
    async with AsyncCompliwa() as client:
        screening = await client.screenings.create({"type": "person", "name": "Ada Okafor"})
        async for verification in client.verifications.list({"status": "completed"}):
            print(verification["id"])

asyncio.run(main())
```

## Lists and pages

```python
page = client.verifications.list({"status": "completed", "limit": 50})
page.data, page.has_more, page.next_cursor          # one page, as sent

for verification in client.verifications.list({"status": "completed"}):
    ...                                              # every item, page after page

everyone = client.monitoring.customers.list({"risk": "high"}).to_list(max_items=5000)
```

Pages are fetched only when you reach them.

## Retries and idempotency

A call is retried (twice by default, with growing waits) only when retrying is safe and can help:
no answer, `429`, a `5xx`, or `409 idempotency_key_in_use`. It waits as long as `Retry-After` says.

The creates the API makes idempotent (verifications, screenings, identity sessions, business checks,
consents, cases, subject requests, signup checks, wallet screenings, Travel Rule transfers) carry an
`Idempotency-Key`, the same on every retry, so a check is never run or charged twice. Pass your own
to make a retry safe across restarts too:

```python
client.verifications.create(params, idempotency_key=f"onboarding-{customer_id}")
```

Any other write is retried only after a `429` (it never ran). If its answer is lost, you get an
`APIConnectionError` saying it may or may not have run: read it back before sending it again.

## Errors

```python
from compliwa import CompliwaError, InvalidRequestError

try:
    client.verifications.create(params)
except InvalidRequestError as error:
    print(error.errors)  # [{"path": "id_number", "message": "…"}]
except CompliwaError as error:
    print(error.status, error.code, error.detail, error.request_id)
```

| Class                   | When                                                     |
| ----------------------- | -------------------------------------------------------- |
| `InvalidRequestError`   | 400, 422: fix the request                                |
| `AuthenticationError`   | 401: the key is missing, wrong, revoked or expired       |
| `PermissionDeniedError` | 403: the key lacks a scope (`scope_missing`)             |
| `NotFoundError`         | 404                                                      |
| `ConflictError`         | 409                                                      |
| `RateLimitError`        | 429 after the retries; `retry_after` says how long       |
| `APIError`              | 5xx after the retries                                    |
| `APIConnectionError`    | No answer (`APITimeoutError` when the time ran out)      |

Branch on `error.code`, which never changes. Quote `error.request_id` to support. Pass
`language="fr"` (or `es`, `ar`) to the client to get titles and details in that language.

## The answer's facts

```python
from compliwa import get_last_response

screening = client.screenings.create(params)
facts = get_last_response(screening)
facts.request_id, facts.environment, facts.idempotent_replayed
```

## Webhooks

Check every webhook's signature before you trust it. Pass the **raw** body:

```python
import os
from flask import Flask, abort, request
from compliwa import WebhookSignatureError, verify_webhook

app = Flask(__name__)

@app.post("/webhooks/compliwa")
def compliwa_webhook():
    try:
        event = verify_webhook(
            request.get_data(),
            request.headers.get("Compliwa-Signature"),
            os.environ["COMPLIWA_WEBHOOK_SECRET"],
        )
    except WebhookSignatureError:
        abort(400)
    # Deliveries can repeat: skip an event["id"] you have already handled.
    if event["type"] == "verification.completed":
        ...
    return "", 204
```

It accepts either signature while a rolled secret overlaps, and refuses one older than 5 minutes.
`sign_webhook(payload, secret)` makes a header exactly as Compliwa does, for your own tests.

## Anything else

`client.request(method, path, body=..., query=...)` calls any endpoint with the same key, retries
and errors.

## Options

```python
Compliwa(
    api_key,
    base_url="http://localhost:5010",    # default https://api.compliwa.com (or COMPLIWA_BASE_URL)
    timeout=30,                          # seconds per attempt
    max_retries=2,
    language="en",                       # en · fr · es · ar
    app_info={"name": "acmepay-onboarding", "version": "3.1.0"},  # added to the User-Agent
    http_client=httpx.Client(...),       # your own (proxies, certificates)
)
```

## Developing this library

```
python -m venv .venv
.venv\Scripts\activate          # Windows (source .venv/bin/activate elsewhere)
pip install -e ".[dev]"
python scripts/generate.py      # from ../compliwaAPI/openapi/dist/openapi.json, or --spec <file or URL>
pytest                          # no network
mypy
python -m pytest e2e            # against a running API, with COMPLIWA_API_KEY=cw_test_…
```

`src/compliwa/_generated/` comes from the contract and is never edited by hand.

## License

MIT
