"""Native menus (muda) — app menu bar, window menu bar, tray menus.

Items are pure data (any thread); the tree is materialized on the main thread
by :meth:`Menu.create` / ``attach_to_window`` / ``install_nsapp``. Runtime edits
follow dual-write on the main thread: data first, native call only when already
materialized.

Activation reaches both the item's ``on_activate`` handlers and
:class:`~lumiview.events.AppEvent.MenuItemActivatedEvent`.
"""

from __future__ import annotations

import copy
import logging
import sys
import uuid
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any, Callable, TypeAlias, TypeVar

from lumiview.app import App
from lumiview.events import AppEvent
from lumiview.task import Task
from lumiview._utils import main_thread
from lumiview._core import (
    TaoCheckMenuItem,
    TaoMenu,
    TaoMenuItem,
    TaoPredefinedMenuItem,
    TaoSubmenu,
)

if TYPE_CHECKING:
    from lumiview.window import Window

_log = logging.getLogger("lumiview.menu")

Item: TypeAlias = "MenuItem | Submenu | CheckMenuItem | PredefinedMenuItem"

NativeItem: TypeAlias = (
    "TaoMenuItem | TaoSubmenu | TaoCheckMenuItem | TaoPredefinedMenuItem"
)

R = TypeVar("R")


def _auto_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


@dataclass(kw_only=True, init=False)
class MenuItem:
    """A plain menu item (pure data; materialized on the main thread)."""

    text: str
    # Always set — the constructor accepts None and generates an id.
    id: str = field(init=False)
    enabled: bool = True
    accelerator: str | None = None

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
        # Hand-written __init__: a generated one cannot shadow on_activate().
        self.text = text
        self.id = id if id is not None else _auto_id("item")
        self.enabled = enabled
        self.accelerator = accelerator
        self._inner = None
        self._activate_callbacks = []
        if on_activate is not None:
            self._activate_callbacks.append(on_activate)

    def on_activate(
        self, fn: Callable[[AppEvent.MenuItemActivatedEvent], R]
    ) -> Callable[[AppEvent.MenuItemActivatedEvent], R]:
        """Register a handler for this item's activation (decorator or plain call).

        Handlers are sync or async and never run on the GUI thread.
        """
        self._activate_callbacks.append(fn)
        return fn

    # Dual write: data first, native only if materialized.

    def set_text(self, text: str) -> Task[None]:
        """Change the label (any thread)."""
        self.text = text
        return self._native_call("set_text", text)

    def set_enabled(self, enabled: bool) -> Task[None]:
        """Enable or disable the item (any thread)."""
        self.enabled = enabled
        return self._native_call("set_enabled", enabled)

    def set_accelerator(self, accelerator: str | None) -> Task[None]:
        """Replace the keyboard shortcut; ``None`` removes it (any thread)."""
        self.accelerator = accelerator
        return self._native_call("set_accelerator", accelerator)

    def _native_call(self, name: str, *args: Any) -> Task[None]:
        # Read once: shutdown may clear _inner between two reads.
        inner = self._inner
        if inner is None:
            return Task._done(None)
        return App.get().call_on_main(getattr(inner, name), *args)

    def _release_native(self) -> None:
        """Drop the native item handle (main thread only)."""
        self._inner = None

    def copy(self, **changes: Any) -> "MenuItem":
        """Return a copy with *changes* applied (keeps ``id`` and ``on_activate``)."""
        clone = copy.copy(self)
        clone._inner = None
        clone._activate_callbacks = list(self._activate_callbacks)
        known = {f.name for f in fields(self)}
        for name, value in changes.items():
            if name not in known:
                raise TypeError(f"unknown field {name!r} for {type(self).__name__}")
            setattr(clone, name, value)
        return clone


@dataclass(kw_only=True, init=False)
class CheckMenuItem(MenuItem):
    """A checkable menu item (toggle with a checkmark)."""

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
            text=text,
            id=id,
            enabled=enabled,
            accelerator=accelerator,
            on_activate=on_activate,
        )
        self.checked = checked

    def set_checked(self, checked: bool) -> Task[None]:
        """Set the checked state (any thread)."""
        self.checked = checked
        return self._native_call("set_checked", checked)


