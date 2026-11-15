"""Internal helpers shared by the framework modules.

Not part of the public API — user-facing helpers live in
:mod:`lumiview.utils`. :func:`main_thread` lives here because importing it
from :mod:`lumiview.app` at module level would create a cycle (app imports
the menu/tray modules lazily, but those import app eagerly).
"""

from __future__ import annotations

import functools
import logging
import re
import threading
import time
from concurrent.futures import InvalidStateError
from typing import Any, Callable, Concatenate, ParamSpec, TypeVar

from lumiview.events import WindowEvent
from lumiview.task import Task

P = ParamSpec("P")
R = TypeVar("R")
E = TypeVar("E")

_log = logging.getLogger("lumiview.events")


def passes_where(where: Callable[[E], bool] | None, event: E) -> bool:
    """Evaluate a ``where`` filter function, treating a raising one as
    a non-match (logged, never propagated into the dispatcher)."""

    if where is None:
        return True
    try:
        return bool(where(event))
    except Exception:
        _log.exception("event filter raised; treating as no match")
        return False


def copy_signature_for_classmethod(
    _: Callable[P, Any],
) -> Callable[[Callable[..., R]], Callable[Concatenate[type[Any], P], R]]:
    """Decorator to copy the signature of a callable to a classmethod."""

    def decorator(fn: Callable[..., R]) -> Callable[Concatenate[type[Any], P], R]:
        return fn

    return decorator


def main_thread(fn: Callable[P, R]) -> Callable[P, Task[R]]:
    """
    Decorate a sync ``def`` method to run on the main thread.

    Returns a :class:`Task` — ``await`` in async code, ``.result()``
    in sync code.
    """

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Task[R]:
        from lumiview.app import App  # deferred — avoids an import cycle

        return App.get().call_on_main(fn, *args, **kwargs)

    return wrapper


def fn_name(fn: Any) -> str:
    """Best-effort human-readable name for a callable (for logs).

    Handles :class:`functools.partial` and falls back to ``repr`` —
    lambdas and functions carry ``__qualname__``; builtins / bound
    objects without one fall to ``repr``.
    """
    if isinstance(fn, functools.partial):
        return fn_name(fn.func) + "(partial)"
    return getattr(fn, "__qualname__", getattr(fn, "__name__", repr(fn)))


def fmt_ms(start: float) -> float:
    """Milliseconds elapsed since *start* (from :func:`time.monotonic`)."""
    return (time.monotonic() - start) * 1000.0


def pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a ``*`` glob pattern to a compiled regex.

    ``*`` matches any sequence (including ``/``, ``.``, ``?``); every
    other character matches literally.
    """
    parts = pattern.split("*")
    source = "^" + re.escape(parts[0])
    for part in parts[1:]:
        source += ".*" + re.escape(part)
    source += "$"
    return re.compile(source)


def match_pattern(pattern: str, value: str) -> bool:
    """Match *value* against a ``*`` glob pattern."""
    return pattern_to_regex(pattern).match(value) is not None


def remove_handler(
    handlers: dict[type, list[tuple]],
    event: type,
    entry: tuple,
    *,
    lock: threading.Lock | None = None,
) -> None:
    """Remove a ``(handler, where)`` pair from an event-handler registry.

    *lock* is the registry's lock (when the owner has one) so removal is
    atomic with respect to registration and dispatch snapshots.
    """

    def _remove() -> None:
        entries = handlers.get(event)
        if entries is None:
            return
        try:
            entries.remove(entry)
        except ValueError:
            pass

    if lock is None:
        _remove()
    else:
        with lock:
            _remove()


def wait_for_event(
    handlers: dict[type[Any], list[tuple]],
    event: type[E],
    *,
    where: Callable[[E], bool] | None,
    timeout: float | None,
    close_event: type,
    is_closed: Callable[[], bool],
    closed_error: Callable[[], BaseException],
    lock: threading.Lock | None = None
) -> Task[E]:
    """One-shot event waiter shared by ``App.wait_for`` / ``Window.wait_for``.

    Registers a temporary handler in *handlers*, resolves the returned
    :class:`Task` with the first matching *event*, and fails it with
    *closed_error* when *close_event* is dispatched (or when *is_closed*
    reports the owner already closed) or with :class:`TimeoutError` after
    *timeout* seconds. Both temporary handlers are removed when the task
    settles, so a timed-out waiter leaves nothing behind.
    """
    from lumiview.app import App  # deferred — avoids an import cycle

    app = App.get()
    loop = app._async_loop

    if loop is None:
        return Task._failed(RuntimeError("App is not running"))

    task: Task[E] = Task()
    holder: dict[str, tuple] = {}

    async def _handler(ev: E) -> None:
        if task.done():
            return
        remove_handler(handlers, event, holder["entry"], lock=lock)
        try:
            task.set_result(ev)
        except InvalidStateError:
            # Lost a race with the close/timeout path — it wins.
            pass

    async def _on_closed(_ev: Any) -> None:
        if task.done():
            return
        remove_handler(handlers, event, entry, lock=lock)
        remove_handler(handlers, close_event, close_entry, lock=lock)
        try:
            task.set_exception(closed_error())
        except InvalidStateError:
            pass

    entry = (_handler, where)
    close_entry = (_on_closed, None)
    holder["entry"] = entry
    if lock is None:
        handlers.setdefault(event, []).append(entry)
        # The close event shares the same registry as ordinary events: it is
        # dispatched exactly like one, so waiting for it needs no second
        # mechanism (and no notification object of its own).
        handlers.setdefault(close_event, []).append(close_entry)
    else:
        # Register both waiters atomically: a dispatch snapshot taken between
        # the two appends would otherwise miss the close waiter.
        with lock:
            handlers.setdefault(event, []).append(entry)
            handlers.setdefault(close_event, []).append(close_entry)
    _log.debug(
        "wait_for %s (%stimeout=%s)",
        event.__name__,
        f"{timeout}s" if timeout is not None else "none",
    )

    timer: list[Any] = []

    def _cleanup(_: Any) -> None:
        remove_handler(handlers, event, entry, lock=lock)
        remove_handler(handlers, close_event, close_entry, lock=lock)
        if timer:
            try:
                timer[0].cancel()
            except Exception:
                pass

    task.add_done_callback(_cleanup)

    # The owner may have closed between the caller's check and the
    # registration above — the close event has already been dispatched,
    # so no further one is coming.
    if is_closed():
        try:
            task.set_exception(closed_error())
        except InvalidStateError:
            pass
        return task

    if timeout is not None:

        def _expire() -> None:
            if task.done():
                return
            remove_handler(handlers, event, entry, lock=lock)
            remove_handler(handlers, close_event, close_entry, lock=lock)
            try:
                task.set_exception(
                    TimeoutError(
                        f"wait_for({event.__name__}) timed out after {timeout}s"
                    )
                )
            except InvalidStateError:
                pass

        def _arm() -> None:
            if task.done():
                return
            timer.append(loop.call_later(timeout, _expire))

        app._call_soon_threadsafe(_arm)

    return task


def navigation_policy(
    *,
    allow: tuple[str, ...] = (),
    deny: tuple[str, ...] = (),
) -> Callable[[WindowEvent.NavigationRequestedEvent], None]:
    """Build a handler for ``win.on(WindowEvent.NavigationRequestedEvent)``.

    Patterns are ``*`` globs matched against the full URL; deny wins.
    Empty *allow* means "allow everything not denied" (same semantics as
    the Bridge permission chain). Non-matching navigations are prevented
    via :meth:`~lumiview.events.WindowBaseEvent.prevent`.

    Example::

        win.on(WindowEvent.NavigationRequestedEvent)(
            utils.navigation_policy(allow=("https://*", "app://*"))
        )
    """

    def handler(event: WindowEvent.NavigationRequestedEvent) -> None:
        url = event.url
        for pattern in deny:
            if match_pattern(pattern, url):
                event.prevent()
                return
        if allow and not any(match_pattern(p, url) for p in allow):
            event.prevent()

    return handler


class Subscription:
    """A registered event handler that can be cancelled.

    Returned by ``Window.on`` / ``App.on``. Callable, so the decorator form
    keeps working (and returns the handler unchanged), plus :meth:`cancel`
    to remove it from the registry::

        sub = win.on(WindowEvent.TitleChangedEvent)

        @sub
        def on_title(event):
            print(event.title)

        sub.cancel()   # idempotent; no-op before registration
    """

    __slots__ = ("_handlers", "_event", "_where", "_lock", "_entry", "_cancelled")

    def __init__(
        self,
        handlers: dict[type, list[tuple]],
        event: type,
        where: Callable[[Any], bool] | None,
        lock: threading.Lock | None,
    ) -> None:
        self._handlers = handlers
        self._event = event
        self._where = where
        self._lock = lock
        self._entry: tuple | None = None
        self._cancelled = False

    def __call__(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        if not self._cancelled:
            entry = (fn, self._where)
            if self._lock is None:
                self._handlers.setdefault(self._event, []).append(entry)
            else:
                with self._lock:
                    self._handlers.setdefault(self._event, []).append(entry)
            self._entry = entry
        return fn

    def cancel(self) -> None:
        """Remove the handler from its registry (idempotent)."""
        if self._cancelled:
            return
        self._cancelled = True
        entry = self._entry
        if entry is None:
            return
        self._entry = None
        remove_handler(self._handlers, self._event, entry, lock=self._lock)
