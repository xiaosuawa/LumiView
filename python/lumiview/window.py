from __future__ import annotations

import asyncio
import json
import logging
import sys
import webbrowser
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable, ParamSpec, TypeVar, overload
from urllib.parse import urlparse
from concurrent.futures import Future
from dataclasses import dataclass

from lumiview.app import App, WindowClosedError
from lumiview.scope import InitContext
from lumiview.serve.base import Serve
from lumiview.utils import copy_signature_for_classmethod, main_thread
from wryview import DragDropEvent, PageLoadEvent, WebView
from wryview._core import NewWindowResponse, WindowHandleKind as WryKind

from lumiview.bridge import BRIDGE_SCRIPT, Bridge
from lumiview._core import (
    AttentionType,
    AxisMotionEvent,
    CloseRequestedEvent,
    CursorIcon,
    DecorationsClickEvent,
    DestroyedEvent,
    FocusedEvent,
    Monitor,
    MovedEvent,
    ProgressState,
    ReceivedImeTextEvent,
    RedrawRequestedEvent,
    ResizeDirection,
    ResizedEvent,
    ScaleFactorChangedEvent,
    StartedEvent,
    StoppedEvent,
    SuspendedEvent,
    TaoEvent,
    TaoWindow,
    Theme,
    ThemeChangedEvent,
    TouchEvent,
    TouchpadPressureEvent,
    UnfocusedEvent,
    ResumedEvent,
    VibrancyMaterial,
    VideoMode,
    WindowEffect,
    WindowHandleKind,
)
from lumiview.events import WindowBaseEvent, WindowEvent
from lumiview.task import Task, run_async

if TYPE_CHECKING:
    from PIL.Image import Image as _PILImage

    from lumiview._core import TaoWindow
else:
    _PILImage = object

_IconSource = str | tuple[bytes, int, int] | _PILImage

P = ParamSpec("P")
R = TypeVar("R")

log = logging.getLogger("lumiview.window")


class CloseBehavior(Enum):
    """
    What happens when the window receives a close request.

    - ``Close`` — destroy the window (default).
    - ``Hide`` — hide the window instead of destroying it.
    - ``Ignore`` — do nothing.
    """

    Close = auto()
    Hide = auto()
    Ignore = auto()


# Window
@dataclass(kw_only=True)
class WindowOptions:
    """Options for creating a :class:`Window`.

    Passed to :meth:`Window.create` either as a single object
    (``await Window.create(WindowOptions(...))``) or as keyword
    arguments (``await Window.create(title=..., url=...)``).
    """

    # Content
    title: str = "lumiview"
    """Window title shown in the titlebar."""
    url: str | None = None
    """URL to load as the initial page."""
    html: str | None = None
    """HTML string to show instead of a URL."""
    source: Serve | list[Serve] | None = None
    """One or more :class:`~lumiview.serve.Serve` handlers
    registered as ``lumiview://`` custom protocols."""
    # Geometry
    width: int = 800
    """Initial inner width in logical pixels."""
    height: int = 600
    """Initial inner height in logical pixels."""
    position: tuple[float, float] | None = None
    """Initial outer position ``(x, y)`` in logical pixels.

    Without ``monitor`` this is relative to the primary screen's
    top-left; with ``monitor`` it becomes local to that monitor's
    top-left."""
    monitor: Monitor | None = None
    """The :class:`~lumiview._core.Monitor` to open the window on.

    Without ``position`` the window is centered on this monitor;
    with ``position``, *position* is interpreted as local to the
    monitor's top-left (in logical pixels)."""
    min_size: tuple[float, float] | None = None
    """Minimum inner size ``(width, height)``."""
    max_size: tuple[float, float] | None = None
    """Maximum inner size ``(width, height)``."""
    # Appearance
    visible: bool = True
    """Whether the window starts visible."""
    decorations: bool = True
    """Whether the window has a native titlebar."""
    resizable: bool = True
    """Whether the user can resize the window."""
    transparent: bool = False
    """Whether the window background is transparent (may need
    ``undecorated_shadow`` on some platforms)."""
    maximized: bool = False
    """Whether the window starts maximized."""
    always_on_top: bool = False
    """Whether the window floats above other windows."""
    undecorated_shadow: bool | None = None
    """Shadow for undecorated windows — ``None`` lets the platform
    decide."""
    icon: _IconSource | None = None
    """Window icon — a file path, ``(rgba_bytes, width, height)``
    tuple, or ``PIL.Image.Image`` object."""
    # Behavior
    focused: bool = True
    """Whether the window starts focused."""
    focusable: bool = True
    """Whether the window can receive focus."""
    minimizable: bool = True
    """Whether the user can minimize the window."""
    maximizable: bool = True
    """Whether the user can maximize the window."""
    closable: bool = True
    """Whether the user can close the window."""
    close_behavior: CloseBehavior = CloseBehavior.Close
    """The :class:`CloseBehavior` applied on close request."""
    visible_on_all_workspaces: bool = False
    """Whether the window appears on all workspaces (Linux)."""
    content_protection: bool = False
    """Whether window content is hidden from screenshots (Windows)."""
    # Bridge
    bridge: Bridge | None = None
    """The :class:`~lumiview.bridge.Bridge` for IPC. ``None`` isolates
    the window — raw messages still surface as
    :class:`~lumiview.events.WindowEvent.WebMessageReceivedEvent`."""
    untrusted: bool = False
    """Skip bridge-script injection entirely; ``emit()`` events are
    never delivered to the page."""
    # WebView
    web_context: Any = None
    """Shared WebView context passed to wryview."""
    data_directory: str | None = None
    """WebView user-data folder."""
    incognito: bool = False
    """Start with no persistent data."""
    proxy: str | None = None
    """Proxy URL string (e.g. ``"http://host:port"``)."""
    user_agent: str | None = None
    """Custom user agent for the WebView."""
    autoplay: bool = False
    """Allow autoplaying media."""
    hotkeys_zoom: bool = False
    """Enable zoom hotkeys (Ctrl+/-/wheel) and touchpad pinch zoom.

    Windows WebView2 only — no effect on macOS and Linux. Disabled by
    default to match Tauri (WebView2 defaults both to enabled)."""
    clipboard: bool = True
    """Enable clipboard access."""
    javascript: bool = True
    """Enable JavaScript execution."""
    back_forward_gestures: bool = False
    """Enable swipe back/forward navigation (Windows)."""
    https_scheme: bool = True
    """Treat the custom protocol as secure from https pages
    (Windows WebView2)."""
    default_context_menus: bool = True
    """Show the default right-click context menu."""
    drag_drop: bool = False
    """Enable custom drag-drop events (``WindowEvent.DragEvent``).

    Registering a custom drag-drop handler disables WebView2's built-in
    external-file drops on Windows, so this must be decided at creation
    — it cannot be enabled lazily after the WebView exists.
    """
    background_color: tuple[int, int, int, int] | None = None
    """WebView background ``(r, g, b, a)``."""
    headers: dict[str, str] | None = None
    """Extra HTTP headers for the initial load."""
    devtools: bool = False
    """Whether developer tools are available."""
    # Pre-creation hook
    prepare: Callable[[Window], None] | None = None
    """Called with the :class:`Window` shell before the native window
    and WebView are created — the earliest point to register event
    handlers."""

    def __post_init__(self) -> None:
        if self.bridge is not None and self.untrusted:
            raise ValueError("bridge and untrusted are mutually exclusive")


