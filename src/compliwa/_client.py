"""The two clients: Compliwa (blocking) and AsyncCompliwa (asyncio). Same methods, same safety.

    client = Compliwa()                         # reads COMPLIWA_API_KEY
    client = Compliwa("cw_test_…", timeout=10, language="fr", base_url="http://localhost:5010")

Every method is generated from the API's contract (_generated/resources.py):
    client.<resource>.<method>(*ids, params?, **options)
        ids       the path ids, in order:   client.travel_rule.transfers.confirm("trt_…", {"txid": …})
        params    a dict — the body (create, actions) or the filters (lists)
        options   idempotency_key, timeout, max_retries, extra_headers
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Mapping, Optional, Sequence, cast
from urllib.parse import quote

import httpx

from ._base import BaseClient, RequestPlan, backoff
from ._generated.meta import OPERATIONS
from ._generated.resources import AsyncResources, SyncResources
from ._pagination import AsyncPaginator, SyncPage
from ._response import ApiDict, wrap

_BY_NAME = {op["name"]: op for op in OPERATIONS}
_OPTION_NAMES = frozenset({"idempotency_key", "timeout", "max_retries", "extra_headers"})


def _path_for(op: Mapping[str, Any], ids: Sequence[Any]) -> str:
    names = op["path_params"]
    if len(ids) != len(names):
        raise TypeError(f"{op['python']}() takes {len(names)} id(s): {', '.join(names) or 'none'}")
    path = str(op["path"])
    for name, value in zip(names, ids, strict=True):
        if not isinstance(value, str) or not value:
            raise TypeError(f"{op['python']}(): {name} should be an id string")
        path = path.replace("{" + name + "}", quote(value, safe=""))
    return path


def _check(op: Mapping[str, Any], params: Any, options: Mapping[str, Any]) -> None:
    if params is not None and not isinstance(params, Mapping):
        raise TypeError(f"{op['python']}(): params should be a dict")
    unknown = set(options) - _OPTION_NAMES
    if unknown:
        raise TypeError(
            f"{op['python']}(): unknown option(s) {', '.join(sorted(unknown))} — "
            "body fields and filters go in the params dict"
        )


class Compliwa(BaseClient, SyncResources):
    """The Compliwa API, from your server. Use it in a `with` block, or call close() when done."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        language: Optional[str] = None,
        app_info: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        BaseClient.__init__(
            self,
            api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            language=language,
            app_info=app_info,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(follow_redirects=False)
        self._sleep = time.sleep
        SyncResources.__init__(self, self)

    # -- lifecycle
    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Compliwa:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # -- the one loop
    def _send(self, plan: RequestPlan) -> Any:
        attempt = 0
        while True:
            try:
                response = self._http.request(
                    plan.method,
                    plan.url,
                    params=plan.query or None,
                    content=plan.body,
                    headers=plan.headers,
                    timeout=plan.timeout,
                )
            except httpx.TransportError as cause:
                if plan.retry_safe and attempt < plan.max_retries:
                    attempt += 1
                    self._sleep(backoff(attempt))
                    continue
                raise plan.connection_error(cause) from cause
            parsed, wait, error = plan.judge(response, attempt)
            if error is not None:
                raise error
            if wait is not None:
                attempt += 1
                self._sleep(wait)
                continue
            return wrap(parsed, response)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: Optional[Mapping[str, Any]] = None,
        idempotent: bool = False,
        **options: Any,
    ) -> Any:
        """Any endpoint, with the same key, retries and errors: client.request("GET", "/v1/sandbox")."""
        return self._send(self._plan(method, path, body=body, query=query, idempotent=idempotent, **options))

    def _call(self, name: str, ids: Sequence[Any], params: Any, options: Mapping[str, Any]) -> Any:
        op = _BY_NAME[name]
        _check(op, params, options)
        path = _path_for(op, ids)

        def fetch(query: Dict[str, Any]) -> ApiDict:
            return cast(
                ApiDict,
                self._send(
                    self._plan(
                        op["method"],
                        path,
                        body=(dict(params or {}) if op.get("body") else None),
                        query=(query if op.get("query") else None),
                        idempotent=bool(op.get("idempotent")),
                        **options,
                    )
                ),
            )

        if op.get("paginated"):
            return SyncPage(fetch, dict(params or {}))
        return fetch(dict(params or {}))


class AsyncCompliwa(BaseClient, AsyncResources):
    """The Compliwa API for asyncio. Use it in an `async with` block, or await close() when done."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        language: Optional[str] = None,
        app_info: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        BaseClient.__init__(
            self,
            api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            language=language,
            app_info=app_info,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(follow_redirects=False)
        self._sleep = asyncio.sleep
        AsyncResources.__init__(self, self)

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncCompliwa:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _send(self, plan: RequestPlan) -> Any:
        attempt = 0
        while True:
            try:
                response = await self._http.request(
                    plan.method,
                    plan.url,
                    params=plan.query or None,
                    content=plan.body,
                    headers=plan.headers,
                    timeout=plan.timeout,
                )
            except httpx.TransportError as cause:
                if plan.retry_safe and attempt < plan.max_retries:
                    attempt += 1
                    await self._sleep(backoff(attempt))
                    continue
                raise plan.connection_error(cause) from cause
            parsed, wait, error = plan.judge(response, attempt)
            if error is not None:
                raise error
            if wait is not None:
                attempt += 1
                await self._sleep(wait)
                continue
            return wrap(parsed, response)

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: Optional[Mapping[str, Any]] = None,
        idempotent: bool = False,
        **options: Any,
    ) -> Any:
        """Any endpoint, with the same key, retries and errors."""
        return await self._send(
            self._plan(method, path, body=body, query=query, idempotent=idempotent, **options)
        )

    def _call(self, name: str, ids: Sequence[Any], params: Any, options: Mapping[str, Any]) -> Any:
        op = _BY_NAME[name]
        _check(op, params, options)
        path = _path_for(op, ids)

        async def fetch(query: Dict[str, Any]) -> ApiDict:
            return cast(
                ApiDict,
                await self._send(
                    self._plan(
                        op["method"],
                        path,
                        body=(dict(params or {}) if op.get("body") else None),
                        query=(query if op.get("query") else None),
                        idempotent=bool(op.get("idempotent")),
                        **options,
                    )
                ),
            )

        if op.get("paginated"):
            return AsyncPaginator(fetch, dict(params or {}))
        return fetch(dict(params or {}))
