"""System tray icons (tray-icon).

``TrayIconOptions`` is a plain data object (any thread); the native icon
is created on the main thread by ``await TrayIcon.create(options)``.
Dropping the native handle removes the icon from the system tray —
:meth:`TrayIcon.close` does this explicitly on the main thread, and
``App.run()`` does it during shutdown.

Tray events (click, double click, enter/move/leave) arrive through a
single per-process callback registered by :meth:`App.run` and are emitted
as :class:`~lumiview.events.AppEvent.TrayIcon*Event`. Menu items attached
to the tray's menu fire the regular menu activation events.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from lumiview.app import App
from lumiview.utils import main_thread
from lumiview._core import TaoTrayIcon

if TYPE_CHECKING:
    from lumiview.window import _IconSource


def _auto_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


@dataclass(kw_only=True)
class TrayIconOptions:
    """Options for creating a :class:`TrayIcon`.

    Attributes:
        icon: Raw RGBA icon data — ``(rgba_bytes, width, height)``
            (or a file path / PIL image, like
            :class:`~lumiview.window.WindowOptions` icon inputs).
        id: Unique tray icon id; auto-generated when omitted. Tray
            events carry this id.
        tooltip: Hover text (not supported on Linux).
        menu: A :class:`~lumiview.menu.Menu` shown on click (all
            platforms). Note: on Linux the menu cannot be replaced after
            creation.
        menu_on_left_click: Show the menu on left click too.
        menu_on_right_click: Show the menu on right click.
        icon_as_template: macOS — render the icon as a template image
            (auto black/white).
    """

    icon: "_IconSource"
    """Raw RGBA bytes ``(rgba_bytes, width, height)``, a file path, or a
    PIL image (same accepted forms as :class:`~lumiview.window.WindowOptions`
    icon inputs)."""
    id: str | None = None
    tooltip: str | None = None
    menu: Any = None
    menu_on_left_click: bool = True
    menu_on_right_click: bool = True
    icon_as_template: bool = False


class TrayIcon:
    """A system tray icon.

    Create with ``await TrayIcon.create(options)`` — the plain
    constructor raises.
    """

    def __init__(self) -> None:
        raise RuntimeError("Use 'await TrayIcon.create(TrayIconOptions(...))' instead")

    _tray: TaoTrayIcon | None = None
    _id: str = ""

    @property
    def id(self) -> str:
        """The tray icon id (as passed at construction)."""
        return self._id

    @classmethod
    @main_thread
    def create(cls, options: TrayIconOptions) -> "TrayIcon":
        """Create the tray icon on the main thread.

        Returns a :class:`Task` — ``await`` in async code, ``.result()``
        in sync code.
        """
        app = App.get()
        if options.menu is not None:
            options.menu._materialize()
        rgba, width, height = _load_icon(options.icon)
        tray = cls.__new__(cls)
        tray._id = options.id or _auto_id("tray")
        tray._tray = TaoTrayIcon(
            id=tray._id,
            icon=rgba,
            icon_width=width,
            icon_height=height,
            tooltip=options.tooltip,
            menu=options.menu._inner if options.menu is not None else None,
            menu_on_left_click=options.menu_on_left_click,
            menu_on_right_click=options.menu_on_right_click,
        )
        if options.icon_as_template and sys.platform == "darwin":
            tray._tray.set_icon_as_template(True)
        app._trays[tray._id] = tray
        return tray

    @main_thread
    def close(self) -> None:
        """Remove the icon from the system tray (native handle is
        dropped on the main thread)."""
        app = App.get()
        app._trays.pop(self._id, None)
        self._tray = None

    @main_thread
    def set_tooltip(self, tooltip: str | None) -> None:
        """Replace the tooltip (``None`` removes it)."""
        if self._tray is not None:
            self._tray.set_tooltip(tooltip)

    @main_thread
    def set_visible(self, visible: bool) -> None:
        """Show or hide the icon."""
        if self._tray is not None:
            self._tray.set_visible(visible)

    def __repr__(self) -> str:
        return f"TrayIcon(id={self._id!r})"


def _load_icon(icon: "_IconSource") -> tuple[bytes, int, int]:
    """Resolve icon input to ``(rgba_bytes, width, height)``.

    Reuses :func:`lumiview.window._load_icon` (file path / PIL image /
    raw tuple); Pillow is required only for the first two.
    """
    from lumiview.window import _load_icon as _window_load_icon

    return _window_load_icon(icon)
