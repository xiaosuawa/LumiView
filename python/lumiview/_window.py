from __future__ import annotations

import asyncio
import functools
import json
import logging
import sys
import webbrowser
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable, ParamSpec, TypeVar
from urllib.parse import urlparse
from concurrent.futures import Future

from wryview import DragDropEvent, PageLoadEvent, WebView
from wryview._core import WindowHandleKind as WryKind

from lumiview._bridge import BRIDGE_SCRIPT, Bridge
from lumiview._core import (
    CloseRequestedEvent,
    DestroyedEvent,
    FocusedEvent,
    MovedEvent,
    RedrawRequestedEvent,
    ResizeDirection,
    ResizedEvent,
    ScaleFactorChangedEvent,
    TaoEvent,
    TaoWindowBuilder,
    ThemeChangedEvent,
    UnfocusedEvent,
    WindowEffect,
    WindowHandleKind,
)
from lumiview._events import WindowHookEvent
from lumiview._task import Task, _run_async

if TYPE_CHECKING:
    from PIL.Image import Image as _PILImage

    from lumiview._app import App
    from lumiview._core import TaoWindow
    from lumiview.serve.base import Serve
else:
    _PILImage = object

_IconSource = str | tuple[bytes, int, int] | _PILImage

P = ParamSpec("P")
R = TypeVar("R")

log = logging.getLogger("lumiview.window")


class CloseBehavior(Enum):
    """What happens when the window receives a close request.

    - ``Close`` — destroy the window (default).
    - ``Hide`` — hide the window instead of destroying it.
    - ``Ignore`` — do nothing.
    """

    Close = auto()
    Hide = auto()
    Ignore = auto()


# @main_thread — decorator


def main_thread(
    fn: Callable[P, R],
) -> Callable[P, Task[R]]:
    """Decorate a sync ``def`` method so it returns ``Task[R]``
    and dispatches the body to the main (tao) thread.
    """

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Task[R]:
        from lumiview._app import App

        app = App.get()
        return app.call_on_main(fn, *args, **kwargs)

    return wrapper


# Window


