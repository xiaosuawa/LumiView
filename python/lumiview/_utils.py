"""Internal helpers shared by the framework modules."""

from __future__ import annotations

import asyncio
import functools
import logging
import re
import threading
import time
from contextlib import suppress
from typing import Any, Callable, Concatenate, Generic, ParamSpec, TYPE_CHECKING
from typing_extensions import TypeVar

from lumiview.events import Event, WindowEvent
from lumiview.task import Task, run_async

if TYPE_CHECKING:
    from lumiview.app import App

P = ParamSpec("P")
R = TypeVar("R")
E = TypeVar("E", default=Any)

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


def _dispatch_event(
    app: "App",
    entries: list[tuple[Callable[..., Any], Callable[[Any], bool] | None]],
    event: Event,
) -> Task[None] | None:
    """Run the matching handlers for *event* on the app's asyncio loop.

    Returns a Task that settles when every handler finished, or ``None`` when
    there is no loop or no handlers. ``where`` filters run on the loop thread and
    a handler failure is logged (the remaining handlers still run). Cancellation
    settles the Task with ``None`` and re-raises, so a shutdown does not surface
    as an error in a preventable event's GUI-thread caller.
    """
    if not entries or app._async_loop is None:
        return None

    if _log.isEnabledFor(logging.DEBUG):
        _log.debug(
            "dispatching %s to %d handler(s): %s",
            type(event).__name__,
            len(entries),
            ", ".join(fn_name(fn) for fn, _ in entries),
        )

    done: Task[None] = Task()

    async def _dispatch() -> None:
        for fn, where in entries:
            if not passes_where(where, event):
                continue
            try:
                await run_async(fn, event)
            except asyncio.CancelledError:
                done._settle(result=None)
                raise
            except BaseException:
                _log.exception("Error in %s handler: %s", type(event).__name__, fn)
        done._settle(result=None)

    if not app._spawn(_dispatch()):
        done._settle(result=None)
    return done


def copy_signature_for_classmethod(
    _: Callable[P, Any],
) -> Callable[[Callable[..., R]], Callable[Concatenate[type[Any], P], R]]:
    """Decorator to copy the signature of a callable to a classmethod."""

    def decorator(fn: Callable[..., R]) -> Callable[Concatenate[type[Any], P], R]:
        return fn

    return decorator


def main_thread(fn: Callable[P, R]) -> Callable[P, Task[R]]:
    """Run a sync ``def`` on the main thread; returns a ``Task``."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Task[R]:
        from lumiview.app import App  # deferred — avoids an import cycle

        return App.get().call_on_main(fn, *args, **kwargs)

    return wrapper


def fn_name(fn: Any) -> str:
    """Best-effort human-readable name for a callable (for logs)."""
    if isinstance(fn, functools.partial):
        return fn_name(fn.func) + "(partial)"
    return getattr(fn, "__qualname__", getattr(fn, "__name__", repr(fn)))


def fmt_ms(start: float) -> float:
    """Milliseconds elapsed since *start* (from :func:`time.monotonic`)."""
    return (time.monotonic() - start) * 1000.0


def pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a ``*`` glob to a regex (``*`` matches anything; the rest is literal)."""
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
    """Remove a ``(handler, where)`` pair from a registry (optionally under *lock*)."""

    def _remove() -> None:
        entries = handlers.get(event)
        if entries is None:
            return
        with suppress(ValueError):
            entries.remove(entry)

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
    lock: threading.Lock | None = None,
) -> Task[E]:
    """One-shot event waiter shared by ``App.wait_for`` / ``Window.wait_for``.

    Fails with *closed_error* when *close_event* fires, or ``TimeoutError``.
    """
    from lumiview.app import App  # deferred — avoids an import cycle

    app = App.get()

    if app._async_loop is None:
        return Task._failed(RuntimeError("App is not running"))

    task: Task[E] = Task()
    holder: dict[str, tuple] = {}

    async def _handler(ev: E) -> None:
        if task.done():
            return
        remove_handler(handlers, event, holder["entry"], lock=lock)
        task._settle(result=ev)

    async def _on_closed(_ev: Any) -> None:
        if task.done():
            return
        remove_handler(handlers, event, entry, lock=lock)
        remove_handler(handlers, close_event, close_entry, lock=lock)
        task._settle(exc=closed_error())

    entry = (_handler, where)
    close_entry = (_on_closed, None)
    holder["entry"] = entry
    if lock is None:
        handlers.setdefault(event, []).append(entry)
        # The close event is an ordinary event in the same registry.
        handlers.setdefault(close_event, []).append(close_entry)
    else:
        # Register both waiters atomically (a snapshot could miss one).
        with lock:
            handlers.setdefault(event, []).append(entry)
            handlers.setdefault(close_event, []).append(close_entry)
    _log.debug(
        "wait_for %s (timeout=%s)",
        event.__name__,
        f"{timeout}s" if timeout is not None else "none",
    )

    def _cleanup(_: Any) -> None:
        remove_handler(handlers, event, entry, lock=lock)
        remove_handler(handlers, close_event, close_entry, lock=lock)

    task.add_done_callback(_cleanup)

    # Closed between the caller's check and registration: no event is coming.
    if is_closed():
        task._settle(exc=closed_error())
        return task

    if timeout is None:
        return task

    bounded = task.with_timeout(
        timeout,
        message=f"wait_for({event.__name__}) timed out after {timeout}s",
    )
    # On timeout or caller cancellation, unregister the handlers.
    bounded.add_done_callback(lambda _: task.cancel())
    return bounded


def navigation_policy(
    *,
    allow: tuple[str, ...] = (),
    deny: tuple[str, ...] = (),
) -> Callable[[WindowEvent.NavigationRequestedEvent], None]:
    """Build a handler that prevents non-matching navigations.

    ``*`` globs matched against the full URL; deny wins, and an empty *allow* means
    "allow everything not denied".
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


class Subscription(Generic[E]):
    """A handler slot returned by ``on()``.

    Call it to register a handler (the decorator form), or let ``on(event,
    handler)`` register immediately. ``cancel()`` unregisters idempotently.
    """

    __slots__ = ("_handlers", "_event", "_where", "_lock", "_entry", "_cancelled")

    def __init__(
        self,
        handlers: dict[Any, Any],
        event: type[E],
        where: Callable[[E], bool] | None,
        lock: threading.Lock | None,
    ) -> None:
        self._handlers = handlers
        self._event = event
        self._where = where
        self._lock = lock
        self._entry: tuple[Callable[[E], Any], Callable[[E], bool] | None] | None = None
        self._cancelled = False

    def __call__(self, fn: Callable[[E], R]) -> Callable[[E], R]:
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
