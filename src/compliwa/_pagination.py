"""Lists with pages (x-sdk `paginated`: a `cursor` filter, answers with has_more and next_cursor).

Sync:
    page = client.verifications.list({"limit": 50})   # one page, as the API sent it
    page.data, page.has_more, page.next_cursor
    for verification in client.verifications.list():  # every item, page after page
        ...

Async:
    page = await client.verifications.list({"limit": 50})
    async for verification in client.verifications.list():
        ...

Pages are fetched one at a time, only as you reach them; the filters you passed apply to every page.
"""

from __future__ import annotations

from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Generator,
    Generic,
    Iterator,
    List,
    Optional,
    TypeVar,
)

from ._response import ApiDict, LastResponse

T = TypeVar("T")

DEFAULT_MAX = 10_000


def _too_many(max_items: int) -> RangeError:
    return RangeError(f"More than {max_items} items: narrow the filters, or pass a larger max_items.")


class RangeError(ValueError):
    """to_list() would return more than max_items: a runaway read, stopped."""


class _PageFacts(Generic[T]):
    _raw: ApiDict

    @property
    def data(self) -> List[T]:
        """The items on this page."""
        return list(self._raw.get("data") or [])

    @property
    def has_more(self) -> bool:
        return bool(self._raw.get("has_more"))

    @property
    def next_cursor(self) -> Optional[str]:
        return self._raw.get("next_cursor")

    @property
    def raw(self) -> ApiDict:
        """The page exactly as the API sent it."""
        return self._raw

    @property
    def last_response(self) -> Optional[LastResponse]:
        return self._raw.last_response

    def __repr__(self) -> str:
        return f"{type(self).__name__}(items={len(self.data)}, has_more={self.has_more})"


class SyncPage(_PageFacts[T]):
    def __init__(self, fetch: Callable[[Dict[str, Any]], ApiDict], query: Dict[str, Any]) -> None:
        self._fetch = fetch
        self._query = dict(query)
        self._raw = fetch(self._query)

    def iter_pages(self) -> Iterator[SyncPage[T]]:
        page: SyncPage[T] = self
        yield page
        while page.has_more and page.next_cursor:
            nxt: SyncPage[T] = SyncPage.__new__(SyncPage)
            nxt._fetch, nxt._query = page._fetch, page._query
            nxt._raw = page._fetch({**page._query, "cursor": page.next_cursor})
            page = nxt
            yield page

    def __iter__(self) -> Iterator[T]:
        for page in self.iter_pages():
            yield from page.data

    def to_list(self, *, max_items: int = DEFAULT_MAX) -> List[T]:
        items: List[T] = []
        for item in self:
            if len(items) >= max_items:
                raise _too_many(max_items)
            items.append(item)
        return items


class AsyncPage(_PageFacts[T]):
    def __init__(
        self, fetch: Callable[[Dict[str, Any]], Awaitable[ApiDict]], query: Dict[str, Any], raw: ApiDict
    ) -> None:
        self._fetch = fetch
        self._query = query
        self._raw = raw

    async def iter_pages(self) -> AsyncIterator[AsyncPage[T]]:
        page: AsyncPage[T] = self
        yield page
        while page.has_more and page.next_cursor:
            raw = await page._fetch({**page._query, "cursor": page.next_cursor})
            page = AsyncPage(page._fetch, page._query, raw)
            yield page

    async def __aiter__(self) -> AsyncIterator[T]:
        async for page in self.iter_pages():
            for item in page.data:
                yield item

    async def to_list(self, *, max_items: int = DEFAULT_MAX) -> List[T]:
        items: List[T] = []
        async for item in self:
            if len(items) >= max_items:
                raise _too_many(max_items)
            items.append(item)
        return items


class AsyncPaginator(Generic[T]):
    """What an async list returns: await it for the first page, or `async for` it for every item."""

    def __init__(self, fetch: Callable[[Dict[str, Any]], Awaitable[ApiDict]], query: Dict[str, Any]) -> None:
        self._fetch = fetch
        self._query = dict(query)
        self._first: Optional[AsyncPage[T]] = None

    async def _first_page(self) -> AsyncPage[T]:
        if self._first is None:
            self._first = AsyncPage(self._fetch, self._query, await self._fetch(self._query))
        return self._first

    def __await__(self) -> Generator[Any, None, AsyncPage[T]]:
        return self._first_page().__await__()

    async def __aiter__(self) -> AsyncIterator[T]:
        page = await self._first_page()
        async for item in page:
            yield item

    async def to_list(self, *, max_items: int = DEFAULT_MAX) -> List[T]:
        return await (await self._first_page()).to_list(max_items=max_items)