class Window:
    """A managed desktop window with an embedded WebView.

    All methods that touch native resources return :class:`Task`.
    Use ``await`` in async code or ``.result()`` in sync code.
    """

    def __init__(self) -> None:
        if TYPE_CHECKING:
            self._app: App
            self._win_id: int
            self._tao: TaoWindow | None
            self._webview: WebView | None
            self._bridge: Bridge
            self._hooks: dict[WindowHookEvent, list[Callable[..., Any]]]
            self._close_behavior: CloseBehavior
            self._navigation_policy: Callable[[str], bool] | None
            self._new_win_policy: Callable[[str], str] | None
            self._download_started_policy: Callable[[str, str], bool | str] | None
            self._download_completed_policy: (
                Callable[[str, str | None, bool], None] | None
            )
            self._bridge_enabled: bool
            self._untrusted: bool
        raise RuntimeError("Use 'await Window.create(...)' instead")

    @classmethod
    @main_thread
    def create(
        cls,
        *,
        title: str = "lumiview",
        url: str | None = None,
        html: str | None = None,
        source: Serve | list[Serve] | None = None,
        # Geometry
        width: int = 800,
        height: int = 600,
        position: tuple[float, float] | None = None,
        min_size: tuple[float, float] | None = None,
        max_size: tuple[float, float] | None = None,
        # Appearance
        visible: bool = True,
        decorations: bool = True,
        resizable: bool = True,
        transparent: bool = False,
        maximized: bool = False,
        always_on_top: bool = False,
        undecorated_shadow: bool | None = None,
        icon: _IconSource | None = None,
        # Behavior
        focused: bool = True,
        focusable: bool = True,
        minimizable: bool = True,
        maximizable: bool = True,
        closable: bool = True,
        close_behavior: CloseBehavior = CloseBehavior.Close,
        visible_on_all_workspaces: bool = False,
        content_protection: bool = False,
        # DevTools
        devtools: bool = False,
        # Bridge
        bridge: Bridge | None = None,
        untrusted: bool = False,
        # WebView profile
        web_context: Any = None,
        data_directory: str | None = None,
        incognito: bool = False,
        proxy: str | None = None,
        user_agent: str | None = None,
        autoplay: bool = False,
        hotkeys_zoom: bool = True,
        clipboard: bool = True,
        javascript: bool = True,
        back_forward_gestures: bool = False,
        https_scheme: bool = True,
        default_context_menus: bool = True,
        drag_drop_handler: (
            Callable[[DragDropEvent, list[str], tuple[int, int]], bool] | None
        ) = None,
        background_color: tuple[int, int, int, int] | None = None,
        headers: dict[str, str] | None = None,
        # Policy callbacks
        on_navigation: Callable[[str], bool] | None = None,
        on_new_window: Callable[[str], str] | None = None,
        on_download_started: Callable[[str, str], bool | str] | None = None,
        on_download_completed: Callable[[str, str | None, bool], None] | None = None,
    ) -> Window:
        """Create a Window and its WebView (runs on main thread).

        Parameters:
            title: Window title bar text.
            url: URL to load. Takes priority over *html* and *source*.
            html: HTML string to load (used when *url* is None).
            source: A :class:`~lumiview.serve.Serve` instance — or a list
                of them — to register as custom protocol(s). Each Serve's
                ``scheme`` attribute names its protocol (default
                ``"lumiview"``); the first one is loaded as
                ``<scheme>://app/``. Lowest priority — *url* or *html*
                override it, but the protocols are still registered.
            width, height: Window size in logical pixels.
            devtools: Enable browser devtools (right-click → Inspect).
            transparent: Make the window background transparent.
            decorations: Show native title bar and borders.
            undecorated_shadow: Windows-only native shadow for a borderless
                window. ``None`` preserves Tao's default.
            resizable: Allow window resizing.
            close_behavior: :class:`CloseBehavior` — ``Close`` (destroy),
                ``Hide`` (hide on close), or ``Ignore`` (do nothing on
                close request).
            bridge: Optional :class:`Bridge` for JS↔Python IPC.
            untrusted: Do not inject any lumiview initialization scripts
                (no ``window.lumiview`` — JS cannot call Python and
                ``emit()`` events are not delivered). Mutually exclusive
                with *bridge*.
            web_context: A shared :class:`wryview.WebContext` for cross-window
                cookies, cache, and storage. Takes priority over
                *data_directory* and *incognito*.
            data_directory: Directory for persistent cookies/storage/cache.
                Per-window — not shared with other windows.
            incognito: Incognito profile (no persistence to disk).
            proxy: Proxy URL (``"http://host:port"`` or ``"socks5://host:port"``).
            user_agent: Custom User-Agent string.
            autoplay: Allow media autoplay.
            hotkeys_zoom: Enable Ctrl+/Ctrl- zoom (default ``True``).
            clipboard: Enable clipboard access (default ``True``).
            javascript: Enable JavaScript (default ``True``).
            background_color: Initial background colour ``(r, g, b, a)``.
            headers: Extra HTTP headers sent with every request.
            on_navigation: Called before navigation — return ``False`` to block.
                **Runs on the wryview callback thread — must be fast.**
            on_new_window: Called when ``window.open()`` is used.
                Return ``"allow"`` or ``"deny"``.
                **Runs on the wryview callback thread — must be fast.**
            on_download_started: Called when a download starts.
                Return ``True`` to allow, ``False`` to cancel, or a string
                path to redirect the download.
                **Runs on the wryview callback thread — must be fast.**
            on_download_completed: Called when a download finishes.
                Receives ``(url, path_or_none, success)``.
        """
        from lumiview._app import App

        app = App.get()

        if untrusted and bridge is not None:
            raise ValueError(
                "untrusted mode cannot be combined with a bridge "
                "(no scripts are injected)"
            )

        self = cls.__new__(cls)
        self._app = app
        self._tao = None
        self._webview = None
        self._hooks = {}
        self._close_behavior = close_behavior
        self._bridge = bridge or Bridge()
        self._navigation_policy = on_navigation
        self._new_win_policy = on_new_window
        self._download_started_policy = on_download_started
        self._download_completed_policy = on_download_completed
        self._bridge_enabled = bridge is not None
        self._untrusted = untrusted

        # Resolve source → url / html / custom_protocols
        custom_protocols: dict[str, Any] = {}
        resolved_url: str | None = None
        resolved_html: str | None = None

        serve_sources: list[Serve]
        if isinstance(source, (list, tuple)):
            serve_sources = [s for s in source]
        elif isinstance(source, str):
            raise TypeError(
                "source must be a Serve instance or a list of them; "
                "use url= for a URL string"
            )
        elif source is not None:
            serve_sources = [source]
        else:
            serve_sources = []

        for serve in serve_sources:
            scheme = getattr(serve, "scheme", "lumiview")
            if scheme in custom_protocols:
                raise ValueError(f"Duplicate custom protocol scheme: {scheme!r}")
            custom_protocols[scheme] = _make_protocol_handler(serve)

        if serve_sources:
            resolved_url = f"{getattr(serve_sources[0], 'scheme', 'lumiview')}://app/"

        if url is not None:
            resolved_url = url

        elif html is not None:
            resolved_html = html

        # Tao window
        builder = TaoWindowBuilder()
        builder.with_title(title)
        builder.with_inner_size(float(width), float(height))
        if position is not None:
            builder.with_position(float(position[0]), float(position[1]))
        if min_size is not None:
            builder.with_min_inner_size(float(min_size[0]), float(min_size[1]))
        if max_size is not None:
            builder.with_max_inner_size(float(max_size[0]), float(max_size[1]))
        builder.with_visible(visible)
        builder.with_resizable(resizable)
        if not decorations:
            builder.with_decorations(False)
        if undecorated_shadow is not None:
            builder.with_undecorated_shadow(undecorated_shadow)
        if transparent:
            builder.with_transparent(True)
        if maximized:
            builder.with_maximized(True)
        if always_on_top:
            builder.with_always_on_top(True)
        builder.with_focused(focused)
        if not focusable:
            builder.with_focusable(False)
        if not minimizable:
            builder.with_minimizable(False)
        if not maximizable:
            builder.with_maximizable(False)
        if not closable:
            builder.with_closable(False)
        if visible_on_all_workspaces:
            builder.with_visible_on_all_workspaces(True)
        if content_protection:
            builder.with_content_protection(True)
        if icon is not None:
            rgba, iw, ih = _load_icon(icon)
            builder.with_window_icon(iw, ih, rgba)
        tao_win = builder.build()

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

        init_scripts: list[str] = []
        if not untrusted:
            if bridge is not None:
                from lumiview._scope import InitContext

                try:
                    ctx = bridge._run_on_init(InitContext(inject_script=BRIDGE_SCRIPT))
                except Exception:
                    # TaoWindow has no explicit close: dropping the last
                    # reference destroys the native window (same path as
                    # Window.close()). Don't leak it when on_init raises.
                    del tao_win
                    raise
                init_scripts.append(ctx.inject_script)
            else:
                init_scripts.append(BRIDGE_SCRIPT)
        init_script = "\n".join(init_scripts) or None

        # WebView
        webview = WebView(
            handle,
            width=width,
            height=height,
            url=resolved_url,
            html=resolved_html,
            transparent=transparent,
            background_color=background_color,
            devtools=devtools,
            incognito=incognito,
            user_agent=user_agent,
            autoplay=autoplay,
            javascript_enabled=javascript,
            hotkeys_zoom=hotkeys_zoom,
            initialization_script=init_script,
            ipc_handler=self._make_ipc_handler(),
            on_navigation=self._make_navigation_handler(on_navigation),
            on_page_load=lambda ev, u: self._emit(_page_event(ev), u),
            on_title_changed=lambda t: self._emit(WindowHookEvent.TitleChanged, t),
            on_new_window=self._make_new_win_handler(on_new_window),
            drag_drop_handler=drag_drop_handler,
            custom_protocols=custom_protocols or None,
            proxy=_parse_proxy(proxy) if proxy is not None else None,
            back_forward_gestures=back_forward_gestures,
            clipboard=clipboard,
            data_directory=data_directory,
            web_context=web_context,
            headers=list(headers.items()) if headers is not None else None,
            https_scheme=https_scheme,
            default_context_menus=default_context_menus,
            on_download_started=(
                self._make_download_started_handler(on_download_started)
                if on_download_started is not None
                else None
            ),
            on_download_completed=(
                self._make_download_completed_handler(on_download_completed)
                if on_download_completed is not None
                else None
            ),
            as_child=True,
            parent_hwnd_kind=kind,
        )

        self._webview = webview
        self._tao = tao_win

        if transparent:
            # Wry creates its child HWND after Tao's parent surface. Refresh
            # the retained transparent backing once more so the first
            # composited frame cannot reuse Tao's opaque creation bitmap.
            tao_win._redraw_transparent_surface()

        win_id = tao_win.id()
        self._win_id = win_id
        app._windows[win_id] = self

        try:
            if bridge is not None:
                bridge._run_on_ready(self)
        except Exception:
            self.close()
            raise

        return self

    # Content

    @main_thread
    def load_url(self, url: str) -> None:
        assert self._webview is not None
        self._webview.load_url(url)

    @main_thread
    def load_html(self, html: str) -> None:
        assert self._webview is not None
        self._webview.load_html(html)

    @main_thread
    def reload(self) -> None:
        assert self._webview is not None
        self._webview.reload()

    # JavaScript

    def eval_js(self, script: str) -> Task[str]:
        from lumiview._app import App

        app = App.get()
        handle: Task[str] = Task()

        def _do():
            if self._webview is not None:
                self._webview.eval_js_with_callback(
                    script, lambda result: handle.set_result(result)
                )
            else:
                handle.set_exception(RuntimeError("WebView is not initialized"))

        dispatched = app.call_on_main(_do)
        if not handle.done():
            dispatched.add_done_callback(
                lambda d: _propagate_dispatch_failure(handle, d)
            )
        return handle

    # Appearance

    @main_thread
    def set_icon(self, icon: _IconSource) -> None:
        """Set the window icon.

        *icon* can be a file path (requires Pillow) or raw RGBA data::

            win.set_icon("path/to/icon.png")
            win.set_icon((rgba_bytes, 64, 64))
        """
        assert self._tao is not None
        rgba, w, h = _load_icon(icon)
        self._tao.set_window_icon(w, h, rgba)

    @main_thread
    def apply_effect(
        self,
        effect: WindowEffect,
        color: tuple[int, int, int, int] | None = None,
    ) -> None:
        """Apply a native window background material.

        Unsupported platforms or OS versions raise :class:`NotImplementedError`.
        """
        assert self._tao is not None
        self._tao.apply_effect(effect, color)

    @main_thread
    def clear_effect(self, effect: WindowEffect) -> None:
        """Clear a native material previously applied to this window."""
        assert self._tao is not None
        self._tao.clear_effect(effect)

    # Geometry

    @main_thread
    def set_bounds(self, x: float, y: float, w: float, h: float) -> None:
        assert self._webview is not None
        self._webview.set_bounds(x, y, w, h)

    @main_thread
    def set_size(self, width: float, height: float) -> None:
        assert self._tao is not None
        self._tao.set_inner_size(width, height)

    @main_thread
    def show(self) -> None:
        assert self._tao is not None
        self._tao.set_visible(True)
        self._tao.set_minimized(False)

    @main_thread
    def hide(self) -> None:
        assert self._tao is not None
        self._tao.set_visible(False)

    @main_thread
    def focus(self, flag: bool = True) -> None:
        assert self._tao is not None
        self._tao.set_focused(flag)

    @main_thread
    def minimize(self, flag: bool = True) -> None:
        assert self._tao is not None
        self._tao.set_minimized(flag)

    @main_thread
    def toggle_maximize(self) -> bool:
        assert self._tao is not None
        maximized = not self._tao.is_maximized()
        self._tao.set_maximized(maximized)
        return maximized

    @main_thread
    def set_fullscreen(self, fullscreen: bool) -> None:
        """Enter or exit fullscreen."""
        assert self._tao is not None
        self._tao.set_fullscreen(fullscreen)

    @main_thread
    def is_maximized(self) -> bool:
        assert self._tao is not None
        return self._tao.is_maximized()

    @main_thread
    def start_dragging(self) -> None:
        assert self._tao is not None
        self._tao.drag_window()

    @main_thread
    def start_resize_dragging(self, direction: ResizeDirection) -> None:
        assert self._tao is not None
        self._tao.drag_resize_window(direction)

    # Bridge

    def emit(self, event: str, payload: Any = None) -> Task[None]:
        """Send an event to JavaScript listeners.

        JS side::

            const unlisten = window.lumiview.listen("my-event", (payload) => {
                console.log(payload);
            });

        Python side::

            await win.emit("my-event", {"key": "value"})

        Events are fire-and-forget — no return value. The returned
        :class:`Task` resolves when the script has been delivered to
        the WebView (not when listeners have finished processing).
        """
        from lumiview._app import App

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
                handle.set_exception(RuntimeError("WebView is not initialized"))

        dispatched = app.call_on_main(_do)
        if not handle.done():
            dispatched.add_done_callback(
                lambda d: _propagate_dispatch_failure(handle, d)
            )
        return handle

    # Events

    def on(self, event: WindowHookEvent):
        """Register a per-window event handler."""

        def decorator(fn):
            self._hooks.setdefault(event, []).append(fn)
            return fn

        return decorator

    def _emit(self, event_or_name, *args: object) -> Future[None] | None:
        """Dispatch a per-window event to the asyncio loop."""
        if self._app._async_loop is None:
            return

        # Support both WindowHookEvent enums and legacy string names
        # (string names are kept for compatibility but have no handlers).
        if isinstance(event_or_name, WindowHookEvent):
            event = event_or_name
        else:
            event = event_or_name

        handlers = (
            self._hooks.get(event, []) if isinstance(event, WindowHookEvent) else []
        )

        if not handlers:
            return

        async def _dispatch() -> None:
            try:
                for fn in handlers:
                    try:
                        await _run_async(fn, *args, pool=self._app._threadpool)
                    except Exception:
                        logging.getLogger("lumiview.window").exception(
                            f"Error in {getattr(event, 'name', event)} handler: {fn}",
                        )
            finally:
                done.set_result(None)

        loop = self._app._async_loop
        assert loop is not None

        done: Future[None] = Future()

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_dispatch()))

        return done

    # Lifecycle

    def _on_tao_event(self, event: TaoEvent) -> None:
        """Handle a tao window event routed from the app (GUI thread)."""
        if isinstance(event, ResizedEvent):
            if self._webview is not None and self._tao is not None:
                sf = self._tao.scale_factor()
                self._webview.set_bounds(0, 0, event.width / sf, event.height / sf)
                # Resize the child HWND first, then replace the parent
                # backing surface. This prevents either old edge from
                # surviving into the newly composed frame.
                self._tao._redraw_transparent_surface()
            self._emit(WindowHookEvent.Resized, event.width, event.height)

        elif isinstance(event, MovedEvent):
            self._emit(WindowHookEvent.Moved, event.x, event.y)

        elif isinstance(event, FocusedEvent):
            self._emit(WindowHookEvent.Focused)

        elif isinstance(event, UnfocusedEvent):
            self._emit(WindowHookEvent.Unfocused)

        elif isinstance(event, ScaleFactorChangedEvent):
            self._emit(WindowHookEvent.ScaleFactorChanged, event.new_scale_factor)

        elif isinstance(event, ThemeChangedEvent):
            self._emit(WindowHookEvent.ThemeChanged, event.theme)

        elif isinstance(event, RedrawRequestedEvent):
            if self._tao is not None:
                self._tao._redraw_transparent_surface()

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
            self._tao = None
            self._webview = None
            self._app._remove_window(self._win_id)

    @main_thread
    def request_close(self) -> None:
        """Apply this window's configured ``close_behavior``."""
        self._request_close_now()

    def _request_close_now(self) -> None:
        """Apply ``close_behavior`` immediately on the GUI thread."""
        behavior = self._close_behavior
        if behavior == CloseBehavior.Ignore:
            return
        if behavior == CloseBehavior.Hide:
            if self._tao is not None:
                self._tao.set_visible(False)

        future = self._emit(WindowHookEvent.CloseRequested)

        if behavior == CloseBehavior.Close:
            if future is None:
                self.close()
            else:
                future.add_done_callback(lambda _: self.close())

    @main_thread
    def close(self) -> None:
        """Close the window and destroy its resources."""
        if self._webview is not None:
            self._webview.close()
        self._tao = None
        self._webview = None
        self._app._remove_window(self._win_id)

    # WebView capabilities (§11)

    @main_thread
    def open_devtools(self) -> None:
        assert self._webview is not None
        self._webview.open_devtools()

    @main_thread
    def close_devtools(self) -> None:
        assert self._webview is not None
        self._webview.close_devtools()

    @main_thread
    def is_devtools_open(self) -> bool:
        assert self._webview is not None
        return self._webview.is_devtools_open()

    @main_thread
    def zoom(self, scale: float) -> None:
        """Set the page zoom level. 1.0 = 100%, 1.5 = 150%."""
        assert self._webview is not None
        self._webview.zoom(scale)

    @main_thread
    def print(self) -> None:
        """Open the system print dialog for the current page."""
        assert self._webview is not None
        self._webview.print()

    @main_thread
    def set_background_color(self, r: int, g: int, b: int, a: int = 255) -> None:
        """Set the WebView background colour before content loads."""
        assert self._webview is not None
        self._webview.set_background_color(r, g, b, a)

    @main_thread
    def cookies(self) -> list[dict]:
        """Return all cookies as dicts with name, value, domain, path, etc."""
        assert self._webview is not None
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
        """Return cookies applicable to *url*."""
        assert self._webview is not None
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
        """Set a cookie."""
        assert self._webview is not None
        self._webview.set_cookie(name, value, domain, path)

    @main_thread
    def delete_cookie(self, name: str, url: str) -> None:
        """Delete a cookie by name for a specific URL."""
        assert self._webview is not None
        self._webview.delete_cookie(name, url)

    @main_thread
    def clear_all_browsing_data(self) -> None:
        """Clear all browsing data (cache, cookies, storage)."""
        assert self._webview is not None
        self._webview.clear_all_browsing_data()

    # Policy setters (post-creation)

    @main_thread
    def set_on_navigation(self, handler: Callable[[str], bool]) -> None:
        """Replace the navigation policy callback.

        The handler receives a URL and should return ``True`` to allow
        or ``False`` to block navigation.

        Dispatched on the GUI main thread; the returned :class:`Task`
        resolves once the policy is registered (not when the policy is
        later invoked).
        """
        self._navigation_policy = handler
        if self._webview is not None:
            self._webview.set_on_navigation(self._make_navigation_handler(handler))

    @main_thread
    def set_on_new_window(self, handler: Callable[[str], str]) -> None:
        """Replace the new-window policy callback.

        The handler receives a URL and should return ``"allow"``
        or ``"deny"``.

        Dispatched on the GUI main thread; the returned :class:`Task`
        resolves once the policy is registered (not when the policy is
        later invoked).
        """
        self._new_win_policy = handler
        if self._webview is not None:
            self._webview.set_on_new_window(self._make_new_win_handler(handler))

    @main_thread
    def set_on_download_started(
        self, handler: Callable[[str, str], bool | str]
    ) -> None:
        """Replace the download-started policy callback.

        Dispatched on the GUI main thread; the returned :class:`Task`
        resolves once the policy is registered (not when the policy is
        later invoked).
        """
        self._download_started_policy = handler
        if self._webview is not None:
            self._webview.set_on_download_started(
                self._make_download_started_handler(handler)
            )

    @main_thread
    def set_on_download_completed(
        self, handler: Callable[[str, str | None, bool], None]
    ) -> None:
        """Replace the download-completed notification callback.

        Dispatched on the GUI main thread; the returned :class:`Task`
        resolves once the policy is registered (not when the policy is
        later invoked).
        """
        self._download_completed_policy = handler
        if self._webview is not None:
            self._webview.set_on_download_completed(
                self._make_download_completed_handler(handler)
            )

    # Internal

    @property
    def _id(self) -> int:
        return self._win_id

    # Callback factories

    def _make_navigation_handler(
        self,
        policy: Callable[[str], bool] | None,
    ) -> Callable[[str], bool]:
        """Create a wryview navigation handler."""

        def _handler(url: str) -> bool:
            self._emit(WindowHookEvent.NavigationRequested, url)
            if policy is not None:
                try:
                    return policy(url)
                except Exception:
                    log.exception("Navigation policy raised")
            return True  # default: allow

        return _handler

    def _make_new_win_handler(
        self,
        policy: Callable[[str], str] | None,
    ) -> Callable[[str], str]:
        """Create a wryview new-window handler."""

        def _handler(url: str) -> str:
            self._emit(WindowHookEvent.NewWindowRequested, url)
            if policy is not None:
                try:
                    return policy(url)
                except Exception:
                    log.exception("New-window policy raised")
            # Default: deny and open in system browser.
            try:
                webbrowser.open(url)
            except Exception:
                pass
            return "deny"

        return _handler

    def _make_download_started_handler(
        self,
        policy: Callable[[str, str], bool | str],
    ) -> Callable[[str, str], bool | str]:
        """Create a wryview download-started handler."""

        def _handler(url: str, path: str) -> bool | str:
            try:
                return policy(url, path)
            except Exception:
                log.exception("Download-started policy raised")
            return True

        return _handler

    def _make_download_completed_handler(
        self,
        policy: Callable[[str, str | None, bool], None],
    ) -> Callable[[str, str | None, bool], None]:
        """Create a wryview download-completed handler."""

        def _handler(url: str, path: str | None, success: bool) -> None:
            try:
                policy(url, path, success)
            except Exception:
                log.exception("Download-completed policy raised")

        return _handler

    # IPC handler

    def _make_ipc_handler(self) -> Callable[[str], None]:
        """Create an IPC handler that forwards messages to the Bridge."""

        def _handler(raw: str) -> None:
            if self._untrusted:
                self._emit(WindowHookEvent.WebMessageReceived, raw)
            else:
                try:
                    if self._webview is not None:
                        self._bridge._on_message(self, raw)
                except Exception:
                    log.exception("IPC handler raised an unexpected exception")
                finally:
                    self._emit(WindowHookEvent.WebMessageReceived, raw)

        return _handler


