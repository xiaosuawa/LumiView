from __future__ import annotations

import functools
import logging
import sys
import threading
import time
import webbrowser
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable, ParamSpec, TypeAlias, TypeVar, overload
from urllib.parse import urlparse
from concurrent.futures import Future
from dataclasses import dataclass

from lumiview.app import App, WindowClosedError
from lumiview.scope import InitContext
from lumiview.serve.base import Serve
from lumiview._utils import (
    Subscription,
    _dispatch_event,
    copy_signature_for_classmethod,
    fmt_ms,
    main_thread,
    wait_for_event,
)
from wryview import (
    DragDropEvent,
    PageLoadEvent,
    Theme as WryTheme,
    WebView,
    WebContext as WryWebContext,
    NewWindowResponse,
    WindowHandleKind as WryKind,
)

from lumiview.bridge import Bridge, client_script, dispatch_script
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
from lumiview.events import WindowBaseEvent, WindowEvent, WindowPreventableEvent
from lumiview.task import Task

if TYPE_CHECKING:
    from PIL.Image import Image as _PILImage

_IconSource: TypeAlias = "str | tuple[bytes, int, int] | _PILImage"

P = ParamSpec("P")
R = TypeVar("R")
_E = TypeVar("_E", bound=WindowBaseEvent)
_HandlerEntry = tuple[Callable[..., Any], Callable[[Any], bool] | None]

_log = logging.getLogger("lumiview.window")


def _platform_only(*platforms: str):
    """Raise ``NotImplementedError`` off *platforms*.

    Applied inside ``@main_thread``, so it surfaces as a failed Task.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if sys.platform not in platforms:
                raise NotImplementedError(
                    f"{fn.__name__}() is only available on " + ", ".join(platforms)
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


class CloseBehavior(Enum):
    """What happens when the window receives a close request."""

    Close = auto()
    Hide = auto()
    Ignore = auto()


@dataclass(kw_only=True)
class TitleBarOptions:
    """macOS titlebar appearance options; ignored elsewhere."""

    transparent: bool = False
    """Make the titlebar transparent so content appears behind it."""
    hidden: bool = False
    """Hide the titlebar entirely."""
    title_hidden: bool = False
    """Hide the title text, keeping the titlebar and its buttons."""
    buttons_hidden: bool = False
    """Hide the traffic-light (window control) buttons."""
    fullsize_content_view: bool = False
    """Let the content view extend behind the titlebar (overlay style).
    Combine with ``transparent=True`` for a Tauri-style ``Overlay``
    titlebar."""
    traffic_light_inset: tuple[float, float] | None = None
    """Traffic-light (window controls) inset ``(x, y)`` in logical
    points, relative to the upper-left corner."""
    movable_by_background: bool = False
    """Let the window be dragged from anywhere on its background, not
    just the titlebar."""


class WebContext:
    """A shared WebView context (one browser process / cache / localStorage).

    Unsendable: create it with :meth:`create` on the main thread, then pass it to
    several windows via ``WindowOptions.web_context``.
    """

    _inner: WryWebContext | None
    """The wrapped wryview context — unsendable, main-thread bound."""

    def __init__(self, inner: WryWebContext) -> None:
        self._inner = inner

    @classmethod
    @main_thread
    def create(cls, *, data_directory: str | None = None) -> "WebContext":
        """Create a shared WebContext on the main thread."""
        return cls(WryWebContext(data_directory=data_directory))


@dataclass(kw_only=True)
class WindowOptions:
    """Options for creating a :class:`Window` (mutable)."""

    title: str = "lumiview"
    """Window title shown in the titlebar."""
    url: str | None = None
    """URL to load as the initial page."""
    html: str | None = None
    """HTML string to show instead of a URL."""
    source: Serve | list[Serve] | None = None
    """One or more :class:`~lumiview.serve.Serve` handlers
    registered as ``lumiview://`` custom protocols."""
    width: int = 800
    """Initial inner width in logical pixels."""
    height: int = 600
    """Initial inner height in logical pixels."""
    position: tuple[float, float] | None = None
    """Initial outer position in logical pixels (relative to *monitor*)."""
    monitor: Monitor | None = None
    """Monitor to open on; without *position* the window is centered on it."""
    min_size: tuple[float, float] | None = None
    """Minimum inner size ``(width, height)``."""
    max_size: tuple[float, float] | None = None
    """Maximum inner size ``(width, height)``."""
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
    always_on_bottom: bool = False
    """Whether the window stays below other windows. Mutually
    exclusive with ``always_on_top`` — the last one set wins."""
    titlebar: TitleBarOptions | None = None
    """macOS titlebar appearance — see :class:`TitleBarOptions`.
    Silently ignored on other platforms."""
    undecorated_shadow: bool | None = None
    """Shadow for undecorated windows — ``None`` lets the platform
    decide."""
    icon: _IconSource | None = None
    """Window icon — a file path, ``(rgba_bytes, width, height)``
    tuple, or ``PIL.Image.Image`` object."""
    theme: Theme | None = None
    """Initial page theme (Windows only); ``None`` follows the system."""
    sync_visibility: bool = True
    """Hide/show the WebView together with the window (saves CPU/GPU while hidden)."""
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
    bridge: Bridge | None = None
    """The IPC bridge; ``None`` still injects the client but rejects every command."""
    untrusted: bool = False
    """Skip the JS client and IPC parsing (messages surface as ``WebMessageReceivedEvent``)."""
    web_context: WebContext | None = None
    """Shared WebView context; pass the same instance to share cache and storage."""
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
    """Window and WebView background ``(r, g, b, a)`` — applied to the
    native window (the alpha channel is ignored there on Windows) and
    the WebView."""
    headers: dict[str, str] | None = None
    """Extra HTTP headers for the initial load."""
    devtools: bool = False
    """Whether developer tools are available."""
    prepare: Callable[[Window], Any] | None = None
    """Called with the :class:`Window` shell before the native window
    and WebView are created — the earliest point to register event
    handlers."""

    def __post_init__(self) -> None:
        if self.bridge is not None and self.untrusted:
            raise ValueError("bridge and untrusted are mutually exclusive")


