"""Async store facade (review A-1): async handlers for hot paths.

The three drivers (SQLite/TiDB/CRDB) are synchronous; Litestar's
sync_to_thread already offloads them off the event loop. This facade lets hot
handlers be `async def` natively (no threadpool hop for the handler frame
itself) while store calls go through asyncio.to_thread — the documented
stepping stone to native async drivers (see review §15.4).
"""

from __future__ import annotations

import asyncio
from typing import Any


class AsyncControlPlaneFacade:
    def __init__(self, store: Any) -> None:
        self._store = store

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._store, name)
        if not callable(attr):
            return attr

        async def _call(*args: Any, **kwargs: Any) -> Any:
            return await asyncio.to_thread(attr, *args, **kwargs)

        return _call