# Module-level helpers


def _page_event(ev: PageLoadEvent) -> WindowHookEvent:
    """Map wryview PageLoadEvent enum to our WindowHookEvent."""
    return {
        PageLoadEvent.Started: WindowHookEvent.PageLoadStarted,
        PageLoadEvent.Finished: WindowHookEvent.PageLoadFinished,
    }[ev]


def _propagate_dispatch_failure(
    handle: Task[Any],
    dispatched: Future[Any],
) -> None:
    """Propagate a failed main-thread dispatch into *handle*.

    ``call_on_main`` returns its own Task. If it fails (app already stopped,
    or the queued callable raised) before *handle* was resolved, the failure
    would otherwise be swallowed and *handle* would stay pending forever.
    """
    if handle.done():
        return
    if dispatched.cancelled():
        handle.cancel()
    elif (exc := dispatched.exception()) is not None:
        handle.set_exception(exc)


# Helpers


def _load_icon(icon: _IconSource) -> tuple[bytes, int, int]:
    """Resolve icon input to (rgba_bytes, width, height).

    Accepts:
      - ``(bytes, int, int)`` — raw RGBA data + dimensions
      - ``str`` — file path (PNG, ICO, etc., requires Pillow)
      - ``PIL.Image.Image`` — a Pillow image object
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
    """Parse a proxy URL into the dict wryview expects."""
    proxy_type = "http"
    host = proxy
    port = "80"
    if "://" in proxy:
        proxy_type, rest = proxy.split("://", 1)
        host = rest
    if ":" in host:
        host, port = host.rsplit(":", 1)
    return {"type": proxy_type, "host": host, "port": port}


# Custom protocol handler


def _make_protocol_handler(serve: Serve) -> Callable[..., None]:
    """Create a wryview custom protocol handler from a Serve instance.

    The ``serve`` callable receives the ``respond`` callback directly and is
    responsible for calling it — synchronously or from any thread / event loop.
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
