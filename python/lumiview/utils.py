"""Prebuilt policy handlers and utilities.

Shares the ``*`` glob pattern implementation with the Bridge permission
chain (``lumiview._scope.match_pattern``).
"""

from __future__ import annotations

from typing import Callable

from lumiview._scope import match_pattern


def navigation_policy(
    *,
    allow: tuple[str, ...] = (),
    deny: tuple[str, ...] = (),
) -> Callable[[str], bool]:
    """Build a navigation policy for ``Window.create(on_navigation=...)``.

    Patterns are ``*`` globs matched against the full URL; deny wins.
    Empty *allow* means "allow everything not denied" (same semantics as
    the Bridge permission chain).

    Example::

        win = await Window.create(
            url="https://example.com",
            on_navigation=utils.navigation_policy(
                allow=("https://*", "app://*"),
            ),
        )
    """

    def handler(url: str) -> bool:
        for pattern in deny:
            if match_pattern(pattern, url):
                return False
        if not allow:
            return True
        return any(match_pattern(pattern, url) for pattern in allow)

    return handler
