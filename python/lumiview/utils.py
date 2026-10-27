"""Prebuilt policy handlers and utilities.

:func:`match_pattern` / :func:`pattern_to_regex` are the shared ``*``
glob matching utilities, used by :func:`navigation_policy` here and by
the Bridge permission chain (:mod:`lumiview.scope` imports them back).
:func:`main_thread` lives here too — it is used by :mod:`lumiview.window`,
:mod:`lumiview.menu` and :mod:`lumiview.tray`, and importing it from
:mod:`lumiview.app` at module level would create a cycle (app imports the
menu/tray modules lazily, but those import app eagerly).
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import inspect
import logging
import re
import time
from concurrent.futures import InvalidStateError
from typing import Any, Callable, Concatenate, Generic, ParamSpec, TypeVar

from lumiview.events import WindowEvent
from lumiview.task import Task


P = ParamSpec("P")
R = TypeVar("R")
E = TypeVar("E")

log = logging.getLogger("lumiview.events")

_MISSING = object()


def _contains(actual: Any, expected: Any) -> bool:
    """Containment used by :func:`contains`.

    - ``dict`` actual + ``dict`` expected: subset match (recursive).
    - ``list``/``tuple`` actual: at least one element contains *expected*.
    - ``str`` actual + ``str`` expected: substring.
    - anything else: ``==``.
    """

    if isinstance(actual, dict) and isinstance(expected, dict):
        return all(
            key in actual and _contains(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(actual, (list, tuple)):
        return any(_contains(item, expected) for item in actual)
    if isinstance(actual, str) and isinstance(expected, str):
        return expected in actual
    return actual == expected


class Contains:
    """Explicit containment matcher for :func:`when` values.

    ``when(payload=contains({"type": "test"}))`` matches a dict that has
    at least those keys (extra keys allowed), a list with at least one
    such element, or a string containing the substring. This is the
    exists semantics — use ``where=lambda e: all(...)`` for forall.
    """

    __slots__ = ("_value",)

    def __init__(self, value: Any) -> None:
        self._value = value

    def __eq__(self, actual: Any) -> bool:
        return _contains(actual, self._value)

    def __ne__(self, actual: Any) -> bool:
        return not self.__eq__(actual)

    def __repr__(self) -> str:
        return f"contains({self._value!r})"


def contains(value: Any) -> Contains:
    """Match a value that *contains* *value* — see :class:`Contains`.

    ::

        when(payload=contains({"type": "test"}))   # dict subset
        when(items=contains({"type": "test"}))     # list contains an element
        when(title=contains("Done"))               # substring
    """

    return Contains(value)


def _match_value(actual: Any, expected: Any) -> bool:
    """Compare an event attribute against a ``when`` pattern value."""

    if isinstance(expected, Contains):
        return expected == actual
    return actual == expected


class Where(Generic[E]):
    """An event predicate with composition operators.

    Instances are callables — ``where(event)`` returns ``bool``. Build
    them with :func:`when`, or use a plain function/lambda::

        win.on(WindowEvent.TitleChangedEvent, where=lambda e: ":" in e.title)

    Combine predicates with ``&``, ``|`` and ``~``::

        busy = when(status="busy")
        failed = when(status="failed")
        win.on(TaskEvent, where=busy | failed)
    """

    __slots__ = ("_fn", "_fields")

    def __init__(
        self,
        fn: Callable[[E], bool],
        fields: frozenset[str] | None = None,
    ) -> None:
        if inspect.iscoroutinefunction(fn):
            raise TypeError(
                "where predicates must be synchronous — they run inline "
                "during dispatch, before handlers"
            )
        self._fn = fn
        self._fields = fields

    def __call__(self, event: E) -> bool:
        return self._fn(event)

    def __and__(self, other: Callable[[E], bool]) -> "Where[E]":
        return Where(lambda e: self(e) and other(e))

    def __or__(self, other: Callable[[E], bool]) -> "Where[E]":
        return Where(lambda e: self(e) or other(e))

    def __invert__(self) -> "Where[E]":
        return Where(lambda e: not self(e))


def when(
    _predicate: Callable[[Any], bool] | None = None,
    /,
    **fields: Any,
) -> Where[Any]:
    """Build an attribute-matching predicate for ``on(..., where=...)``.

    Every keyword is compared against the event's attribute of the same
    name with ``==`` (containers compare exactly, as in Python)::

        win.on(WindowEvent.TitleChangedEvent, where=when(title="Done"))
        win.on(WindowEvent.JsEvent, where=when(event="data.changed"))

    Wrap a value in :func:`contains` for partial matching::

        when(payload=contains({"type": "test"}))   # dict subset
        when(items=contains({"type": "test"}))     # list contains an element
        when(title=contains("Done"))               # substring

    A plain predicate can be wrapped so it composes with field
    patterns::

        positive = when(lambda e: e.value > 0)
        win.on(Event, where=positive & when(kind="x"))(fn)
    """

    if _predicate is not None:
        if fields:
            raise TypeError(
                "when() accepts either a predicate or keyword fields, not both"
            )
        if not callable(_predicate):
            raise TypeError(
                f"when() predicate must be callable; "
                f"got {type(_predicate).__name__}"
            )
        return Where(_predicate)

    if not fields:
        raise TypeError("when() requires a predicate or at least one field")

    def pred(event: Any) -> bool:
        for key, expected in fields.items():
            if not _match_value(getattr(event, key, _MISSING), expected):
                return False
        return True

    return Where(pred, frozenset(fields))


def passes_where(where: Callable[[E], bool] | None, event: E) -> bool:
    """Evaluate a ``where`` predicate, treating a raising predicate as
    a non-match (logged, never propagated into the dispatcher)."""

    if where is None:
        return True
    try:
        return bool(where(event))
    except Exception:
        log.exception("event predicate raised; treating as no match")
        return False


def copy_signature_for_classmethod(_: Callable[P, Any]):
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


def fn_name(fn) -> str:
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


def validate_where(event_cls: type, where: Callable[[Any], bool] | None) -> None:
    """Validate :func:`when` fields against *event_cls* at registration time.

    Plain callables (lambdas, functions) carry no field metadata and are
    not checked — only the field names of a direct :func:`when` result
    are known. Composed predicates (``&``/``|``/``~``) are not checked
    either.
    """

    if where is None:
        return

    if not callable(where):
        raise TypeError(
            f"where must be a callable predicate; got {type(where).__name__}"
        )
    if inspect.iscoroutinefunction(where):
        raise TypeError(
            "where must be a synchronous predicate — it runs inline during "
            "dispatch, before handlers"
        )

    fields = getattr(where, "_fields", None)
    if fields is None:
        return

    if not dataclasses.is_dataclass(event_cls):
        raise TypeError(
            f"{event_cls.__name__} has no fields; when() cannot be used "
            "with this event class"
        )

    known = {f.name for f in dataclasses.fields(event_cls)}
    unknown = fields - known
    if unknown:
        raise TypeError(
            f"{event_cls.__name__} has no field(s) "
            f"{', '.join(sorted(unknown))!r} "
            f"(available: {', '.join(sorted(known))})"
        )


def remove_handler(
    handlers: dict[type, list[tuple]], event: type, entry: tuple
) -> None:
    """Remove a ``(handler, where)`` pair from an event-handler registry."""
    entries = handlers.get(event)
    if entries is None:
        return
    try:
        entries.remove(entry)
    except ValueError:
        pass


def wait_for_event(
    handlers: dict[type[Any], list[tuple]],
    event: type[E],
    *,
    where: Callable[[E], bool] | None,
    timeout: float | None,
    loop: asyncio.AbstractEventLoop | None,
    close_event: type,
    is_closed: Callable[[], bool],
    closed_error: Callable[[], BaseException],
    logger: logging.Logger,
    label: str = "",
) -> Task[E]:
    """One-shot event waiter shared by ``App.wait_for`` / ``Window.wait_for``.

    Registers a temporary handler in *handlers*, resolves the returned
    :class:`Task` with the first matching *event*, and fails it with
    *closed_error* when *close_event* is dispatched (or when *is_closed*
    reports the owner already closed) or with :class:`TimeoutError` after
    *timeout* seconds. Both temporary handlers are removed when the task
    settles, so a timed-out waiter leaves nothing behind.

    *loop* is the asyncio loop the timer is armed on; ``None`` (app not
    running) yields an already-failed task. *logger* and *label* only
    affect the debug log line.
    """
    validate_where(event, where)

    if loop is None:
        return Task._failed(RuntimeError("App is not running"))

    task: Task[E] = Task()
    holder: dict[str, tuple] = {}

    async def _handler(ev: E) -> None:
        if task.done():
            return
        remove_handler(handlers, event, holder["entry"])
        try:
            task.set_result(ev)
        except InvalidStateError:
            # Lost a race with the close/timeout path — it wins.
            pass

    async def _on_closed(_ev: Any) -> None:
        if task.done():
            return
        remove_handler(handlers, event, entry)
        remove_handler(handlers, close_event, close_entry)
        try:
            task.set_exception(closed_error())
        except InvalidStateError:
            pass

    entry = (_handler, where)
    close_entry = (_on_closed, None)
    holder["entry"] = entry
    handlers.setdefault(event, []).append(entry)
    # The close event shares the same registry as ordinary events: it is
    # dispatched exactly like one, so waiting for it needs no second
    # mechanism (and no notification object of its own).
    handlers.setdefault(close_event, []).append(close_entry)
    logger.debug(
        "wait_for %s (%stimeout=%s)",
        event.__name__,
        f"{label}, " if label else "",
        f"{timeout}s" if timeout is not None else "none",
    )

    timer: list[Any] = []

    def _cleanup(_: Any) -> None:
        remove_handler(handlers, event, entry)
        remove_handler(handlers, close_event, close_entry)
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
            remove_handler(handlers, event, entry)
            remove_handler(handlers, close_event, close_entry)
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

        try:
            loop.call_soon_threadsafe(_arm)
        except RuntimeError:
            # Loop already closed (app shutting down) — the close event
            # has failed this waiter already.
            pass

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
