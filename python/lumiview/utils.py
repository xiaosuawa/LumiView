"""Prebuilt policy handlers and utilities.

:func:`match_pattern` / :func:`pattern_to_regex` are the shared ``*``
glob matching utilities, used by :func:`navigation_policy` here and by
the Bridge permission chain (:mod:`lumiview.scope` imports them back).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Concatenate, ParamSpec, TypeVar

from lumiview.events import WindowEvent


P = ParamSpec("P")
R = TypeVar("R")


def copy_signature_for_classmethod(_: Callable[P, Any]):
    """Decorator to copy the signature of a callable to a classmethod."""

    def decorator(fn: Callable[..., R]) -> Callable[Concatenate[type[Any], P], R]:
        return fn

    return decorator


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
