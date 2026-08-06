"""Native menus (muda) — app menu bar, window menu bar, tray menus.

``MenuItem`` / ``Submenu`` / ``CheckMenuItem`` / ``PredefinedMenuItem``
are **pure data carriers** (like :class:`~lumiview.window.WindowOptions`)
— construct them on any thread, before or after :meth:`App.run`. The
native menu tree is materialized on the main thread when the data tree is
attached (:meth:`Menu.create`, :meth:`Menu.attach_to_window`,
:meth:`Menu.install_nsapp`) or edited at runtime.

Runtime edits follow a dual-write model: the data field is updated first
(any thread, plain Python), then — only if the item is already
materialized — the native call is dispatched to the main thread and the
result returned as a :class:`Task`. Unattached items never touch native
objects, so editing them before :meth:`App.run` is free.

Activation events reach Python through a single per-process callback
registered by :meth:`App.run` (muda's ``MenuEvent::set_event_handler``
is a OnceCell). Every :class:`MenuItem` can register its own handler —
pass ``on_activate=fn`` at construction, or register later via
:meth:`MenuItem.on_activate` (decorator style) — and the same event is
also emitted globally as
:class:`~lumiview.events.AppEvent.MenuItemActivatedEvent` for
``app.on(...)``-style handling.

Handlers may be sync or ``async`` (auto-detected, like
:meth:`App.on <lumiview.app.App.on>`): async handlers are awaited on the
asyncio loop, sync handlers are dispatched to the app's thread pool.
Neither ever runs on the GUI thread.
"""

from __future__ import annotations

import logging
import sys
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, TypeAlias

from lumiview.app import App, WindowClosedError
from lumiview.events import AppEvent
from lumiview.task import Task
from lumiview.utils import main_thread
from lumiview._core import (
    TaoCheckMenuItem,
    TaoMenu,
    TaoMenuItem,
    TaoPredefinedMenuItem,
    TaoSubmenu,
)

if TYPE_CHECKING:
    from lumiview.window import Window

log = logging.getLogger("lumiview.menu")

# Item — a user-facing menu entry (data carrier). CheckMenuItem is a
# MenuItem subclass but is listed explicitly for clarity. String form:
# the classes are defined below and PEP 563 defers the annotation anyway.
Item: TypeAlias = "MenuItem | Submenu | CheckMenuItem | PredefinedMenuItem"

# NativeItem — the materialized Rust-side object for an Item.
NativeItem: TypeAlias = (
    "TaoMenuItem | TaoSubmenu | TaoCheckMenuItem | TaoPredefinedMenuItem"
)


def _auto_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


