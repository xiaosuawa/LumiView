"""Serve adapter regressions: shutdown races and thread-pool ownership."""

from __future__ import annotations

import asyncio
import gc
import warnings

import pytest

from lumiview.app import App, AppState
from lumiview.serve import Handler, Request
from lumiview.serve.asgi import ASGI
from lumiview.serve.wsgi import WSGI


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
    app._state = AppState.RUNNING
    monkeypatch.setattr(App, "get", classmethod(lambda cls: app))

    adapter = ASGI(lambda scope, receive, send: None)
    responses: list[int] = []

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        adapter(_request(), lambda status, headers, body: responses.append(status))
        gc.collect()

    assert responses == [503]
    assert not [w for w in caught if "never awaited" in str(w.message)]


# ---------------------------------------------------------------------------
# WSGI — the App owns the pool now
# ---------------------------------------------------------------------------


class _RecordingPool:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


def _app_with_pool(pool, *, state=AppState.RUNNING) -> App:
    app = object.__new__(App)
    app._threadpool = pool
    app._state = state
    app._async_loop = None
    return app


def test_wsgi_submits_to_the_app_pool(monkeypatch):
    pool = _RecordingPool()
    app = _app_with_pool(pool)
    monkeypatch.setattr(App, "get", classmethod(lambda cls: app))

    WSGI(lambda environ, start_response: [])(
        _request(), lambda status, headers, body: None
    )

    assert len(pool.calls) == 1


def test_wsgi_answers_503_when_the_app_is_gone(monkeypatch):
    app = _app_with_pool(None)
    monkeypatch.setattr(App, "get", classmethod(lambda cls: app))

    responses: list[int] = []
    WSGI(lambda environ, start_response: [])(
        _request(), lambda status, headers, body: responses.append(status)
    )

    assert responses == [503]


def test_wsgi_answers_503_when_the_pool_rejects_the_submit(monkeypatch):
    class _ClosedPool:
        def submit(self, fn, *args):
            raise RuntimeError("cannot schedule new futures after shutdown")

    app = _app_with_pool(_ClosedPool())
    monkeypatch.setattr(App, "get", classmethod(lambda cls: app))

    responses: list[int] = []
    WSGI(lambda environ, start_response: [])(
        _request(), lambda status, headers, body: responses.append(status)
    )

    assert responses == [503]


def test_wsgi_max_workers_is_deprecated():
    with pytest.warns(DeprecationWarning):
        WSGI(lambda environ, start_response: [], max_workers=2)


# ---------------------------------------------------------------------------
# Handler — shutdown behaviour
# ---------------------------------------------------------------------------


def test_handler_answers_503_when_the_loop_is_closed(monkeypatch):
    loop = asyncio.new_event_loop()
    loop.close()

    app = object.__new__(App)
    app._async_loop = loop
    app._state = AppState.RUNNING
    monkeypatch.setattr(App, "get", classmethod(lambda cls: app))

    responses: list[int] = []
    Handler(lambda request: None)(
        _request(), lambda status, headers, body: responses.append(status)
    )

    assert responses == [503]
