"""
lumiview

Tao window management + wryview WebView = cross-platform desktop apps,
powered by Rust under the hood.

Application layer (default — start here)::

    from lumiview import App, Window, WindowOptions

    app = App(name="MyApp")

    async def main():
        win = await Window.create(WindowOptions(title="MyApp", url="https://example.com"))
        app.exit()

    app.run(main)

Events::

    from lumiview import WindowEvent

    @win.on(WindowEvent.TitleChangedEvent)
    def on_title(event):
        print(event.title)

Low-level bindings live in :mod:`lumiview._core`.
"""

from lumiview.app import App, AppState, AppClosedError, WindowClosedError
from lumiview._core import (
    AttentionType,
    CursorIcon,
    Monitor,
    ProgressState,
    ResizeDirection,
    Theme,
    VibrancyMaterial,
    VideoMode,
    WindowEffect,
    WindowHandleKind,
)
from lumiview.window import (
    CloseBehavior,
    TitleBarOptions,
    WebContext,
    Window,
    WindowOptions,
)
from lumiview.menu import (
    Menu,
    MenuItem,
    Submenu,
    CheckMenuItem,
    PredefinedMenuItem,
)
from lumiview.tray import TrayIcon, TrayIconOptions
from lumiview.bridge import Bridge, BridgeError
from lumiview.scope import Plugin, Scope, ScopePermission, BridgeContext, InitContext
from lumiview.task import task, Task, TaskDeadlockError
from lumiview.events import (
    DragDropEvent,
    Event,
    WindowEvent,
    WindowBaseEvent,
    AppEvent,
    AppBaseEvent,
)
from lumiview._utils import Subscription
from lumiview._core import (
    ActivationPolicy,
    ElementState,
    MouseButton,
    ScrollDeltaKind,
    StartCause,
    TouchPhase,
)
from lumiview import utils
from lumiview import plugins
from lumiview import serve

__version__ = "0.2.0rc1"

__all__ = [
    # Application layer
    "App",
    "AppState",
    "AppClosedError",
    "WindowClosedError",
    # Window layer
    "WebContext",
    "Window",
    "WindowOptions",
    "TitleBarOptions",
    "CloseBehavior",
    "WindowEffect",
    "ResizeDirection",
    "Theme",
    "CursorIcon",
    "AttentionType",
    "VibrancyMaterial",
    "ProgressState",
    "Monitor",
    "VideoMode",
    "WindowHandleKind",
    # Menus & tray
    "Menu",
    "MenuItem",
    "Submenu",
    "CheckMenuItem",
    "PredefinedMenuItem",
    "TrayIcon",
    "TrayIconOptions",
    "ActivationPolicy",
    # Events
    "Event",
    "WindowEvent",
    "WindowBaseEvent",
    "AppEvent",
    "AppBaseEvent",
    "DragDropEvent",
    "Subscription",
    # Event field types
    "MouseButton",
    "ElementState",
    "ScrollDeltaKind",
    "StartCause",
    "TouchPhase",
    # IPC
    "Bridge",
    "BridgeError",
    "Scope",
    "Plugin",
    "ScopePermission",
    "BridgeContext",
    "InitContext",
    # Concurrency
    "task",
    "Task",
    "TaskDeadlockError",
    # Subpackages
    "utils",
    "plugins",
    "serve",
]