@dataclass(kw_only=True, init=False)
class MenuItem:
    """A plain menu item (pure data).

    Materialized on the main thread when added to a :class:`Menu`.

    Attributes:
        text: Label shown in the menu.
        id: Unique id string; auto-generated when omitted. Activation
            events carry this id.
        enabled: Whether the item is initially enabled.
        accelerator: Keyboard shortcut in muda syntax, e.g.
            ``"CmdOrCtrl+Shift+K"`` (modifiers may be ``Ctrl``, ``Shift``,
            ``Alt``, ``Cmd``, ``CmdOrCtrl`` ...). A malformed string
            raises ``ValueError`` when the item is materialized.

            .. note::
               **Windows**: accelerators may not fire from the keyboard —
               PRs welcome to fix this.
        on_activate: A handler called when the item is activated — the
            same as calling :meth:`on_activate` afterwards.
    """

    text: str
    # Always set — the constructor accepts None and generates an id.
    id: str = field(init=False)
    enabled: bool = True
    accelerator: str | None = None

    # Internal state — not constructor arguments.
    _inner: NativeItem | None = field(default=None, init=False, repr=False)
    _activate_callbacks: list[Callable[[AppEvent.MenuItemActivatedEvent], Any]] = field(
        default_factory=list, init=False, repr=False
    )

    def __init__(
        self,
        *,
        text: str,
        id: str | None = None,
        enabled: bool = True,
        accelerator: str | None = None,
        on_activate: Callable[[AppEvent.MenuItemActivatedEvent], Any] | None = None,
    ) -> None:
        # Hand-written __init__ (dataclass init=False): the *on_activate*
        # keyword names the same thing as the instance method below, which
        # a dataclass-generated __init__ cannot express.
        self.text = text
        self.id = id if id is not None else _auto_id("item")
        self.enabled = enabled
        self.accelerator = accelerator
        self._inner = None
        self._activate_callbacks = []
        if on_activate is not None:
            self._activate_callbacks.append(on_activate)

    def on_activate(
        self, fn: Callable[[AppEvent.MenuItemActivatedEvent], Any]
    ) -> Callable[[AppEvent.MenuItemActivatedEvent], Any]:
        """Register a handler for this item's activation.

        Equivalent to passing ``on_activate=fn`` at construction. Works
        as a decorator or a plain call; multiple handlers are supported
        and run in registration order.

        Handlers may be sync or ``async`` — auto-detected. They run on
        the asyncio loop (never the main GUI thread): async handlers are
        awaited directly, sync handlers are dispatched to the app's
        thread pool. Safe to call :meth:`~lumiview.window.Window` methods
        from inside a handler (``await`` in async handlers, ``.result()``
        in sync ones).
        """
        self._activate_callbacks.append(fn)
        return fn

    # Runtime edits — dual write: update the data field, then push to the
    # native item if materialized. Returns a Task (done immediately when
    # the item is not materialized).

    def set_text(self, text: str) -> Task[None]:
        """Change the label (any thread)."""
        self.text = text
        return self._native_call("set_text", text)

    def set_enabled(self, enabled: bool) -> Task[None]:
        """Enable or disable the item (any thread)."""
        self.enabled = enabled
        return self._native_call("set_enabled", enabled)

    def set_accelerator(self, accelerator: str | None) -> Task[None]:
        """Replace the keyboard shortcut; ``None`` removes it (any thread).

        A malformed string fails the returned :class:`Task` with
        ``ValueError``.
        """
        self.accelerator = accelerator
        return self._native_call("set_accelerator", accelerator)

    def _native_call(self, name: str, *args: Any) -> Task[None]:
        if self._inner is None:
            return Task._done(None)
        return App.get().call_on_main(getattr(self._inner, name), *args)


@dataclass(kw_only=True, init=False)
class CheckMenuItem(MenuItem):
    """A checkable menu item (toggle with a checkmark).

    Attributes:
        checked: Initial checked state.
        on_activate: A handler called when the item is activated (same as
            :meth:`MenuItem.on_activate`).
    """

    checked: bool = False

    def __init__(
        self,
        *,
        text: str,
        id: str | None = None,
        enabled: bool = True,
        accelerator: str | None = None,
        checked: bool = False,
        on_activate: Callable[[AppEvent.MenuItemActivatedEvent], Any] | None = None,
    ) -> None:
        super().__init__(
            text=text, id=id, enabled=enabled, accelerator=accelerator,
            on_activate=on_activate,
        )
        self.checked = checked

    def set_checked(self, checked: bool) -> Task[None]:
        """Set the checked state (any thread)."""
        self.checked = checked
        return self._native_call("set_checked", checked)


