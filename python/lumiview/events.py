"""Event class system.

:class:`WindowBaseEvent` is the true window-event base (context data +
``prevent()``); :class:`WindowEvent` and :class:`AppEvent` are pure
namespace containers — event classes nest inside them (inheriting the
*BaseEvent classes), so both namespace access
(``WindowEvent.TitleChangedEvent``) and isinstance checks
(``isinstance(event, WindowBaseEvent)``) work.

Event classes are ``@dataclass(slots=True, kw_only=True)`` — every field
is a real dataclass field, so static type checkers see the full shape
(no dynamic ``setattr``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lumiview.window import Window
    from lumiview._core import Theme
    from wryview import DragDropEvent


class Event:
    """Common ancestor of all lumiview events (empty)."""

    __slots__ = ()


@dataclass(slots=True, kw_only=True)
class WindowBaseEvent(Event):
    """Base class of all window events: context + prevent primitive.

    Attributes:
        window: The :class:`~lumiview.window.Window` the event belongs to.
            Filled by the dispatch machinery before handlers run.
        prevented: Set by :meth:`prevent` — true when the default
            behavior was cancelled.
    """

    window: Window | None = None
    prevented: bool = False

    def prevent(self) -> None:
        """Cancel the default behavior (meaningful on preventable events)."""
        self.prevented = True


class AppBaseEvent(Event):
    """Base class of all app events."""

    __slots__ = ()


class WindowEvent:
    """Window event namespace (pure module separation)."""

    # Page

    @dataclass(slots=True, kw_only=True)
    class PageLoadStartedEvent(WindowBaseEvent):
        """A page load has started (initial page or a navigation).

        Attributes:
            url: URL of the page being loaded.
        """

        url: str

    @dataclass(slots=True, kw_only=True)
    class PageLoadFinishedEvent(WindowBaseEvent):
        """A page load has finished.

        Attributes:
            url: URL of the page that finished loading.
        """

        url: str

    @dataclass(slots=True, kw_only=True)
    class TitleChangedEvent(WindowBaseEvent):
        """The page title changed.

        Attributes:
            title: The new title.
        """

        title: str

    # Navigation / new window (preventable + extension actions)

    @dataclass(slots=True, kw_only=True)
    class NavigationRequestedEvent(WindowBaseEvent):
        """A navigation is requested in this window.

        Preventable — call :meth:`~WindowBaseEvent.prevent` to block the
        navigation (the WebView stays on the current page).

        Attributes:
            url: The URL being navigated to.
        """

        url: str

    @dataclass(slots=True, kw_only=True)
    class NewWindowRequestedEvent(WindowBaseEvent):
        """The page requested a new window (e.g. ``window.open``).

        wry cannot open a second in-app window, so the default behavior
        is to deny the new window and open *url* in the system browser.
        Preventable — :meth:`~WindowBaseEvent.prevent` blocks the default
        entirely; :meth:`open_in` overrides the browser target.

        Attributes:
            url: The URL the new window would have shown.
        """

        url: str
        _open_url: str | None = None

        def open_in(self, url: str) -> None:
            """Open *url* in the system browser via :func:`webbrowser.open`.

            The in-webview window is denied (wry has no in-app redirect).
            """
            self._open_url = url

    # Drag & drop

    @dataclass(slots=True, kw_only=True)
    class DragEvent(WindowBaseEvent):
        """File drag & drop over the window.

        Only emitted after a handler is first registered for this event
        class (the underlying wryview handler is installed lazily to keep
        WebView2's built-in external-file drops working on Windows).

        Attributes:
            kind: The wryview :class:`~wryview.DragDropEvent` phase —
                ``Enter`` / ``Over`` / ``Leave`` / ``Drop``.
            paths: Absolute paths of the dragged files.
            position: Pointer position inside the window.
        """

        kind: DragDropEvent
        paths: list[str]
        position: tuple[int, int]

    # Downloads

    @dataclass(slots=True, kw_only=True)
    class DownloadStartedEvent(WindowBaseEvent):
        """A download is about to start.

        Preventable — :meth:`~WindowBaseEvent.prevent` cancels the
        download; :meth:`save_to` redirects it to a custom path. The
        default is to save to *suggested_path*.

        Attributes:
            url: The URL being downloaded.
            suggested_path: The path the WebView suggested.
        """

        url: str
        suggested_path: str
        _save_path: str | None = None

        def save_to(self, path: str) -> None:
            """Redirect the download to *path* instead of the suggested one."""
            self._save_path = path

    @dataclass(slots=True, kw_only=True)
    class DownloadCompletedEvent(WindowBaseEvent):
        """A download finished (successfully or not).

        Attributes:
            url: The URL that was downloaded.
            saved_path: The final path on disk, or ``None``.
            success: Whether the download completed without error.
        """

        url: str
        saved_path: str | None
        success: bool

    # Window (tao events)

    class CloseRequestedEvent(WindowBaseEvent):
        """The window received a close request.

        Preventable — :meth:`~WindowBaseEvent.prevent` cancels the
        request; otherwise the window's configured close behavior is
        applied (see :class:`~lumiview.window.CloseBehavior`).
        """

        ...

    @dataclass(slots=True, kw_only=True)
    class ResizedEvent(WindowBaseEvent):
        """The window was resized.

        Attributes:
            width: New window width.
            height: New window height.
        """

        width: int
        height: int

    @dataclass(slots=True, kw_only=True)
    class MovedEvent(WindowBaseEvent):
        """The window was moved.

        Attributes:
            x: New outer position, x coordinate.
            y: New outer position, y coordinate.
        """

        x: int
        y: int

    class FocusedEvent(WindowBaseEvent):
        """The window gained focus."""

        ...

    class UnfocusedEvent(WindowBaseEvent):
        """The window lost focus."""

        ...

    @dataclass(slots=True, kw_only=True)
    class ScaleFactorChangedEvent(WindowBaseEvent):
        """The display scale factor changed (e.g. across monitors).

        Attributes:
            scale_factor: The previous scale factor.
            new_scale_factor: The new scale factor.
        """

        scale_factor: float
        new_scale_factor: float

    @dataclass(slots=True, kw_only=True)
    class ThemeChangedEvent(WindowBaseEvent):
        """The system or window theme changed.

        Attributes:
            theme: The new :class:`~lumiview._core.Theme`.
        """

        theme: Theme

    # IPC

    @dataclass(slots=True, kw_only=True)
    class WebMessageReceivedEvent(WindowBaseEvent):
        """A raw message arrived from the page's ``window.ipc.postMessage``.

        Emitted for every IPC message, even when a :class:`Bridge
        <lumiview.bridge.Bridge>` handles it. With ``untrusted=True``
        this is the only way to receive page messages (no bridge script
        is injected).

        Attributes:
            message: The raw message string as posted by the page.
        """

        message: str


class AppEvent:
    """App event namespace (pure module separation)."""

    class ReadyEvent(AppBaseEvent):
        """The app is ready.

        Emitted on the asyncio loop just before the ``run()`` entry
        point is called — register handlers here to run early setup.
        """

        ...

    class AppCloseEvent(AppBaseEvent):
        """The app is shutting down.

        Emitted during shutdown; handlers are awaited before the asyncio
        loop stops, so cleanup code placed here actually runs.
        """

        ...

    @dataclass(slots=True, kw_only=True)
    class ReopenEvent(AppBaseEvent):
        """The app was reopened via the macOS Dock icon (macOS only).

        Emitted when the user clicks the Dock icon while the app is
        running with no visible windows — restore or recreate a window
        here (e.g. ``win.show()``).

        Attributes:
            has_visible_windows: Whether any window was visible at
                reopen time.
        """

        has_visible_windows: bool


__all__ = [
    "Event", "WindowBaseEvent", "AppBaseEvent",
    "WindowEvent", "AppEvent",
]