@dataclass(kw_only=True, init=False)
class Submenu:
    """A submenu — also the top level of a menu bar."""

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

    def _release_native(self) -> None:
        """Drop the native submenu handle (main thread only)."""
        self._inner = None

    def copy(self, **changes: Any) -> "Submenu":
        """Return a copy with *changes* applied (see :meth:`MenuItem.copy`)."""
        clone = copy.copy(self)
        clone._inner = None
        clone.items = list(self.items)
        known = {f.name for f in fields(self)}
        for name, value in changes.items():
            if name not in known:
                raise TypeError(f"unknown field {name!r} for Submenu")
            setattr(clone, name, value)
        return clone

    # Structural edits run on the main thread, so the data order and the native
    # order cannot diverge (and the list is serialized with materialization).

    @main_thread
    def append(self, item: Item) -> None:
        """Append an item at runtime (any thread)."""
        inner_menu = self._inner
        if inner_menu is None:
            self.items.append(item)
            return
        inner = Menu._materialize_item(item)
        self.items.append(item)
        inner_menu.append(inner)

    @main_thread
    def insert(self, item: Item, position: int) -> None:
        """Insert an item at *position* at runtime (any thread)."""
        inner_menu = self._inner
        if inner_menu is None:
            self.items.insert(position, item)
            return
        inner = Menu._materialize_item(item)
        self.items.insert(position, item)
        inner_menu.insert(inner, position)

    @main_thread
    def remove(self, item: Item) -> None:
        """Remove an item at runtime (any thread)."""
        if item in self.items:
            self.items.remove(item)
        inner_menu = self._inner
        if inner_menu is not None and item._inner is not None:
            inner_menu.remove(item._inner)


class PredefinedMenuItem:
    """A system-behavior menu item (pure data).

    Performs its OS action natively and never emits an activation event.
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
    """A root menu: the app menu bar (macOS), a window menu bar (Windows) or a tray
    menu. Create with ``await Menu.create(items=[...])`` — the plain constructor
    raises.
    """

    def __init__(self) -> None:
        raise RuntimeError("Use 'await Menu.create(items=[...])' instead")

    _inner: TaoMenu | None = None
    _items: list[Item]

    @property
    def items(self) -> tuple[Item, ...]:
        """A read-only snapshot of this menu's top-level items."""
        return tuple(self._items)

    def _release_native(self) -> None:
        """Drop the native menu handle (main thread only)."""
        self._inner = None

    @classmethod
    @main_thread
    def create(cls, *, items: list[Item]) -> "Menu":
        """Materialize the whole menu tree on the main thread."""
        app = App.get()
        menu = cls.__new__(cls)
        menu._items = list(items)
        menu._inner = TaoMenu()
        app._register_menu(menu)
        for item in items:
            inner = cls._materialize_item(item)
            menu._inner.append(inner)
        _log.debug("Materialized menu with %d item(s)", len(items))
        return menu

    @classmethod
    def default_app_menu(cls) -> "Menu":
        """The default app menu bar (Application / Edit / Window).

        Installed automatically on macOS. Its Quit item calls ``App.exit()`` so ⌘Q takes
        the graceful path instead of the native ``terminate:``.
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
                MenuItem(
                    id="__quit",
                    text="Quit",
                    accelerator="CmdOrCtrl+Q",
                    on_activate=lambda _event: App.get().exit(),
                ),
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
                PredefinedMenuItem.close_window(),
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
            # Predefined items never emit activation events.
        elif isinstance(item, Submenu):
            if item._inner is None:
                item._inner = TaoSubmenu(
                    id=item.id, text=item.text, enabled=item.enabled
                )
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
        """Register *item* under its id (duplicate ids make activation ambiguous)."""
        app = App.get()
        prev = app._menu_items.get(item.id)
        if prev is not None and prev is not item:
            _log.warning(
                "duplicate menu item id %r — activation events may be ambiguous",
                item.id,
            )
        app._register_menu_item(item)

    def _materialize(self) -> TaoMenu:
        """Materialize the tree on the main thread if needed (idempotent)."""
        if self._inner is None:
            app = App.get()
            self._inner = TaoMenu()
            app._register_menu(self)
            for item in self._items:
                inner = Menu._materialize_item(item)
                self._inner.append(inner)
        return self._inner

    # Platform attachment (main thread)

    @main_thread
    def install_nsapp(self) -> None:
        """macOS: replace the application menu bar with this menu."""
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
        hwnd = win._require_hwnd()
        inner = self._materialize()
        inner.init_for_hwnd(hwnd)

    @main_thread
    def remove_from_window(self, win: "Window") -> None:
        """Windows: detach this menu from *win*'s menu bar."""
        if sys.platform != "win32":
            raise NotImplementedError("remove_from_window() is Windows only")
        hwnd = win._require_hwnd()
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