@dataclass(kw_only=True, init=False)
class Submenu:
    """A submenu: a menu item that can contain other items.

    Also used as the top level of a menu bar (each top-level entry of a
    :class:`Menu` is a :class:`Submenu`).

    Attributes:
        text: Label shown in the menu bar / parent menu.
        items: Child items (may be nested).
        id: Unique id string; auto-generated when omitted.
        enabled: Whether the submenu is initially enabled.
    """

    text: str
    items: list[Item] = field(default_factory=list)
    # Always set — the constructor accepts None and generates an id.
    id: str = field(init=False)
    enabled: bool = True

    _inner: TaoSubmenu | None = field(default=None, init=False, repr=False)
    _is_window_menu: bool = field(default=False, init=False, repr=False)

    def __init__(
        self,
        *,
        text: str,
        items: list[Item] | None = None,
        id: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.text = text
        self.items = items if items is not None else []
        self.id = id if id is not None else _auto_id("submenu")
        self.enabled = enabled
        self._inner = None
        self._is_window_menu = False

    # Runtime edits — same dual-write model as MenuItem. Native work is
    # batched into a single main-thread dispatch: materializing *item*
    # creates an unsendable object and must not run off-thread.

    def append(self, item: Item) -> Task[None]:
        """Append an item at runtime (any thread)."""
        self.items.append(item)
        if self._inner is None:
            return Task._done(None)
        app = App.get()
        inner_menu = self._inner  # narrowed below; captured by the closure

        def _do() -> None:
            inner_item = Menu._materialize_item(item)
            inner_menu.append(inner_item)

        return app.call_on_main(_do)

    def insert(self, item: Item, position: int) -> Task[None]:
        """Insert an item at *position* (any thread)."""
        self.items.insert(position, item)
        if self._inner is None:
            return Task._done(None)
        app = App.get()
        inner_menu = self._inner  # narrowed below; captured by the closure

        def _do() -> None:
            inner_item = Menu._materialize_item(item)
            inner_menu.insert(inner_item, position)

        return app.call_on_main(_do)

    def remove(self, item: Item) -> Task[None]:
        """Remove an item at runtime (any thread)."""
        if item in self.items:
            self.items.remove(item)
        if self._inner is None or item._inner is None:
            return Task._done(None)
        return App.get().call_on_main(self._inner.remove, item._inner)


class PredefinedMenuItem:
    """A system-behavior menu item (pure data).

    Predefined items perform their OS action natively (copy, quit,
    separator, ...) and **do not** generate activation events, so there
    is no ``on_activate``. Use the classmethod factories to build them.
    """

    def __init__(
        self,
        kind: str,
        text: str | None = None,
        name: str | None = None,
        version: str | None = None,
    ) -> None:
        self.kind = kind
        self.text = text
        self.name = name
        self.version = version
        self._inner: TaoPredefinedMenuItem | None = None

    # Factories

    @classmethod
    def separator(cls) -> "PredefinedMenuItem":
        """A horizontal separator line."""
        return cls("separator")

    @classmethod
    def copy(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("copy", text)

    @classmethod
    def cut(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("cut", text)

    @classmethod
    def paste(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("paste", text)

    @classmethod
    def select_all(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("select_all", text)

    @classmethod
    def undo(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("undo", text)

    @classmethod
    def redo(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("redo", text)

    @classmethod
    def minimize(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("minimize", text)

    @classmethod
    def maximize(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("maximize", text)

    @classmethod
    def fullscreen(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("fullscreen", text)

    @classmethod
    def hide(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("hide", text)

    @classmethod
    def hide_others(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("hide_others", text)

    @classmethod
    def show_all(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("show_all", text)

    @classmethod
    def close_window(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("close_window", text)

    @classmethod
    def quit(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("quit", text)

    @classmethod
    def about(
        cls,
        text: str | None = None,
        name: str | None = None,
        version: str | None = None,
    ) -> "PredefinedMenuItem":
        """The system "About" dialog. *name*/*version* feed its content."""
        return cls("about", text, name, version)

    @classmethod
    def services(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("services", text)

    @classmethod
    def bring_all_to_front(cls, text: str | None = None) -> "PredefinedMenuItem":
        return cls("bring_all_to_front", text)

    def __repr__(self) -> str:
        return f"PredefinedMenuItem(kind={self.kind!r})"


class Menu:
    """A root menu — the app menu bar (macOS), a window menu bar
    (Windows), or the menu attached to a tray icon.

    Create with ``await Menu.create(items=[...])`` — the plain
    constructor raises.

    On macOS, :meth:`App.run` installs a default menu bar
    (:meth:`default_app_menu`); replace it by creating a Menu and calling
    :meth:`install_nsapp` (``remove_from_nsapp`` restores nothing — it
    only detaches the current menu). On Windows, attach a menu to a
    window with :meth:`attach_to_window`.
    """

    def __init__(self) -> None:
        raise RuntimeError("Use 'await Menu.create(items=[...])' instead")

    _inner: TaoMenu | None = None
    _items: list[Item] = []

    @classmethod
    @main_thread
    def create(cls, *, items: list[Item]) -> "Menu":
        """Materialize the whole menu tree on the main thread.

        Returns a :class:`Task` — ``await`` in async code, ``.result()``
        in sync code.
        """
        app = App.get()
        menu = cls.__new__(cls)
        menu._items = list(items)
        menu._inner = TaoMenu()
        app._menus.append(menu)
        for item in items:
            inner = cls._materialize_item(item)
            menu._inner.append(inner)
        return menu

    @classmethod
    def default_app_menu(cls) -> "Menu":
        """The default app menu bar (pure data — any thread, no
        materialization): Application / Edit / Window, all system
        behaviors.

        Installed automatically by :meth:`App.run` on macOS; call
        :meth:`install_nsapp` on another Menu to replace it.
        """
        menu = cls.__new__(cls)
        app_menu = Submenu(
            id="__app",
            text="Application",
            items=[
                PredefinedMenuItem.about(),
                PredefinedMenuItem.separator(),
                PredefinedMenuItem.services(),
                PredefinedMenuItem.separator(),
                PredefinedMenuItem.hide(),
                PredefinedMenuItem.hide_others(),
                PredefinedMenuItem.show_all(),
                PredefinedMenuItem.separator(),
                PredefinedMenuItem.quit(),
            ],
        )
        edit_menu = Submenu(
            id="__edit",
            text="Edit",
            items=[
                PredefinedMenuItem.undo(),
                PredefinedMenuItem.redo(),
                PredefinedMenuItem.separator(),
                PredefinedMenuItem.cut(),
                PredefinedMenuItem.copy(),
                PredefinedMenuItem.paste(),
                PredefinedMenuItem.select_all(),
            ],
        )
        window_menu = Submenu(
            id="__window",
            text="Window",
            items=[
                PredefinedMenuItem.minimize(),
                PredefinedMenuItem.maximize(),
                PredefinedMenuItem.separator(),
                PredefinedMenuItem.bring_all_to_front(),
            ],
        )
        window_menu._is_window_menu = True
        menu._items = [app_menu, edit_menu, window_menu]
        return menu

    # Internal — main thread only

    @classmethod
    def _materialize_item(cls, item: Item) -> NativeItem:
        """Build the native object for *item* (idempotent), register it
        in the app's id → wrapper table, and return it. Main thread only.
        """
        if isinstance(item, CheckMenuItem):
            if item._inner is None:
                item._inner = TaoCheckMenuItem(
                    id=item.id,
                    text=item.text,
                    enabled=item.enabled,
                    checked=item.checked,
                    accelerator=item.accelerator,
                )
            cls._register(item)
        elif isinstance(item, MenuItem):
            if item._inner is None:
                item._inner = TaoMenuItem(
                    id=item.id,
                    text=item.text,
                    enabled=item.enabled,
                    accelerator=item.accelerator,
                )
            cls._register(item)
        elif isinstance(item, PredefinedMenuItem):
            if item._inner is None:
                item._inner = TaoPredefinedMenuItem(
                    kind=item.kind, text=item.text, name=item.name, version=item.version
                )
            # Predefined items never emit activation events — no id to
            # register (and no on_activate).
        elif isinstance(item, Submenu):
            if item._inner is None:
                item._inner = TaoSubmenu(id=item.id, text=item.text, enabled=item.enabled)
            cls._register(item)
            for child in item.items:
                inner_child = cls._materialize_item(child)
                item._inner.append(inner_child)
        else:
            raise TypeError(
                f"unsupported menu item: {type(item).__name__} "
                "(expected MenuItem, CheckMenuItem, Submenu or PredefinedMenuItem)"
            )
        assert item._inner is not None  # set in the branches above
        return item._inner

    @classmethod
    def _register(cls, item: MenuItem | Submenu) -> None:
        """Register *item* under its id in the app's table, warning on
        duplicates (Windows shares command ids among duplicates, which
        makes activation events ambiguous). Only items that can emit
        activation events are registered (PredefinedMenuItem never does).
        """
        app = App.get()
        prev = app._menu_items.get(item.id)
        if prev is not None and prev is not item:
            log.warning(
                "duplicate menu item id %r — activation events may be ambiguous", item.id
            )
        app._menu_items[item.id] = item

    def _materialize(self) -> TaoMenu:
        """Materialize the tree on the main thread if needed (idempotent)."""
        if self._inner is None:
            app = App.get()
            self._inner = TaoMenu()
            app._menus.append(self)
            for item in self._items:
                inner = Menu._materialize_item(item)
                self._inner.append(inner)
        return self._inner

    # Platform attachment (main thread)

    @main_thread
    def install_nsapp(self) -> None:
        """macOS: replace the application menu bar with this menu.

        ``Window`` submenus built with ``_is_window_menu`` are registered
        so macOS populates the window list and tiling shortcuts.
        """
        if sys.platform != "darwin":
            raise NotImplementedError("install_nsapp() is macOS only")
        inner = self._materialize()
        inner.init_for_nsapp()
        for item in self._items:
            if (
                isinstance(item, Submenu)
                and item._is_window_menu
                and item._inner is not None
            ):
                item._inner.set_as_windows_menu_for_nsapp()

    @main_thread
    def remove_from_nsapp(self) -> None:
        """macOS: detach this menu from the application menu bar."""
        if sys.platform != "darwin":
            raise NotImplementedError("remove_from_nsapp() is macOS only")
        if self._inner is not None:
            self._inner.remove_for_nsapp()

    @main_thread
    def attach_to_window(self, win: "Window") -> None:
        """Windows: attach this menu as *win*'s menu bar (below the
        title bar). Detach with :meth:`remove_from_window`.
        """
        if sys.platform != "win32":
            raise NotImplementedError("attach_to_window() is Windows only")
        if win._window is None:
            raise WindowClosedError()
        hwnd = win._window.native_handle()
        inner = self._materialize()
        inner.init_for_hwnd(hwnd)

    @main_thread
    def remove_from_window(self, win: "Window") -> None:
        """Windows: detach this menu from *win*'s menu bar."""
        if sys.platform != "win32":
            raise NotImplementedError("remove_from_window() is Windows only")
        if win._window is None:
            raise WindowClosedError()
        hwnd = win._window.native_handle()
        if self._inner is not None:
            self._inner.remove_for_hwnd(hwnd)

    # Runtime editing (main thread)

    @main_thread
    def append(self, item: Item) -> None:
        """Append an item to this menu at runtime."""
        inner = Menu._materialize_item(item)
        self._items.append(item)
        self._materialize().append(inner)

    @main_thread
    def insert(self, item: Item, position: int) -> None:
        """Insert an item at *position* at runtime."""
        inner = Menu._materialize_item(item)
        self._items.insert(position, item)
        self._materialize().insert(inner, position)

    @main_thread
    def remove(self, item: Item) -> None:
        """Remove an item from this menu at runtime."""
        if item in self._items:
            self._items.remove(item)
        if item._inner is not None:
            self._materialize().remove(item._inner)

    def __repr__(self) -> str:
        return f"Menu(items={len(self._items)})"
