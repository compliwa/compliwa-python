# Changelog

## 0.2.0 — 2026-11-10

Generated from the Compliwa API contract 0.4.0.

- `client.webhook_endpoints.list / create / retrieve / update / delete`: subscribe to events from your
  server, in your key's environment (needs the key's `webhooks.manage` scope). `create` returns the
  signing secret once — pass it to `verify_webhook()`.

## 0.1.0 — 2026-11-10

The first release, generated from the Compliwa API contract 0.3.0.

- Every operation an API key can call (61), sync (`Compliwa`) and async (`AsyncCompliwa`), named from the
  contract's `x-sdk` — the same names as the Node.js library, in Python style (`travel_rule.transfers.confirm`).
- TypedDicts for every request and answer (`compliwa.types`), so your editor completes fields and mypy checks them.
- Retries only when safe, honouring `Retry-After`; an `Idempotency-Key` kept across retries for the creates the API
  makes idempotent.
- Lists you can read one page at a time or iterate across every page (`for` / `async for`), and `to_list()`.
- Typed errors carrying the API's problem details (`code`, `detail`, `errors`, `request_id`).
- `verify_webhook()` for the `Compliwa-Signature` header, and `sign_webhook()` for tests.