class Window:
    """A window with an embedded WebView.

    Native calls are marshalled to the main thread and return a ``Task``; ``id``,
    ``is_closed`` and ``bridge`` are local reads.
    """

    def __init__(self) -> None:
        self._app: App
        self._win_id: int
        self._window: TaoWindow | None
        """Unsendable, main-thread bound. Never hold on other threads."""
        self._webview: WebView | None
        """Unsendable, main-thread bound. Never hold on other threads."""
        self._bridge: Bridge | None
        """The IPC :class:`~lumiview.bridge.Bridge`, or ``None`` in untrusted
        mode (no IPC is parsed at all). Read it through the :attr:`bridge`
        property: the command tree is fixed for the window's lifetime —
        mutate it in place instead of replacing it."""
        self._handlers: dict[type[WindowBaseEvent], list[_HandlerEntry]]
        self._closed: bool
        self._loaded: Task[WindowBaseEvent]
        self._close_behavior: CloseBehavior
        self._close_pending: bool
        self._drag_enabled: bool
        self._untrusted: bool
        self._sync_visibility: bool
        self._handlers_lock: threading.Lock
        self._close_lock: threading.Lock

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
        """Create a window (main thread) and return it.

        Accepts a :class:`WindowOptions` or keyword arguments. ``options.prepare`` runs
        before the native objects exist, so it can register early events.
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
        self._win_id = 0  # real id assigned after the tao window exists
        self._handlers = {}
        # Registered from any thread, snapshotted during dispatch.
        self._handlers_lock = threading.Lock()
        # Written on the main thread, cleared from the asyncio thread.
        self._close_lock = threading.Lock()

        # `_loaded` is pre-registered here, so `wait_loaded()` cannot race it.
        self._closed = False
        self._loaded = self.wait_for(WindowEvent.PageLoadFinishedEvent)
        self._loaded.on_exception(
            lambda _: None
        )  # suppress unhandled exception logging

        # Fixed command tree: on_init/on_ready run against this exact bridge.
        self._bridge = None if options.untrusted else (options.bridge or Bridge())
        self._untrusted = options.untrusted

        ctx = InitContext(
            inject_script=client_script(),
            window=self,
            options=options,
        )
        if self._bridge is not None:
            ctx = self._bridge._run_on_init(ctx)
        logging.getLogger("lumiview.window").debug(
            "Window.create: inject_script=%d chars", len(ctx.inject_script)
        )

        self._close_behavior = options.close_behavior
        self._close_pending = False
        self._drag_enabled = options.drag_drop
        self._sync_visibility = options.sync_visibility

        # Resolve source → url / html / custom_protocols
        custom_protocols: dict[str, Callable] = {}
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

        if options.icon is not None:
            rgba, iw, ih = _load_icon(options.icon)
            icon_data = (iw, ih, rgba)  # (width, height, rgba) per _core
        else:
            icon_data = None

        # tao has no "open on monitor": place the window at its screen coords.
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

        tb = options.titlebar
        _t0 = time.monotonic()
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
            always_on_bottom=options.always_on_bottom,
            background_color=options.background_color,
            titlebar_transparent=tb.transparent if tb else None,
            titlebar_hidden=tb.hidden if tb else None,
            title_hidden=tb.title_hidden if tb else None,
            titlebar_buttons_hidden=tb.buttons_hidden if tb else None,
            fullsize_content_view=tb.fullsize_content_view if tb else None,
            traffic_light_inset=tb.traffic_light_inset if tb else None,
            movable_by_background=tb.movable_by_background if tb else None,
            focused=options.focused,
            focusable=options.focusable,
            content_protection=options.content_protection,
            visible_on_all_workspaces=options.visible_on_all_workspaces,
            transparent=options.transparent,
            icon=icon_data,
        )
        win_id = tao_win.id()
        _log.debug("tao window created in %.1fms", fmt_ms(_t0))

        try:
            _t1 = time.monotonic()
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
                visible=options.visible if self._sync_visibility else True,
                transparent=options.transparent,
                background_color=options.background_color,
                devtools=options.devtools,
                incognito=options.incognito,
                user_agent=options.user_agent,
                autoplay=options.autoplay,
                javascript_enabled=options.javascript,
                hotkeys_zoom=options.hotkeys_zoom,
                theme=_to_wry_theme(options.theme),
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
                web_context=(
                    options.web_context._inner
                    if options.web_context is not None
                    else None
                ),
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
            _log.debug("webview created in %.1fms", fmt_ms(_t1))
        except Exception:
            del tao_win
            raise

        self._webview = webview
        self._window = tao_win

        self._win_id = win_id
        app._register_window(self)
        _log.info(
            "Window created (id=%s) in %.1fms",
            win_id,
            fmt_ms(_t0),
        )

        try:
            if options.transparent:
                # Wry creates its child HWND after Tao's surface — refresh once more.
                tao_win._redraw_transparent_surface()

            if self._bridge is not None:
                self._bridge._run_on_ready(self)
        except Exception:
            self._teardown_failed_create()
            del tao_win
            raise

        return self

    @property
    def bridge(self) -> Bridge | None:
        """The IPC bridge, or ``None`` in untrusted mode (fixed for the window's lifetime)."""
        return self._bridge

    def _get_webview(self) -> WebView:
        if self._webview is None:
            raise WindowClosedError(self._win_id)
        return self._webview

    def _get_window(self) -> TaoWindow:
        if self._window is None:
            raise WindowClosedError(self._win_id)
        return self._window

    @main_thread
    def load_url(self, url: str) -> None:
        """Navigate the WebView to *url*."""
        self._get_webview().load_url(url)

    @main_thread
    def load_html(self, html: str) -> None:
        """Render *html* as the current page."""
        self._get_webview().load_html(html)

    @main_thread
    def reload(self) -> None:
        """Reload the current page."""
        self._get_webview().reload()

    def eval_js(self, script: str) -> Task[str]:
        """Evaluate JavaScript in the page and return its value as a string.

        The script runs on the GUI thread and the task settles when the page
        answers. Fails with ``WindowClosedError`` if the window closes first —
        the native callback never fires once the WebView is gone.
        """
        return self._eval_script(script)

    def _eval_script(self, script: str, *, discard: bool = False) -> Task[Any]:
        """Evaluate *script* on the GUI thread and settle the result into a Task.

        The ``ClosedEvent`` subscription is the fallback for a page that can no
        longer answer; it is dropped as soon as the handle settles.
        """
        handle: Task[Any] = Task()
        if self._closed:
            handle._settle(exc=WindowClosedError(self._win_id))
            return handle

        sub = self.on(
            WindowEvent.ClosedEvent,
            lambda _: handle._settle(exc=WindowClosedError(self._win_id)),
        )
        handle.add_done_callback(lambda _: sub.cancel())

        def _do() -> None:
            try:
                webview = self._get_webview()
            except WindowClosedError as exc:
                handle._settle(exc=exc)
                return
            webview.eval_js_with_callback(
                script,
                lambda result: handle._settle(result=None if discard else result),
            )

        App.get().call_on_main(_do).add_done_callback(
            lambda dispatched: _propagate_dispatch_failure(handle, dispatched)
        )
        return handle

    @main_thread
    def set_icon(self, icon: _IconSource) -> None:
        """Set the window icon.

        *icon* is a path (needs Pillow), ``(rgba_bytes, width, height)`` or a PIL image.
        """
        rgba, w, h = _load_icon(icon)
        self._get_window().set_window_icon(w, h, rgba)

    @main_thread
    def apply_effect(
        self,
        effect: WindowEffect,
        color: tuple[int, int, int, int] | None = None,
        material: VibrancyMaterial | None = None,
    ) -> None:
        """Apply a native background material.

        ``material`` picks the macOS vibrancy variant for ``WindowEffect.Vibrancy``;
        unsupported platforms or OS versions raise ``NotImplementedError``.
        """
        self._get_window().apply_effect(effect, color, material)

    @main_thread
    def clear_effect(self, effect: WindowEffect) -> None:
        """
        Clear a native material previously applied to this window.
        """
        self._get_window().clear_effect(effect)

    @main_thread
    def set_bounds(self, x: float, y: float, w: float, h: float) -> None:
        """Resize and position the WebView inside the window."""
        self._get_webview().set_bounds(x, y, w, h)

    @main_thread
    def set_inner_size(self, width: float, height: float) -> None:
        """Set the window's inner size in logical pixels.

        Named after :meth:`inner_size` / :meth:`set_min_inner_size` — the
        old ``set_size()`` was the odd one out.
        """
        self._get_window().set_inner_size(width, height)

    @main_thread
    def set_visible(self, flag: bool) -> None:
        """Show (``True``) or hide (``False``) the window, re-syncing the
        WebView to match (a no-op when ``sync_visibility`` is ``False``)."""
        self._set_visible_impl(flag)

    def _set_visible_impl(self, flag: bool) -> None:
        """Apply the visibility and re-sync the WebView (main thread only)."""
        self._get_window().set_visible(flag)
        self._sync_webview_visibility_impl()

    @main_thread
    def set_webview_visible(self, flag: bool) -> None:
        """Show (``True``) or hide (``False``) the WebView independently of
        the window. The next window visibility change re-syncs it as long
        as ``sync_visibility`` is ``True``."""
        self._set_webview_visible_impl(flag)

    def _set_webview_visible_impl(self, flag: bool) -> None:
        """Apply the WebView visibility (main thread only)."""
        self._get_webview().set_visible(flag)

    @main_thread
    def show(self) -> None:
        """Show the window (and un-minimize it if needed)."""
        self._show_impl()

    def _show_impl(self) -> None:
        """Show + un-minimize + re-sync (main thread only)."""
        self._set_visible_impl(True)
        self._set_minimized_impl(False)

    @main_thread
    def hide(self) -> None:
        """Hide the window."""
        self._hide_impl()

    def _hide_impl(self) -> None:
        """Hide the window (main thread only)."""
        self._set_visible_impl(False)

    def _sync_webview_visibility_impl(self) -> None:
        """Sync the WebView's visibility to match the window's (main thread only).

        When ``sync_visibility`` is ``False``, this is a no-op.
        """
        if not self._sync_visibility:
            return
        visible = (
            self._get_window().is_visible() and not self._get_window().is_minimized()
        )
        self._set_webview_visible_impl(visible)

    @main_thread
    def focus(self) -> None:
        """Give the window keyboard focus (there is no unfocus)."""
        self._get_window().set_focused(True)

    def _set_minimized_impl(self, flag: bool) -> None:
        """Apply the minimize state and re-sync the WebView.

        Shared by :meth:`show` and :meth:`set_minimized` so the two cannot
        drift apart. Main-thread only — callers are ``@main_thread`` methods.
        """
        self._get_window().set_minimized(flag)
        self._sync_webview_visibility_impl()

    @main_thread
    def set_maximized(self, flag: bool = True) -> None:
        """Maximize (``True``) or restore the window (``flag`` = maximize)."""
        self._set_maximized_impl(flag)

    def _set_maximized_impl(self, flag: bool) -> None:
        """Apply the maximize state (main thread only)."""
        self._get_window().set_maximized(flag)

    @main_thread
    def toggle_maximize(self) -> bool:
        """Toggle maximize state.

        Returns:
            True if the window is now maximized.
        """
        maximized = not self._get_window().is_maximized()
        self._set_maximized_impl(maximized)
        return maximized

    @main_thread
    def set_fullscreen(self, fullscreen: bool) -> None:
        """
        Enter or exit fullscreen.
        """
        self._get_window().set_fullscreen(fullscreen)

    @main_thread
    def is_maximized(self) -> bool:
        """True if the window is maximized."""
        return self._get_window().is_maximized()

    @main_thread
    def start_dragging(self) -> None:
        """Start an OS-level window drag (for custom titlebars)."""
        self._get_window().drag_window()

    @main_thread
    def start_resize_dragging(self, direction: ResizeDirection) -> None:
        """Start an OS-level resize drag from *direction* (for custom
        titlebars)."""
        self._get_window().drag_resize_window(direction)

    @main_thread
    def set_title(self, title: str) -> None:
        """Set the window title."""
        self._get_window().set_title(title)

    @main_thread
    def title(self) -> str:
        """Return the current window title."""
        return self._get_window().title()

    @main_thread
    def theme(self) -> Theme:
        """Return the window's effective color theme."""
        return self._get_window().theme()

    @main_thread
    def set_theme(self, theme: Theme | None = None) -> None:
        """Force the window chrome and page theme (``None`` restores the system).

        The WebView theme is Windows-only; macOS/Linux follow the system.
        """
        self._get_window().set_theme(theme)
        if self._webview is not None:
            try:
                self._webview.set_theme(_to_wry_theme(theme))
            except NotImplementedError:
                _log.debug("WebView theme is Windows-only — window theme still applied")

    @main_thread
    def inner_size(self) -> tuple[float, float]:
        """Return the inner size ``(width, height)`` in logical pixels."""
        return self._get_window().inner_size()

    @main_thread
    def inner_position(self) -> tuple[float, float]:
        """Return the client area position ``(x, y)`` in logical pixels."""
        return self._get_window().inner_position()

    @main_thread
    def outer_position(self) -> tuple[float, float]:
        """Return the window position ``(x, y)`` in logical pixels."""
        return self._get_window().outer_position()

    @main_thread
    def cursor_position(self) -> tuple[float, float]:
        """Return the cursor position inside the window in logical pixels."""
        return self._get_window().cursor_position()

    @main_thread
    def outer_size(self) -> tuple[int, int]:
        """Return the outer size ``(width, height)`` in logical pixels."""
        return self._get_window().outer_size()

    @main_thread
    def scale_factor(self) -> float:
        """Return the window's DPI scale factor."""
        return self._get_window().scale_factor()

    @main_thread
    def set_outer_position(self, x: float, y: float) -> None:
        """Move the window so its top-left corner is at ``(x, y)``."""
        self._get_window().set_outer_position(x, y)

    @main_thread
    def set_min_inner_size(self, width: float, height: float) -> None:
        """Set the minimum inner size in logical pixels."""
        self._get_window().set_min_inner_size(width, height)

    @main_thread
    def set_max_inner_size(self, width: float, height: float) -> None:
        """Set the maximum inner size in logical pixels."""
        self._get_window().set_max_inner_size(width, height)

    @main_thread
    def set_resizable(self, flag: bool) -> None:
        """Allow or disallow resizing the window."""
        self._get_window().set_resizable(flag)

    @main_thread
    def set_focusable(self, flag: bool) -> None:
        """Allow or disallow the window receiving focus."""
        self._get_window().set_focusable(flag)

    @main_thread
    def set_content_protection(self, flag: bool) -> None:
        """Hide window content from screenshots (Windows)."""
        self._get_window().set_content_protection(flag)

    @main_thread
    def set_visible_on_all_workspaces(self, flag: bool) -> None:
        """Show the window on all workspaces (Linux)."""
        self._get_window().set_visible_on_all_workspaces(flag)

    @main_thread
    def set_always_on_bottom(self, flag: bool) -> None:
        """Pin the window below other windows."""
        self._get_window().set_always_on_bottom(flag)

    @main_thread
    def is_focused(self) -> bool:
        """True if the window currently has keyboard focus."""
        return self._get_window().is_focused()

    @main_thread
    def is_resizable(self) -> bool:
        """True if the window can be resized by the user."""
        return self._get_window().is_resizable()

    @main_thread
    def is_decorated(self) -> bool:
        """True if the window has a native titlebar and frame."""
        return self._get_window().is_decorated()

    @main_thread
    def is_closable(self) -> bool:
        """True if the window can be closed by the user."""
        return self._get_window().is_closable()

    @main_thread
    def is_minimizable(self) -> bool:
        """True if the window can be minimized by the user."""
        return self._get_window().is_minimizable()

    @main_thread
    def is_maximizable(self) -> bool:
        """True if the window can be maximized by the user."""
        return self._get_window().is_maximizable()

    @main_thread
    def is_always_on_top(self) -> bool:
        """True if the window floats above other windows."""
        return self._get_window().is_always_on_top()

    @main_thread
    def is_fullscreen(self) -> bool:
        """True if the window is currently fullscreen."""
        return self._get_window().is_fullscreen()

    @main_thread
    def set_minimizable(self, flag: bool) -> None:
        """Allow or disallow minimizing the window."""
        self._get_window().set_minimizable(flag)

    @main_thread
    def set_maximizable(self, flag: bool) -> None:
        """Allow or disallow maximizing the window."""
        self._get_window().set_maximizable(flag)

    @main_thread
    def set_closable(self, flag: bool) -> None:
        """Allow or disallow closing the window."""
        self._get_window().set_closable(flag)

    @main_thread
    def set_always_on_top(self, flag: bool) -> None:
        """Float the window above (or below) other windows."""
        self._get_window().set_always_on_top(flag)

    @main_thread
    def set_decorations(self, flag: bool) -> None:
        """Show or hide the native titlebar and window frame."""
        self._get_window().set_decorations(flag)

    @main_thread
    def set_cursor_visible(self, flag: bool) -> None:
        """Show or hide the cursor over the window."""
        self._get_window().set_cursor_visible(flag)

    @main_thread
    def set_cursor_icon(self, icon: CursorIcon) -> None:
        """Set the cursor shape shown while hovering the window."""
        self._get_window().set_cursor_icon(icon)

    @main_thread
    def set_cursor_grab(self, grab: bool) -> None:
        """Lock (``True``) or release (``False``) the cursor to the
        window. Useful for games or drawing apps."""
        self._get_window().set_cursor_grab(grab)

    @main_thread
    def set_ignore_cursor_events(self, ignore: bool) -> None:
        """Make the window transparent to mouse events (``True`` =
        clicks pass through)."""
        self._get_window().set_ignore_cursor_events(ignore)

    @main_thread
    def set_cursor_position(self, x: float, y: float) -> None:
        """Move the cursor to a logical position inside the window."""
        self._get_window().set_cursor_position(x, y)

    @main_thread
    def request_user_attention(self, request_type: AttentionType | None = None) -> None:
        """Ask the OS to draw attention to this window (``None`` clears it)."""
        self._get_window().request_user_attention(request_type)

    @main_thread
    def set_ime_position(self, x: float, y: float) -> None:
        """Place the input method editor (candidate window) at a
        logical position inside the window."""
        self._get_window().set_ime_position(x, y)

    @main_thread
    def set_progress_bar(
        self,
        state: ProgressState | None = None,
        progress: float | None = None,
    ) -> None:
        """Set the Windows taskbar progress bar.

        ``state=None`` removes it; *progress* is 0.0–100.0.
        """
        self._get_window().set_progress_bar(state, progress)

    @main_thread
    def set_minimized(self, flag: bool) -> None:
        """Minimize or restore the window."""
        self._set_minimized_impl(flag)

    @main_thread
    def is_minimized(self) -> bool:
        """True if the window is minimized."""
        return self._get_window().is_minimized()

    @main_thread
    def is_visible(self) -> bool:
        """True if the window is visible."""
        return self._get_window().is_visible()

    @main_thread
    def toggle_visibility(self) -> None:
        """Toggle the window between shown and hidden."""
        win = self._get_window()
        if win.is_visible() and not win.is_minimized():
            self._set_visible_impl(False)
        else:
            self._set_visible_impl(True)
            # _set_minimized_impl() re-syncs after un-minimizing.
            self._set_minimized_impl(False)

    @main_thread
    def request_redraw(self) -> None:
        """Ask the OS to repaint the window.

        The WebView paints itself; this only repaints the window's own surface,
        which matters for the retained transparent surface of a transparent /
        vibrancy window (Windows).
        """
        self._get_window().request_redraw()

    @main_thread
    def native_handle(self) -> int:
        """Return the raw OS window handle (HWND / NSView / X11 window).

        See :meth:`native_handle_kind` for the handle type.
        """
        return self._get_window().native_handle()

    @main_thread
    def native_handle_kind(self) -> WindowHandleKind:
        """
        Return the OS handle type (Win32 / AppKit / X11 / Wayland / Gtk).
        """
        return self._get_window().native_handle_kind()

    @main_thread
    @_platform_only("linux")
    def gtk_container(self) -> int:
        """Return the raw GTK container widget pointer (Linux only).

        Raises :class:`NotImplementedError` on other platforms.
        """
        return self._get_window().gtk_container()

    @main_thread
    def current_monitor(self) -> Monitor | None:
        """Return the :class:`~lumiview._core.Monitor` the window is
        currently on, or ``None``."""
        return self._get_window().current_monitor()

    @main_thread
    def available_monitors(self) -> list[Monitor]:
        """Return all monitors currently connected."""
        return self._get_window().available_monitors()

    @main_thread
    def primary_monitor(self) -> Monitor | None:
        """Return the primary monitor, or ``None``."""
        return self._get_window().primary_monitor()

    @main_thread
    def monitor_from_point(self, x: float, y: float) -> Monitor | None:
        """Return the monitor containing the given physical screen point."""
        return self._get_window().monitor_from_point(x, y)

    @main_thread
    def set_borderless_fullscreen(self, monitor: Monitor | None = None) -> None:
        """Enter borderless fullscreen on *monitor* (``None`` = the
        current monitor)."""
        self._get_window().set_borderless_fullscreen(monitor)

    @main_thread
    def set_exclusive_fullscreen(self, mode: VideoMode) -> None:
        """Enter exclusive fullscreen at *mode*'s resolution and
        refresh rate (see :meth:`~lumiview._core.Monitor.video_modes`)."""
        self._get_window().set_exclusive_fullscreen(mode)

    # Platform extensions

    # Windows

    @main_thread
    @_platform_only("win32", "linux")
    def set_skip_taskbar(self, skip: bool) -> None:
        """Hide or show the window in the taskbar.

        **Windows / Linux (X11).** Wayland has no taskbar concept, so the
        hint is a no-op there.
        """
        self._get_window().set_skip_taskbar(skip)

    @main_thread
    @_platform_only("win32")
    def set_taskbar_icon(self, icon: _IconSource | None = None) -> None:
        """Replace the taskbar icon (``None`` restores the window icon).
        **Windows only.**"""
        data = None if icon is None else _icon_tuple(icon)
        self._get_window().set_taskbar_icon(data)

    @main_thread
    @_platform_only("win32")
    def set_overlay_icon(self, icon: _IconSource | None = None) -> None:
        """Set an overlay badge on the taskbar icon (``None`` removes
        it). **Windows only.**"""
        data = None if icon is None else _icon_tuple(icon)
        self._get_window().set_overlay_icon(data)

    @main_thread
    @_platform_only("win32")
    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the window (disabled windows ignore mouse
        input). **Windows only.**"""
        self._get_window().set_enable(enabled)

    @main_thread
    @_platform_only("win32")
    def set_rtl(self, rtl: bool) -> None:
        """Right-to-left layout for the window. **Windows only.**"""
        self._get_window().set_rtl(rtl)

    @main_thread
    @_platform_only("win32")
    def reset_dead_keys(self) -> None:
        """Reset the OS dead-key state. **Windows only.**"""
        self._get_window().reset_dead_keys()

    @main_thread
    @_platform_only("win32")
    def set_undecorated_shadow(self, shadow: bool) -> None:
        """Toggle the shadow of an undecorated window at runtime.
        **Windows only.**"""
        self._get_window().set_undecorated_shadow(shadow)

    @main_thread
    @_platform_only("win32")
    def has_undecorated_shadow(self) -> bool:
        """Whether the undecorated window shadow is enabled.
        **Windows only.**"""
        return self._get_window().has_undecorated_shadow()

    # macOS

    @main_thread
    @_platform_only("darwin")
    def set_badge_label(self, label: str | None) -> None:
        """Set the text in the macOS Dock badge (``None`` clears it).
        **macOS only.**"""
        self._get_window().set_badge_label(label)

    @main_thread
    @_platform_only("darwin")
    def set_simple_fullscreen(self, fullscreen: bool) -> bool:
        """Toggle "simple fullscreen" (content covers the whole screen,
        including the menu bar). Returns the resulting state.
        **macOS only.**"""
        return self._get_window().set_simple_fullscreen(fullscreen)

    @main_thread
    @_platform_only("darwin")
    def set_titlebar_transparent(self, transparent: bool) -> None:
        """Make the native titlebar transparent (custom chrome overlays
        the titlebar area). **macOS only.**"""
        self._get_window().set_titlebar_transparent(transparent)

    @main_thread
    @_platform_only("darwin")
    def set_traffic_light_inset(self, x: float, y: float) -> None:
        """Set the traffic-light (window controls) inset in logical
        points. **macOS only.**"""
        self._get_window().set_traffic_light_inset(x, y)

    @main_thread
    @_platform_only("darwin")
    def set_fullsize_content_view(self, fullsize: bool) -> None:
        """Let the content view extend behind the titlebar
        (``NSFullSizeContentViewWindowMask``). **macOS only.**"""
        self._get_window().set_fullsize_content_view(fullsize)

    @main_thread
    @_platform_only("darwin")
    def set_has_shadow(self, has_shadow: bool) -> None:
        """Toggle the window shadow. **macOS only.**"""
        self._get_window().set_has_shadow(has_shadow)

    @main_thread
    @_platform_only("darwin")
    def has_shadow(self) -> bool:
        """Whether the window currently has a shadow. **macOS only.**"""
        return self._get_window().has_shadow()

    # Linux (GTK)

    @main_thread
    @_platform_only("linux")
    def set_badge_count(self, count: int | None) -> None:
        """Set the number shown in the GTK badge (``None`` clears it).
        **Linux only.**"""
        self._get_window().set_badge_count(count)

    def emit(self, event: str, payload: Any = None) -> Task[None]:
        """Send an event to the page (``__LUMIVIEW__.listen``).

        The task resolves when the script reaches the WebView, and fails with
        ``WindowClosedError`` if the window closes first. Fails in untrusted mode.
        """
        if self._untrusted:
            return Task._failed(
                RuntimeError(
                    "emit() is not available in untrusted mode — "
                    "use WindowOptions.untrusted=False to enable it"
                )
            )

        return self._eval_script(
            dispatch_script(
                {"type": "event", "event": event, "payload": payload},
                default=str,
            ),
            discard=True,
        )

    # Events

    def on(
        self,
        event: type[_E],
        handler: Callable[[_E], Any] | None = None,
        *,
        where: Callable[[_E], bool] | None = None,
    ) -> Subscription[_E]:
        """Register a handler for an event class (sync or async).

        Pass *handler* to register it right away, or call the returned
        cancellable :class:`~lumiview.Subscription` (the decorator form).
        ``where`` is a synchronous filter.
        """
        if event is WindowEvent.DragEvent and not self._drag_enabled:
            raise RuntimeError(
                "WindowEvent.DragEvent requires WindowOptions(drag_drop=True) — "
                "registering a custom drag-drop handler at creation disables "
                "WebView2's built-in external-file drops, so it cannot be "
                "enabled lazily after the WebView exists."
            )

        sub = Subscription(self._handlers, event, where, self._handlers_lock)
        if handler is not None:
            sub(handler)
        return sub

    def _emit(self, event: WindowBaseEvent) -> Task[None] | None:
        """Dispatch *event* to its handlers (sets ``event.window``).

        Returns a completion ``Task`` or ``None``.
        """
        event.window = self

        # Snapshot under the lock (waiters mutate the list mid-dispatch).
        with self._handlers_lock:
            entries = list(self._handlers.get(type(event), ()))

        return _dispatch_event(self._app, entries, event)

    # Waiting

    def wait_for(
        self,
        event: type[_E],
        *,
        where: Callable[[_E], bool] | None = None,
        timeout: float | None = None,
    ) -> Task[_E]:
        """Wait for the next event of *event* matching *where* (one-shot).

        Fails with ``WindowClosedError`` if the window closes first, and with
        ``TimeoutError`` after *timeout*. Register it before the event can fire.
        """
        return wait_for_event(
            self._handlers,
            event,
            where=where,
            timeout=timeout,
            lock=self._handlers_lock,
            close_event=WindowEvent.ClosedEvent,
            is_closed=lambda: self._closed,
            closed_error=lambda: WindowClosedError(self._win_id),
        )

    def wait_loaded(self, *, timeout: float | None = None) -> Task[WindowBaseEvent]:
        """Wait for the initial page load to finish (pre-registered, so no race).

        A timeout only bounds this caller's view of the shared latch.
        """
        if timeout is None:
            return self._loaded
        return self._loaded.with_timeout(
            timeout,
            message=f"wait_loaded() timed out after {timeout}s",
        )

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
        _log.debug(
            "navigation to %s -> %s",
            url,
            "blocked" if event.prevented else "allowed",
        )
        return not event.prevented

    def _dispatch_new_window(self, url: str) -> NewWindowResponse:
        """wryview ``on_new_window`` callback — wry has no redirect (Allow/Deny only).

        Default: deny the in-webview window and open the URL externally.
        ``prevent()`` blocks it entirely; ``open_in()`` overrides the target.
        """
        event = WindowEvent.NewWindowRequestedEvent(url=url)
        done = self._emit(event)
        if done is not None:
            done.result()
        open_url = event._open_url
        if open_url is not None:
            _log.debug("new-window %s -> open external (%s)", url, open_url)
            try:
                webbrowser.open(open_url)
            except Exception:
                _log.warning("failed to open url: %s", open_url, exc_info=True)
        elif not event.prevented:
            _log.debug("new-window %s -> open external", url)
            try:
                webbrowser.open(url)
            except Exception:
                _log.warning("failed to open url: %s", url, exc_info=True)
        else:
            _log.debug("new-window %s -> deny (prevented)", url)
        return NewWindowResponse.Deny

    def _dispatch_download_started(self, url: str, suggested_path: str) -> bool | str:
        """wryview ``on_download_started`` callback — block, redirect or allow."""
        event = WindowEvent.DownloadStartedEvent(url=url, suggested_path=suggested_path)
        done = self._emit(event)
        if done is not None:
            done.result()
        save_path = event._save_path
        if save_path is not None:
            _log.debug("download %s -> redirect to %s", url, save_path)
            return save_path
        if event.prevented:
            _log.debug("download %s -> blocked", url)
            return False
        _log.debug("download %s -> allowed", url)
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
        match event:
            case ResizedEvent(width=width, height=height):
                if self._webview is not None and self._window is not None:
                    sf = self._window.scale_factor()
                    self._webview.set_bounds(0, 0, width / sf, height / sf)
                    # Resize the child HWND before replacing the parent backing surface.
                    self._window._redraw_transparent_surface()
                self._emit(
                    WindowEvent.ResizedEvent(width=int(width), height=int(height))
                )

            case MovedEvent(x=x, y=y):
                self._emit(WindowEvent.MovedEvent(x=int(x), y=int(y)))

            case FocusedEvent():
                self._emit(WindowEvent.FocusedEvent())
                # OS restores (e.g. taskbar) bypass show()/toggle — re-derive here.
                self._sync_webview_visibility_impl()

            case UnfocusedEvent():
                self._emit(WindowEvent.UnfocusedEvent())
                self._sync_webview_visibility_impl()

            case ScaleFactorChangedEvent(scale_factor=scale_factor):
                self._emit(
                    WindowEvent.ScaleFactorChangedEvent(scale_factor=scale_factor)
                )

            case ThemeChangedEvent(theme=theme):
                self._emit(WindowEvent.ThemeChangedEvent(theme=theme))

            case StartedEvent():
                self._emit(WindowEvent.StartedEvent())

            case SuspendedEvent():
                self._emit(WindowEvent.SuspendedEvent())

            case ResumedEvent():
                self._emit(WindowEvent.ResumedEvent())

            case StoppedEvent():
                self._emit(WindowEvent.StoppedEvent())

            case DecorationsClickEvent():
                self._emit(WindowEvent.DecorationsClickEvent())

            case ReceivedImeTextEvent(text=text):
                self._emit(WindowEvent.ReceivedImeTextEvent(text=text))

            case TouchpadPressureEvent(pressure=pressure, stage=stage):
                self._emit(
                    WindowEvent.TouchpadPressureEvent(pressure=pressure, stage=stage)
                )

            case AxisMotionEvent(axis=axis, value=value):
                self._emit(WindowEvent.AxisMotionEvent(axis=axis, value=value))

            case TouchEvent(phase=phase, x=x, y=y, force=force, id=touch_id):
                self._emit(
                    WindowEvent.TouchEvent(
                        phase=phase,
                        x=x,
                        y=y,
                        force=force,
                        id=touch_id,
                    )
                )

            case RedrawRequestedEvent():
                if self._window is not None:
                    self._window._redraw_transparent_surface()

            case CloseRequestedEvent():
                self._request_close_now()

            case DestroyedEvent():
                # Safety net: the OS destroyed the window independently.
                if self._webview is not None:
                    try:
                        self._webview.close()
                    except Exception:
                        pass
                self._window = None
                self._webview = None
                self._fail_closed()
                self._app._remove_window(self._win_id)

            case _:
                pass

    @main_thread
    def request_close(self) -> None:
        """Request a close; dispatches the preventable ``CloseRequestedEvent``.

        The returned task completes when the request is dispatched, not when the window
        closes.
        """
        self._request_close_now()

    def _request_close_now(self) -> None:
        """
        Apply ``close_behavior`` without blocking the GUI thread.
        """
        with self._close_lock:
            if self._close_pending or self._window is None:
                return
            self._close_pending = True
        event = WindowEvent.CloseRequestedEvent()
        done = self._emit(event)
        if done is None:
            # No handlers: apply the behavior now (main thread, inline calls).
            self._on_close_handlers_done(event)
        else:
            done.add_done_callback(lambda _: self._on_close_handlers_done(event))

    def _on_close_handlers_done(self, event: WindowPreventableEvent) -> None:
        """Handler-completion callback (asyncio thread) — apply ``close_behavior``."""
        with self._close_lock:
            self._close_pending = False

        if event.prevented:
            _log.debug("window close prevented (id=%s)", self._win_id)
            return

        behavior = self._close_behavior
        _log.debug(
            "window close proceeding (id=%s), behavior=%s",
            self._win_id,
            behavior,
        )

        if behavior == CloseBehavior.Hide:
            handle = self.hide()
        elif behavior == CloseBehavior.Close:
            handle = self.close()
        else:
            return

        # The Task is dropped otherwise — observe it or the failure vanishes.
        handle.on_exception(
            lambda exc: _log.error(
                "window close failed (id=%s)", self._win_id, exc_info=exc
            )
        )

    def _fail_closed(self) -> Task[None] | None:
        """Emit ``WindowEvent.ClosedEvent`` once; returns the dispatch or ``None``."""

        if self._closed:
            return None
        self._closed = True
        return self._emit(WindowEvent.ClosedEvent())

    def _release_native(self) -> None:
        """Close the WebView and drop the native window (main thread only).

        ``ClosedEvent`` is emitted separately by :meth:`_fail_closed`.
        """
        if self._webview is not None:
            try:
                self._webview.close()
            except Exception:
                _log.exception("Error closing WebView")
        self._window = None
        self._webview = None

    def _require_hwnd(self) -> int:
        """Native handle for internal main-thread callers (``@main_thread`` returns a Task)."""
        return self._get_window().native_handle()

    def _teardown_failed_create(self) -> None:
        """Roll back a window whose creation failed (main thread only).

        Unlike :meth:`close`, this does not apply the last-window exit policy.
        """
        self._release_native()
        self._fail_closed()
        self._app._unregister_window(self._win_id)

    @main_thread
    def close(self) -> None:
        """
        Close the window and destroy its resources.
        """
        self._release_native()
        self._fail_closed()
        self._app._remove_window(self._win_id)

    @main_thread
    def open_devtools(self) -> None:
        """Open the developer tools window."""
        self._get_webview().open_devtools()

    @main_thread
    def close_devtools(self) -> None:
        """Close the developer tools window."""
        self._get_webview().close_devtools()

    @main_thread
    def is_devtools_open(self) -> bool:
        """True if the developer tools window is open."""
        return self._get_webview().is_devtools_open()

    @main_thread
    def zoom(self, scale: float) -> None:
        """
        Set the page zoom level. 1.0 = 100%, 1.5 = 150%.
        """
        self._get_webview().zoom(scale)

    @main_thread
    def print(self) -> None:
        """
        Open the system print dialog for the current page.
        """
        self._get_webview().print()

    @main_thread
    def set_background_color(self, color: tuple[int, int, int, int]) -> None:
        """Set the window and WebView background colour."""
        self._get_window().set_background_color(color)
        self._get_webview().set_background_color(*color)

    @main_thread
    def cookies(self) -> list[dict[str, Any]]:
        """
        Return all cookies as dicts with name, value, domain, path, etc.
        """
        raw = self._get_webview().cookies()
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
    def cookies_for_url(self, url: str) -> list[dict[str, Any]]:
        """
        Return cookies applicable to *url*.
        """
        raw = self._get_webview().cookies_for_url(url)
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
        self._get_webview().set_cookie(name, value, domain, path)

    @main_thread
    def delete_cookie(self, name: str, url: str) -> None:
        """
        Delete a cookie by name for a specific URL.
        """
        self._get_webview().delete_cookie(name, url)

    @main_thread
    def clear_all_browsing_data(self) -> None:
        """
        Clear all browsing data (cache, cookies, storage).
        """
        self._get_webview().clear_all_browsing_data()

    @property
    def id(self) -> int:
        """The native window id (stable for the window's lifetime)."""
        return self._win_id

    @property
    def is_closed(self) -> bool:
        """True once the window is closed (ClosedEvent has been dispatched).

        A plain attribute read — no main-thread round trip.
        """
        return self._closed

    # IPC handler

    def _make_ipc_handler(self) -> Callable[[str], Any]:
        """
        Create an IPC handler that forwards messages to the Bridge.
        """

        def _handler(raw: str) -> None:
            if self._untrusted:
                self._emit(WindowEvent.WebMessageReceivedEvent(message=raw))
            else:
                try:
                    if self._webview is not None and self._bridge is not None:
                        self._bridge._on_message(self, raw)
                except Exception:
                    _log.exception("IPC handler raised an unexpected exception")
                finally:
                    self._emit(WindowEvent.WebMessageReceivedEvent(message=raw))

        return _handler


def _propagate_dispatch_failure(
    handle: Task[Any],
    dispatched: Future[Any],
) -> None:
    """Propagate a failed main-thread dispatch into *handle*."""
    if dispatched.cancelled():
        # ``cancel()`` on an already-settled Task is a no-op.
        handle.cancel()
        return
    exc = dispatched.exception()
    if exc is not None:
        handle._settle(exc=exc)


def _to_wry_theme(theme: Theme | None) -> WryTheme:
    """Map the window theme (``None`` = follow the system) to wryview's
    WebView theme (``Auto`` / ``Dark`` / ``Light``)."""
    if theme is None:
        return WryTheme.Auto
    return WryTheme.Light if theme is Theme.Light else WryTheme.Dark


def _icon_tuple(icon: _IconSource) -> tuple[int, int, bytes]:
    """
    Resolve icon input to ``(width, height, rgba)`` — the argument order
    the native bindings expect.
    """
    rgba, w, h = _load_icon(icon)
    return w, h, rgba


def _load_icon(icon: _IconSource) -> tuple[bytes, int, int]:
    """Resolve icon input to ``(rgba_bytes, width, height)``."""
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
    """Parse a proxy URL into the dict wryview expects."""
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


def _make_protocol_handler(serve: Serve) -> Callable:
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
            _log.exception("Serve handler raised an exception")
            respond(500, [("Content-Type", "text/plain")], b"Internal Server Error")

    return _handler
