"""lumiview — tao windows + wryview WebView, async-first and thread-safe.

    from lumiview import App, Window, WindowOptions

    app = App(name="MyApp")
    app.run(main)

Events live in :class:`lumiview.WindowEvent` / :class:`lumiview.AppEvent`;
low-level bindings are in :mod:`lumiview._core`.

Optional submodules are imported explicitly so ``import lumiview`` stays light:
``lumiview.serve`` (core protocol types), ``lumiview.plugins`` (plugins) and
``lumiview.utils`` are not re-exported here. Serve adapters and plugins live in
their own submodules, e.g. ``from lumiview.serve.static import Static`` or
``from lumiview.plugins.window_controls import WindowControls``.
"""

from lumiview.app import App, AppState, AppClosedError, WindowClosedError
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
    WindowPreventableEvent,
    AppEvent,
    AppBaseEvent,
    AppPreventableEvent,
)
from lumiview._utils import Subscription

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
    ActivationPolicy,
    ElementState,
    MouseButton,
    ScrollDeltaKind,
    TouchPhase,
)

__version__ = "0.2.0rc1"

__all__ = [
    "App",
    "AppState",
    "AppClosedError",
    "WindowClosedError",
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
    "Menu",
    "MenuItem",
    "Submenu",
    "CheckMenuItem",
    "PredefinedMenuItem",
    "TrayIcon",
    "TrayIconOptions",
    "ActivationPolicy",
    "Event",
    "WindowEvent",
    "WindowBaseEvent",
    "WindowPreventableEvent",
    "AppEvent",
    "AppBaseEvent",
    "AppPreventableEvent",
    "DragDropEvent",
    "Subscription",
    "MouseButton",
    "ElementState",
    "ScrollDeltaKind",
    "TouchPhase",
    "Bridge",
    "BridgeError",
    "Scope",
    "Plugin",
    "ScopePermission",
    "BridgeContext",
    "InitContext",
    "task",
    "Task",
    "TaskDeadlockError",
]
