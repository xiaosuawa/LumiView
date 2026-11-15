"""ASGI adapter regressions: shutdown races."""

from __future__ import annotations

import asyncio
import gc
import warnings

from lumiview.app import App
from lumiview.serve import ASGI, Request


def _request() -> Request:
    return Request(
        method="GET",
        url="lumiview://app/",
        path="/",
        query="",
        headers=[],
        body=b"",
    )


def test_asgi_call_answers_when_the_loop_is_closed(monkeypatch):
    """Scheduling on a closed loop must still answer the request and must
    not leak the coroutine."""
    loop = asyncio.new_event_loop()
    loop.close()

    # Only the attributes ASGI touches: the closed loop and the scheduler
    # helpers from the real App class.
    app = object.__new__(App)
    app._async_loop = loop
    app._closing = False
    monkeypatch.setattr(App, "get", classmethod(lambda cls: app))

    adapter = ASGI(lambda scope, receive, send: None)
    responses: list[int] = []

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        adapter(_request(), lambda status, headers, body: responses.append(status))
        gc.collect()

    assert responses == [503]
    assert not [w for w in caught if "never awaited" in str(w.message)]