class Window:
    """A window with an embedded WebView.

    Create instances with ``await Window.create(...)`` — the plain
    constructor raises :class:`RuntimeError`, because windows can only
    be created on the main thread inside ``app.run()``.

    Every operation that touches the native window or WebView runs on
    the main thread and returns a :class:`~lumiview.task.Task` —
    ``await`` it in async code, or use ``.result()`` in sync code.
    """

    def __init__(self) -> None:
        if TYPE_CHECKING:
            self._app: App
            self._win_id: int
            self._window: TaoWindow | None
            """Unsendable, main-thread bound. Never hold on other threads."""
            self._webview: WebView | None
            """Unsendable, main-thread bound. Never hold on other threads."""
            self._bridge: Bridge
            self._hooks: dict[type[WindowBaseEvent], list[Callable[..., Any]]]
            self._close_behavior: CloseBehavior
            self._close_pending: bool
            self._drag_enabled: bool
            self._untrusted: bool
        raise RuntimeError("Use 'await Window.create(...)' instead")

    @overload
    @classmethod
    def create(cls, _options: WindowOptions, /) -> Task[Window]: ...

    @overload
    @classmethod
    @copy_signature_for_classmethod(WindowOptions)
    def create(cls, **kwargs: Any) -> Task[Window]: ...

    @classmethod
    @main_thread
    def create(
        cls,
        _options: WindowOptions | None = None,
        /,
        **kwargs: Any,
    ) -> Window:
        """Create a new :class:`Window`.

        Two calling forms::

            win = await Window.create(WindowOptions(title="MyApp", url=...))
            win = await Window.create(title="MyApp", url=...)

        The ``options.prepare`` hook (if set) receives the window shell
        before the native window and WebView are created, so early
        events are not lost. Returns a :class:`Task` resolving to the
        window; must be awaited (or ``.result()``-blocked) from a
        non-GUI thread.

        Parameters:
            _options: A prebuilt :class:`WindowOptions` object
                (mutually exclusive with keyword arguments).
            **kwargs: :class:`WindowOptions` fields as keyword
                arguments.
        """
        app = App.get()

        if _options is not None:
            if kwargs:
                raise TypeError(
                    "Cannot specify both a WindowOptions object and keyword arguments"
                )
            options = _options

        else:
            options = WindowOptions(**kwargs)

        if options.untrusted and options.bridge is not None:
            raise ValueError(
                "untrusted mode cannot be combined with a bridge "
                "(no scripts are injected)"
            )

        self = cls.__new__(cls)
        self._app = app
        self._window = None
        self._webview = None
        self._hooks = {}

        ctx = InitContext(inject_script=BRIDGE_SCRIPT, window=self, options=options)
        if not options.untrusted and options.bridge is not None:
            ctx = options.bridge._run_on_init(ctx)

        self._close_behavior = options.close_behavior
        self._close_pending = False
        self._drag_enabled = options.drag_drop
        self._bridge = options.bridge or Bridge()
        self._untrusted = options.untrusted

        # Resolve source → url / html / custom_protocols
        custom_protocols: dict[str, Any] = {}
        resolved_url: str | None = None
        resolved_html: str | None = None

        serve_sources: list[Serve]
        if isinstance(options.source, (list, tuple)):
            serve_sources = [s for s in options.source]
        elif isinstance(options.source, str):
            raise TypeError(
                "source must be a Serve instance or a list of them; "
                "use url= for a URL string"
            )
        elif options.source is not None:
            serve_sources = [options.source]
        else:
            serve_sources = []

        for serve in serve_sources:
            if not isinstance(serve, Serve):
                raise TypeError(
                    f"source entries must be Serve instances; got "
                    f"{type(serve).__name__} — subclass Serve or use "
                    "Handler(fn) to adapt a plain function"
                )
            scheme = serve.scheme
            if scheme in custom_protocols:
                raise ValueError(f"Duplicate custom protocol scheme: {scheme!r}")
            custom_protocols[scheme] = _make_protocol_handler(serve)

        if serve_sources:
            resolved_url = f"{serve_sources[0].scheme}://app/"

        if options.url is not None:
            resolved_url = options.url

        elif options.html is not None:
            resolved_html = options.html
            # html takes precedence over the source's initial load;
            # custom_protocols are still registered.
            resolved_url = None

        if options.prepare is not None:
            options.prepare(self)

        # Tao window
        if options.icon is not None:
            rgba, iw, ih = _load_icon(options.icon)
            icon_data = (iw, ih, rgba)  # (width, height, rgba) per _core
        else:
            icon_data = None

        # Resolve the initial position. tao has no "open on monitor"
        # builder option — targeting a monitor means placing the window
        # at that monitor's screen coordinates. With *monitor*, an
        # explicit *position* is local to the monitor's top-left
        # (logical pixels); without one, the window is centered.
        if options.monitor is not None:
            m = options.monitor
            sf = m.scale_factor()
            mx, my = m.position()
            if options.position is None:
                mw, mh = m.size()
                position = (
                    mx / sf + (mw / sf - options.width) / 2,
                    my / sf + (mh / sf - options.height) / 2,
                )
            else:
                lx, ly = options.position
                position = (mx / sf + lx, my / sf + ly)
        else:
            position = options.position

        if app._event_loop is None:
            raise RuntimeError(
                "App is not running — create windows inside app.run(entry)"
            )

        tao_win = TaoWindow(
            app._event_loop,
            title=options.title,
            width=float(options.width),
            height=float(options.height),
            position=position,
            min_size=options.min_size,
            max_size=options.max_size,
            resizable=options.resizable,
            minimizable=options.minimizable,
            maximizable=options.maximizable,
            closable=options.closable,
            maximized=options.maximized,
            visible=options.visible,
            decorations=options.decorations,
            undecorated_shadow=options.undecorated_shadow,
            always_on_top=options.always_on_top,
            focused=options.focused,
            focusable=options.focusable,
            content_protection=options.content_protection,
            visible_on_all_workspaces=options.visible_on_all_workspaces,
            transparent=options.transparent,
            icon=icon_data,
        )

        try:
            # WebView

            if sys.platform == "linux":
                handle = tao_win.gtk_container()
                kind = WryKind.Gtk
            else:
                handle = tao_win.native_handle()
                our = tao_win.native_handle_kind()
                kind = {
                    WindowHandleKind.Win32: WryKind.Win32,
                    WindowHandleKind.AppKit: WryKind.AppKit,
                    WindowHandleKind.X11: WryKind.X11,
                }[our]

            webview = WebView(
                handle,
                width=options.width,
                height=options.height,
                url=resolved_url,
                html=resolved_html,
                transparent=options.transparent,
                background_color=options.background_color,
                devtools=options.devtools,
                incognito=options.incognito,
                user_agent=options.user_agent,
                autoplay=options.autoplay,
                javascript_enabled=options.javascript,
                hotkeys_zoom=options.hotkeys_zoom,
                initialization_script=None if self._untrusted else ctx.inject_script,
                ipc_handler=self._make_ipc_handler(),
                on_navigation=self._dispatch_navigation,
                on_page_load=self._dispatch_page_load,
                on_title_changed=lambda t: self._emit(
                    WindowEvent.TitleChangedEvent(title=t)
                ),
                on_new_window=self._dispatch_new_window,
                drag_drop_handler=(
                    self._dispatch_drag_drop if options.drag_drop else None
                ),
                custom_protocols=custom_protocols or None,
                proxy=(
                    _parse_proxy(options.proxy) if options.proxy is not None else None
                ),
                back_forward_gestures=options.back_forward_gestures,
                clipboard=options.clipboard,
                data_directory=options.data_directory,
                web_context=options.web_context,
                headers=(
                    list(options.headers.items())
                    if options.headers is not None
                    else None
                ),
                https_scheme=options.https_scheme,
                default_context_menus=options.default_context_menus,
                on_download_started=self._dispatch_download_started,
                on_download_completed=self._dispatch_download_completed,
                as_child=True,
                parent_hwnd_kind=kind,
            )
        except Exception:
            del tao_win
            raise

        self._webview = webview
        self._window = tao_win

        win_id = tao_win.id()
        self._win_id = win_id
        app._windows[win_id] = self
        log.info("Window created (id=%s)", win_id)

        try:
            if options.transparent:
                # Wry creates its child HWND after Tao's parent surface. Refresh
                # the retained transparent backing once more so the first
                # composited frame cannot reuse Tao's opaque creation bitmap.
                tao_win._redraw_transparent_surface()

            if options.bridge is not None:
                options.bridge._run_on_ready(self)
        except Exception:
            self.close()
            del tao_win
            raise

        return self

    # Content

    @main_thread
    def load_url(self, url: str) -> None:
        """Navigate the WebView to *url*."""
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.load_url(url)

    @main_thread
    def load_html(self, html: str) -> None:
        """Render *html* as the current page."""
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.load_html(html)

    @main_thread
    def reload(self) -> None:
        """Reload the current page."""
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.reload()

    # JavaScript

    def eval_js(self, script: str) -> Task[str]:
        """
        Evaluate JavaScript in the page and return its value.

        Unlike wryview's fire-and-forget ``eval_js``, this captures the
        script's return value (as a string) into the returned
        :class:`~lumiview.task.Task`.
        """
        app = App.get()
        handle: Task[str] = Task()

        def _do():
            if self._webview is not None:
                self._webview.eval_js_with_callback(
                    script, lambda result: handle.set_result(result)
                )
            else:
                handle.set_exception(WindowClosedError(self._win_id))

        dispatched = app.call_on_main(_do)
        if not handle.done():
            dispatched.add_done_callback(
                lambda d: _propagate_dispatch_failure(handle, d)
            )
        return handle

    # Appearance

    @main_thread
    def set_icon(self, icon: _IconSource) -> None:
        """
        Set the window icon.

        *icon* can be a file path (requires Pillow) or raw RGBA data::

            win.set_icon("path/to/icon.png")
            win.set_icon((rgba_bytes, 64, 64))
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        rgba, w, h = _load_icon(icon)
        self._window.set_window_icon(w, h, rgba)

    @main_thread
    def apply_effect(
        self,
        effect: WindowEffect,
        color: tuple[int, int, int, int] | None = None,
        material: VibrancyMaterial | None = None,
    ) -> None:
        """
        Apply a native window background material.

        *material* selects the macOS
        :class:`~lumiview._core.VibrancyMaterial` when
        ``effect == WindowEffect.Vibrancy`` (default ``Sidebar``).
        Unsupported platforms or OS versions raise
        :class:`NotImplementedError`.
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.apply_effect(effect, color, material)

    @main_thread
    def clear_effect(self, effect: WindowEffect) -> None:
        """
        Clear a native material previously applied to this window.
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.clear_effect(effect)

    # Geometry

    @main_thread
    def set_bounds(self, x: float, y: float, w: float, h: float) -> None:
        """Resize and position the WebView inside the window."""
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.set_bounds(x, y, w, h)

    @main_thread
    def set_size(self, width: float, height: float) -> None:
        """Set the window's inner size in logical pixels."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_inner_size(width, height)

    @main_thread
    def show(self) -> None:
        """Show the window (and un-minimize it if needed)."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_visible(True)
        self._window.set_minimized(False)

    @main_thread
    def hide(self) -> None:
        """Hide the window."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_visible(False)

    @main_thread
    def focus(self, flag: bool = True) -> None:
        """Give or remove keyboard focus (``flag`` = focus)."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_focused(flag)

    @main_thread
    def minimize(self, flag: bool = True) -> None:
        """Minimize or restore the window (``flag`` = minimize)."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_minimized(flag)

    @main_thread
    def toggle_maximize(self) -> bool:
        """Toggle maximize state.

        Returns:
            True if the window is now maximized.
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        maximized = not self._window.is_maximized()
        self._window.set_maximized(maximized)
        return maximized

    @main_thread
    def set_fullscreen(self, fullscreen: bool) -> None:
        """
        Enter or exit fullscreen.
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_fullscreen(fullscreen)

    @main_thread
    def is_maximized(self) -> bool:
        """True if the window is maximized."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.is_maximized()

    @main_thread
    def start_dragging(self) -> None:
        """Start an OS-level window drag (for custom titlebars)."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.drag_window()

    @main_thread
    def start_resize_dragging(self, direction: ResizeDirection) -> None:
        """Start an OS-level resize drag from *direction* (for custom
        titlebars)."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.drag_resize_window(direction)

    @main_thread
    def set_title(self, title: str) -> None:
        """Set the window title."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_title(title)

    @main_thread
    def title(self) -> str:
        """Return the current window title."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.title()

    @main_thread
    def theme(self) -> Theme:
        """Return the window's effective color theme."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.theme()

    @main_thread
    def set_theme(self, theme: Theme | None = None) -> None:
        """Force the window theme (``None`` restores the system default)."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_theme(theme)

    @main_thread
    def inner_size(self) -> tuple[float, float]:
        """Return the inner size ``(width, height)`` in logical pixels."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.inner_size()

    @main_thread
    def inner_position(self) -> tuple[float, float]:
        """Return the client area position ``(x, y)`` in logical pixels.

        Raises :class:`NotImplementedError` on platforms that cannot
        report it (Wayland).
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.inner_position()

    @main_thread
    def outer_position(self) -> tuple[float, float]:
        """Return the window position ``(x, y)`` in logical pixels."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.outer_position()

    @main_thread
    def cursor_position(self) -> tuple[float, float]:
        """Return the cursor position inside the window in logical pixels."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.cursor_position()

    @main_thread
    def outer_size(self) -> tuple[int, int]:
        """Return the outer size ``(width, height)`` in logical pixels."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.outer_size()

    @main_thread
    def scale_factor(self) -> float:
        """Return the window's DPI scale factor."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.scale_factor()

    @main_thread
    def set_outer_position(self, x: float, y: float) -> None:
        """Move the window so its top-left corner is at ``(x, y)``."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_outer_position(x, y)

    @main_thread
    def set_min_inner_size(self, width: float, height: float) -> None:
        """Set the minimum inner size in logical pixels."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_min_inner_size(width, height)

    @main_thread
    def set_max_inner_size(self, width: float, height: float) -> None:
        """Set the maximum inner size in logical pixels."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_max_inner_size(width, height)

    @main_thread
    def set_resizable(self, flag: bool) -> None:
        """Allow or disallow resizing the window."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_resizable(flag)

    @main_thread
    def set_focusable(self, flag: bool) -> None:
        """Allow or disallow the window receiving focus."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_focusable(flag)

    @main_thread
    def set_content_protection(self, flag: bool) -> None:
        """Hide window content from screenshots (Windows)."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_content_protection(flag)

    @main_thread
    def set_visible_on_all_workspaces(self, flag: bool) -> None:
        """Show the window on all workspaces (Linux)."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_visible_on_all_workspaces(flag)

    @main_thread
    def set_always_on_bottom(self, flag: bool) -> None:
        """Pin the window below other windows."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_always_on_bottom(flag)

    # State queries

    @main_thread
    def is_focused(self) -> bool:
        """True if the window currently has keyboard focus."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.is_focused()

    @main_thread
    def is_resizable(self) -> bool:
        """True if the window can be resized by the user."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.is_resizable()

    @main_thread
    def is_decorated(self) -> bool:
        """True if the window has a native titlebar and frame."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.is_decorated()

    @main_thread
    def is_closable(self) -> bool:
        """True if the window can be closed by the user."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.is_closable()

    @main_thread
    def is_minimizable(self) -> bool:
        """True if the window can be minimized by the user."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.is_minimizable()

    @main_thread
    def is_maximizable(self) -> bool:
        """True if the window can be maximized by the user."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.is_maximizable()

    @main_thread
    def is_always_on_top(self) -> bool:
        """True if the window floats above other windows."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.is_always_on_top()

    @main_thread
    def is_fullscreen(self) -> bool:
        """True if the window is currently fullscreen."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.is_fullscreen()

    @main_thread
    def set_minimizable(self, flag: bool) -> None:
        """Allow or disallow minimizing the window."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_minimizable(flag)

    @main_thread
    def set_maximizable(self, flag: bool) -> None:
        """Allow or disallow maximizing the window."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_maximizable(flag)

    @main_thread
    def set_closable(self, flag: bool) -> None:
        """Allow or disallow closing the window."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_closable(flag)

    @main_thread
    def set_always_on_top(self, flag: bool) -> None:
        """Float the window above (or below) other windows."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_always_on_top(flag)

    @main_thread
    def set_decorations(self, flag: bool) -> None:
        """Show or hide the native titlebar and window frame."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_decorations(flag)

    @main_thread
    def set_cursor_visible(self, flag: bool) -> None:
        """Show or hide the cursor over the window."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_cursor_visible(flag)

    @main_thread
    def set_cursor_icon(self, icon: CursorIcon) -> None:
        """Set the cursor shape shown while hovering the window."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_cursor_icon(icon)

    @main_thread
    def set_cursor_grab(self, grab: bool) -> None:
        """Lock (``True``) or release (``False``) the cursor to the
        window. Useful for games or drawing apps."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_cursor_grab(grab)

    @main_thread
    def set_ignore_cursor_events(self, ignore: bool) -> None:
        """Make the window transparent to mouse events (``True`` =
        clicks pass through)."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_ignore_cursor_events(ignore)

    @main_thread
    def set_cursor_position(self, x: float, y: float) -> None:
        """Move the cursor to a logical position inside the window."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_cursor_position(x, y)

    @main_thread
    def request_user_attention(self, request_type: AttentionType | None = None) -> None:
        """Ask the OS to draw the user's attention to this window
        (taskbar flash / Dock bounce).

        ``None`` clears a previous request.
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.request_user_attention(request_type)

    @main_thread
    def set_ime_position(self, x: float, y: float) -> None:
        """Place the input method editor (candidate window) at a
        logical position inside the window."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_ime_position(x, y)

    @main_thread
    def set_progress_bar(
        self,
        state: ProgressState | None = None,
        progress: float | None = None,
    ) -> None:
        """Set the Windows taskbar progress bar.

        ``state=None`` removes it; *progress* is 0.0–100.0 (ignored for
        ``Indeterminate``).
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_progress_bar(state, progress)

    @main_thread
    def set_focused(self, flag: bool) -> None:
        """Give or remove keyboard focus."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_focused(flag)

    @main_thread
    def set_minimized(self, flag: bool) -> None:
        """Minimize or restore the window."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_minimized(flag)

    @main_thread
    def is_minimized(self) -> bool:
        """True if the window is minimized."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.is_minimized()

    @main_thread
    def is_visible(self) -> bool:
        """True if the window is visible."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.is_visible()

    @main_thread
    def toggle_visibility(self) -> None:
        """Toggle the window between shown and hidden.

        Visible (and not minimized) → hidden; otherwise → shown and
        un-minimized. A single main-thread round trip — the natural fit
        for "click the tray icon to toggle the window".
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        if self._window.is_visible() and not self._window.is_minimized():
            self._window.set_visible(False)
        else:
            self._window.set_visible(True)
            self._window.set_minimized(False)

    @main_thread
    def request_redraw(self) -> None:
        """Ask the compositor to redraw the window."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.request_redraw()

    @main_thread
    def native_handle(self) -> int:
        """Return the raw OS window handle (HWND / NSView / X11 window).

        See :meth:`native_handle_kind` for the handle type.
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.native_handle()

    @main_thread
    def native_handle_kind(self) -> WindowHandleKind:
        """
        Return the OS handle type (Win32 / AppKit / X11 / Wayland / Gtk).
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.native_handle_kind()

    @main_thread
    def gtk_container(self) -> int:
        """Return the raw GTK container widget pointer (Linux only).

        Raises :class:`AttributeError` on other platforms.
        """
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.gtk_container()

    # Monitors

    @main_thread
    def current_monitor(self) -> Monitor | None:
        """Return the :class:`~lumiview._core.Monitor` the window is
        currently on, or ``None``."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.current_monitor()

    @main_thread
    def available_monitors(self) -> list[Monitor]:
        """Return all monitors currently connected."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.available_monitors()

    @main_thread
    def primary_monitor(self) -> Monitor | None:
        """Return the primary monitor, or ``None``."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.primary_monitor()

    @main_thread
    def monitor_from_point(self, x: float, y: float) -> Monitor | None:
        """Return the monitor containing the given physical screen point."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.monitor_from_point(x, y)

    @main_thread
    def set_borderless_fullscreen(self, monitor: Monitor | None = None) -> None:
        """Enter borderless fullscreen on *monitor* (``None`` = the
        current monitor)."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_borderless_fullscreen(monitor)

    @main_thread
    def set_exclusive_fullscreen(self, mode: VideoMode) -> None:
        """Enter exclusive fullscreen at *mode*'s resolution and
        refresh rate (see :meth:`~lumiview._core.Monitor.video_modes`)."""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_exclusive_fullscreen(mode)

    # Platform extensions
    # Each method exists only on its platform — calling it elsewhere
    # raises AttributeError (the underlying _core method is absent).

    # Windows

    @main_thread
    def set_skip_taskbar(self, skip: bool) -> None:
        """Hide or show the window in the taskbar. **Windows only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_skip_taskbar(skip)

    @main_thread
    def set_taskbar_icon(self, icon: _IconSource | None = None) -> None:
        """Replace the taskbar icon (``None`` restores the window icon).
        **Windows only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        data = None if icon is None else _icon_tuple(icon)
        self._window.set_taskbar_icon(data)

    @main_thread
    def set_overlay_icon(self, icon: _IconSource | None = None) -> None:
        """Set an overlay badge on the taskbar icon (``None`` removes
        it). **Windows only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        data = None if icon is None else _icon_tuple(icon)
        self._window.set_overlay_icon(data)

    @main_thread
    def set_enable(self, enabled: bool) -> None:
        """Enable or disable the window (disabled windows ignore mouse
        input). **Windows only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_enable(enabled)

    @main_thread
    def set_rtl(self, rtl: bool) -> None:
        """Right-to-left layout for the window. **Windows only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_rtl(rtl)

    @main_thread
    def reset_dead_keys(self) -> None:
        """Reset the OS dead-key state. **Windows only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.reset_dead_keys()

    @main_thread
    def set_undecorated_shadow(self, shadow: bool) -> None:
        """Toggle the shadow of an undecorated window at runtime.
        **Windows only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_undecorated_shadow(shadow)

    @main_thread
    def has_undecorated_shadow(self) -> bool:
        """Whether the undecorated window shadow is enabled.
        **Windows only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.has_undecorated_shadow()

    # macOS

    @main_thread
    def set_badge_label(self, label: str | None) -> None:
        """Set the text in the macOS Dock badge (``None`` clears it).
        **macOS only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_badge_label(label)

    @main_thread
    def set_simple_fullscreen(self, fullscreen: bool) -> bool:
        """Toggle "simple fullscreen" (content covers the whole screen,
        including the menu bar). Returns the resulting state.
        **macOS only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.set_simple_fullscreen(fullscreen)

    @main_thread
    def set_titlebar_transparent(self, transparent: bool) -> None:
        """Make the native titlebar transparent (custom chrome overlays
        the titlebar area). **macOS only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_titlebar_transparent(transparent)

    @main_thread
    def set_traffic_light_inset(self, x: float, y: float) -> None:
        """Set the traffic-light (window controls) inset in logical
        points. **macOS only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_traffic_light_inset(x, y)

    @main_thread
    def set_has_shadow(self, has_shadow: bool) -> None:
        """Toggle the window shadow. **macOS only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_has_shadow(has_shadow)

    @main_thread
    def has_shadow(self) -> bool:
        """Whether the window currently has a shadow. **macOS only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window.has_shadow()

    # Linux (GTK)

    @main_thread
    def set_badge_count(self, count: int | None) -> None:
        """Set the number shown in the GTK badge (``None`` clears it).
        **Linux only.**"""
        if self._window is None:
            raise WindowClosedError(self._win_id)
        self._window.set_badge_count(count)

    # Bridge

    def emit(self, event: str, payload: Any = None) -> Task[None]:
        """
        Send an event to JavaScript ``window.lumiview.listen`` listeners.

        JS side::

            const unlisten = window.lumiview.listen("my-event", (payload) => {
                console.log(payload);
            });

        Python side::

            await win.emit("my-event", {"key": "value"})

        The returned :class:`Task` resolves when the script has been
        delivered to the WebView (not when listeners have processed it).
        """
        if self._untrusted:
            # untrusted mode injects no bridge script — nothing can
            # receive the event, so complete immediately.
            return Task._done(None)

        app = App.get()
        handle: Task[None] = Task()

        payload_json = json.dumps(
            {"event": event, "payload": payload},
            default=str,
        )
        script = f"window.lumiview._dispatchEvent({payload_json})"

        def _do():
            if self._webview is not None:
                self._webview.eval_js_with_callback(
                    script, lambda _result: handle.set_result(None)
                )
            else:
                handle.set_exception(WindowClosedError(self._win_id))

        dispatched = app.call_on_main(_do)
        if not handle.done():
            dispatched.add_done_callback(
                lambda d: _propagate_dispatch_failure(handle, d)
            )
        return handle

    # Events

    def on(self, event: type[WindowBaseEvent]):
        """
        Register a handler for an event class::

            win.on(WindowEvent.TitleChangedEvent)(handler)

        The handler receives the event object.
        """
        if event is WindowEvent.DragEvent and not self._drag_enabled:
            raise RuntimeError(
                "WindowEvent.DragEvent requires WindowOptions(drag_drop=True) — "
                "registering a custom drag-drop handler at creation disables "
                "WebView2's built-in external-file drops, so it cannot be "
                "enabled lazily after the WebView exists."
            )

        def decorator(fn):
            self._hooks.setdefault(event, []).append(fn)
            return fn

        return decorator

    def _emit(self, event: WindowBaseEvent) -> Task[None] | None:
        """
        Dispatch *event* to handlers registered for its class.

        Returns a completion :class:`Task` or ``None`` when there is
        no loop or no handlers. ``event.window`` is set to this window.
        """
        event.window = self
        if self._app._async_loop is None:
            return

        handlers = self._hooks.get(type(event), [])

        if not handlers:
            return

        log.debug(
            "dispatching %s to %d handler(s)", type(event).__name__, len(handlers)
        )
        done: Task[None] = Task()

        async def _dispatch() -> None:
            try:
                for fn in handlers:
                    try:
                        await run_async(fn, event, pool=self._app._threadpool)
                    except Exception:
                        logging.getLogger("lumiview.window").exception(
                            f"Error in {type(event).__name__} handler: {fn}",
                        )
            finally:
                done.set_result(None)

        loop = self._app._async_loop
        assert loop is not None

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_dispatch()))

        return done

    def _dispatch_page_load(self, ev: PageLoadEvent, url: str) -> None:
        """
        wryview ``on_page_load`` callback — dispatch a page event.
        """
        if ev == PageLoadEvent.Started:
            self._emit(WindowEvent.PageLoadStartedEvent(url=url))
        else:
            self._emit(WindowEvent.PageLoadFinishedEvent(url=url))

    def _dispatch_navigation(self, url: str) -> bool:
        """
        wryview ``on_navigation`` callback — ``False`` blocks.
        """
        event = WindowEvent.NavigationRequestedEvent(url=url)
        done = self._emit(event)
        if done is not None:
            done.result()
        return not event.prevented

    def _dispatch_new_window(self, url: str) -> NewWindowResponse:
        """
        wryview ``on_new_window`` callback — decide the response.

        wry only supports ``Allow``/``Deny`` (no URL redirect), so
        ``open_in(url)`` opens *url* in the system browser. Default:
        deny the in-webview window and open it externally.
        """
        event = WindowEvent.NewWindowRequestedEvent(url=url)
        done = self._emit(event)
        if done is not None:
            done.result()
        open_url = event._open_url
        if open_url is not None:
            try:
                webbrowser.open(open_url)
            except Exception:
                pass
        elif not event.prevented:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        return NewWindowResponse.Deny

    def _dispatch_download_started(self, url: str, suggested_path: str) -> bool | str:
        """
        wryview ``on_download_started`` callback.

        Returns ``True`` to allow, ``False`` to cancel, or a string
        path to redirect the download.
        """
        event = WindowEvent.DownloadStartedEvent(url=url, suggested_path=suggested_path)
        done = self._emit(event)
        if done is not None:
            done.result()
        save_path = event._save_path
        if save_path is not None:
            return save_path
        if event.prevented:
            return False
        return True

    def _dispatch_download_completed(
        self, url: str, saved_path: str | None, success: bool
    ) -> None:
        """
        wryview ``on_download_completed`` callback — fire the event.
        """
        self._emit(
            WindowEvent.DownloadCompletedEvent(
                url=url, saved_path=saved_path, success=success
            )
        )

    def _dispatch_drag_drop(
        self, ev: DragDropEvent, paths: list[str], position: tuple[int, int]
    ) -> bool:
        """
        wryview ``drag_drop_handler`` callback — dispatch the event.

        Returns whether at least one handler received the event.
        """
        if ev == DragDropEvent.Unknown:  # future variants
            return False
        return (
            self._emit(WindowEvent.DragEvent(kind=ev, paths=paths, position=position))
            is not None
        )

    # Lifecycle

    def _on_tao_event(self, event: TaoEvent) -> None:
        """
        Handle a tao window event routed from the app (GUI thread).
        """
        if isinstance(event, ResizedEvent):
            if self._webview is not None and self._window is not None:
                sf = self._window.scale_factor()
                self._webview.set_bounds(0, 0, event.width / sf, event.height / sf)
                # Resize the child HWND first, then replace the parent
                # backing surface. This prevents either old edge from
                # surviving into the newly composed frame.
                self._window._redraw_transparent_surface()
            self._emit(
                WindowEvent.ResizedEvent(
                    width=int(event.width), height=int(event.height)
                )
            )

        elif isinstance(event, MovedEvent):
            self._emit(WindowEvent.MovedEvent(x=int(event.x), y=int(event.y)))

        elif isinstance(event, FocusedEvent):
            self._emit(WindowEvent.FocusedEvent())

        elif isinstance(event, UnfocusedEvent):
            self._emit(WindowEvent.UnfocusedEvent())

        elif isinstance(event, ScaleFactorChangedEvent):
            self._emit(
                WindowEvent.ScaleFactorChangedEvent(scale_factor=event.scale_factor)
            )

        elif isinstance(event, ThemeChangedEvent):
            self._emit(WindowEvent.ThemeChangedEvent(theme=event.theme))

        elif isinstance(event, StartedEvent):
            self._emit(WindowEvent.StartedEvent())

        elif isinstance(event, SuspendedEvent):
            self._emit(WindowEvent.SuspendedEvent())

        elif isinstance(event, ResumedEvent):
            self._emit(WindowEvent.ResumedEvent())

        elif isinstance(event, StoppedEvent):
            self._emit(WindowEvent.StoppedEvent())

        elif isinstance(event, DecorationsClickEvent):
            self._emit(WindowEvent.DecorationsClickEvent())

        elif isinstance(event, ReceivedImeTextEvent):
            self._emit(WindowEvent.ReceivedImeTextEvent(text=event.text))

        elif isinstance(event, TouchpadPressureEvent):
            self._emit(
                WindowEvent.TouchpadPressureEvent(
                    pressure=event.pressure, stage=event.stage
                )
            )

        elif isinstance(event, AxisMotionEvent):
            self._emit(WindowEvent.AxisMotionEvent(axis=event.axis, value=event.value))

        elif isinstance(event, TouchEvent):
            self._emit(
                WindowEvent.TouchEvent(
                    phase=event.phase,
                    x=event.x,
                    y=event.y,
                    force=event.force,
                    id=event.id,
                )
            )

        elif isinstance(event, RedrawRequestedEvent):
            if self._window is not None:
                self._window._redraw_transparent_surface()

        elif isinstance(event, CloseRequestedEvent):
            self._request_close_now()

        elif isinstance(event, DestroyedEvent):
            # Safety net: if the OS destroys the window independently
            # (e.g. user kills the process, or platform-specific behavior),
            # ensure we clean up tracking and WebView resources.
            if self._webview is not None:
                try:
                    self._webview.close()
                except Exception:
                    pass
            self._window = None
            self._webview = None
            self._app._remove_window(self._win_id)

    @main_thread
    def request_close(self) -> None:
        """
        Request this window to close.

        Dispatches the preventable
        :class:`~lumiview.events.WindowEvent.CloseRequestedEvent`
        asynchronously — the returned task completes once the request is
        dispatched, *not* once the window is actually closed. The
        configured ``close_behavior`` is applied after handlers finish:
        a handler may call
        :meth:`~lumiview.events.WindowBaseEvent.prevent` to cancel the
        close.
        """
        self._request_close_now()

    def _request_close_now(self) -> None:
        """
        Apply ``close_behavior`` without blocking the GUI thread.
        """
        if self._close_pending or self._window is None:
            return
        self._close_pending = True
        event = WindowEvent.CloseRequestedEvent()
        done = self._emit(event)
        if done is None:
            # No handlers — apply close behavior right now (we are on the
            # main thread; @main_thread calls run inline here).
            self._on_close_handlers_done(event)
        else:
            done.add_done_callback(lambda _: self._on_close_handlers_done(event))

    def _on_close_handlers_done(self, event: WindowBaseEvent) -> None:
        """
        Handler-completion callback (asyncio thread) — apply close behavior.

        ``_close_pending`` is cleared on every path that keeps the window
        alive (prevented / Ignore / Hide); the Close path keeps it set,
        leaving ``self._window is None`` as the guard for any later
        request.
        """
        if event.prevented:
            self._close_pending = False
            return

        behavior = self._close_behavior
        if behavior == CloseBehavior.Ignore:
            self._close_pending = False
        elif behavior == CloseBehavior.Hide:

            def _hide() -> None:
                if self._window is not None:
                    self._window.set_visible(False)
                self._close_pending = False

            self._app.call_on_main(_hide)
        else:
            self.close()

    @main_thread
    def close(self) -> None:
        """
        Close the window and destroy its resources.
        """
        if self._webview is not None:
            self._webview.close()
        self._window = None
        self._webview = None
        self._app._remove_window(self._win_id)

    # WebView capabilities (§11)

    @main_thread
    def open_devtools(self) -> None:
        """Open the developer tools window."""
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.open_devtools()

    @main_thread
    def close_devtools(self) -> None:
        """Close the developer tools window."""
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.close_devtools()

    @main_thread
    def is_devtools_open(self) -> bool:
        """True if the developer tools window is open."""
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        return self._webview.is_devtools_open()

    @main_thread
    def zoom(self, scale: float) -> None:
        """
        Set the page zoom level. 1.0 = 100%, 1.5 = 150%.
        """
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.zoom(scale)

    @main_thread
    def print(self) -> None:
        """
        Open the system print dialog for the current page.
        """
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.print()

    @main_thread
    def set_background_color(self, r: int, g: int, b: int, a: int = 255) -> None:
        """
        Set the WebView background colour before content loads.
        """
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.set_background_color(r, g, b, a)

    @main_thread
    def cookies(self) -> list[dict]:
        """
        Return all cookies as dicts with name, value, domain, path, etc.
        """
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        raw = self._webview.cookies()
        return [
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
                "http_only": c.http_only,
            }
            for c in raw
        ]

    @main_thread
    def cookies_for_url(self, url: str) -> list[dict]:
        """
        Return cookies applicable to *url*.
        """
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        raw = self._webview.cookies_for_url(url)
        return [
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
                "http_only": c.http_only,
            }
            for c in raw
        ]

    @main_thread
    def set_cookie(
        self,
        name: str,
        value: str,
        *,
        domain: str | None = None,
        path: str | None = None,
    ) -> None:
        """
        Set a cookie.
        """
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.set_cookie(name, value, domain, path)

    @main_thread
    def delete_cookie(self, name: str, url: str) -> None:
        """
        Delete a cookie by name for a specific URL.
        """
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.delete_cookie(name, url)

    @main_thread
    def clear_all_browsing_data(self) -> None:
        """
        Clear all browsing data (cache, cookies, storage).
        """
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        self._webview.clear_all_browsing_data()

    # Internal

    @property
    def _id(self) -> int:
        return self._win_id

    # IPC handler

    def _make_ipc_handler(self) -> Callable[[str], None]:
        """
        Create an IPC handler that forwards messages to the Bridge.
        """

        def _handler(raw: str) -> None:
            if self._untrusted:
                self._emit(WindowEvent.WebMessageReceivedEvent(message=raw))
            else:
                try:
                    if self._webview is not None:
                        self._bridge._on_message(self, raw)
                except Exception:
                    log.exception("IPC handler raised an unexpected exception")
                finally:
                    self._emit(WindowEvent.WebMessageReceivedEvent(message=raw))

        return _handler


# Module-level helpers


def _propagate_dispatch_failure(
    handle: Task[Any],
    dispatched: Future[Any],
) -> None:
    """
    Propagate a failed main-thread dispatch into *handle*.

    Without this, a failed ``call_on_main`` would be swallowed and
    *handle* would stay pending forever.
    """
    if handle.done():
        return
    if dispatched.cancelled():
        handle.cancel()
    elif (exc := dispatched.exception()) is not None:
        handle.set_exception(exc)


# Helpers


def _icon_tuple(icon: _IconSource) -> tuple[int, int, bytes]:
    """
    Resolve icon input to ``(width, height, rgba)`` — the argument order
    the native bindings expect.
    """
    rgba, w, h = _load_icon(icon)
    return w, h, rgba


def _load_icon(icon: _IconSource) -> tuple[bytes, int, int]:
    """
    Resolve icon input to ``(rgba_bytes, width, height)``.

    Accepts a ``(bytes, w, h)`` tuple, a file path (requires Pillow),
    or a ``PIL.Image.Image`` object.
    """
    if isinstance(icon, tuple):
        rgba, w, h = icon
        if len(rgba) != w * h * 4:
            raise ValueError(f"Icon data size mismatch: {len(rgba)} != {w}*{h}*4")
        return rgba, w, h

    try:
        from PIL import Image

        if isinstance(icon, Image.Image):
            img = icon.convert("RGBA")

        elif isinstance(icon, str):
            img = Image.open(icon).convert("RGBA")

        else:
            raise TypeError(
                f"icon must be a file path, (bytes, width, height) tuple, "
                f"or PIL.Image.Image, got {type(icon).__name__}"
            )

        return img.tobytes(), img.width, img.height

    except ImportError:
        raise RuntimeError(
            "Pillow is required to load icon from file path or PIL.Image.Image"
        )


def _parse_proxy(proxy: str) -> dict[str, str]:
    """
    Parse a proxy URL into the dict wryview expects.

    Handles ``user:pass@`` credentials (stripped), IPv6 literals
    (``[::1]:8080``), and type-specific default ports.
    """
    proxy_type = "http"
    rest = proxy
    if "://" in proxy:
        proxy_type, rest = proxy.split("://", 1)

    # Strip credentials — wryview's config has no user/password fields.
    host_part = rest.rsplit("@", 1)[-1]

    if host_part.startswith("["):
        # IPv6 literal: [addr] or [addr]:port
        if "]" in host_part:
            host, _, tail = host_part.partition("]")
            host += "]"
            port = tail[1:] if tail.startswith(":") else ""
        else:
            host, port = host_part, ""
    else:
        host, sep, tail = host_part.rpartition(":")
        if sep:
            host, port = host, tail
        else:
            host, port = host_part, ""

    if not port:
        port = "443" if proxy_type == "https" else "80"
    return {"type": proxy_type, "host": host, "port": port}


# Custom protocol handler


def _make_protocol_handler(serve: Serve) -> Callable[..., None]:
    """
    Create a wryview custom protocol handler from a Serve instance.
    """
    from lumiview.serve.base import Request

    def _handler(
        method: str,
        uri: str,
        headers: list[tuple[str, str]],
        body: bytes,
        respond: Callable[[int, list[tuple[str, str]], bytes], None],
    ) -> None:
        parsed = urlparse(uri)
        path = parsed.path or "/"
        query = parsed.query or ""

        request = Request(
            method=method,
            url=uri,
            path=path,
            query=query,
            headers=list(headers),
            body=body,
        )

        try:
            serve(request, respond)
        except Exception:
            log.exception("Serve handler raised an exception")
            respond(500, [("Content-Type", "text/plain")], b"Internal Server Error")

    return _handler
