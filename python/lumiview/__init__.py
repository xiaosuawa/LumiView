"""
lumiview

Tao window management + wryview WebView = cross-platform desktop apps,
powered by Rust under the hood.

Application layer (default — start here)::

    from lumiview import App, Window

    app = App(name="MyApp")

    async def main():
        win = await Window.create(title="MyApp", url="https://example.com")
        app.exit()

    app.run(main)

Low-level bindings (available when you need them)::

    from lumiview import TaoEventLoop, TaoWindowBuilder, ...
"""

from lumiview._core import (
    TaoEventLoop,
    TaoEventLoopProxy,
    TaoWindowBuilder,
    TaoWindow,
    WindowEffect,
    ResizeDirection,
    WindowHandleKind,
    EventLoopControl,
    EventKind,
    ModifiersState,
    MouseButton,
    ElementState,
    ScrollDeltaKind,
    TouchPhase,
    KeyLocation,
    Theme,
    TaoEvent,
    ResizedEvent,
    MovedEvent,
    CloseRequestedEvent,
    DestroyedEvent,
    FocusedEvent,
    UnfocusedEvent,
    ScaleFactorChangedEvent,
    ThemeChangedEvent,
    MouseInputEvent,
    CursorMovedEvent,
    MouseWheelEvent,
    KeyboardInputEvent,
    ModifiersChangedEvent,
    CursorEnteredEvent,
    CursorLeftEvent,
    RedrawRequestedEvent,
    UserEvent,
    LoopDestroyedEvent,
)

from lumiview._app import App, AppState, AppClosedError, WindowClosedError
from lumiview._events import WindowHookEvent, AppHookEvent
from lumiview._bridge import Bridge, BridgeError
from lumiview._scope import Scope, ScopePermission, BridgeContext, InitContext
from lumiview._window import CloseBehavior, Window
from lumiview._task import task, Task, TaskDeadlockError
from lumiview import utils
from lumiview import plugins

# Serve subpackage (§10)

from lumiview.serve import Request, Response, Serve, Static, WSGI, ASGI, Handler

__version__ = "0.1.0.dev1"

__all__ = [
    # Application layer
    "App",
    "AppState",
    "CloseBehavior",
    "Window",
    "WindowEffect",
    "ResizeDirection",
    "WindowHookEvent",
    "AppHookEvent",
    "Bridge",
    "BridgeError",
    "Scope",
    "ScopePermission",
    "BridgeContext",
    "InitContext",
    "utils",
    "plugins",
    "task",
    "Task",
    "TaskDeadlockError",
    "AppClosedError",
    "WindowClosedError",
    # Serve
    "Request",
    "Response",
    "Serve",
    "Static",
    "WSGI",
    "ASGI",
    "Handler",
    # Low-level bindings
    "TaoEventLoop",
    "TaoEventLoopProxy",
    "TaoWindowBuilder",
    "TaoWindow",
    "WindowHandleKind",
    "EventLoopControl",
    "EventKind",
    "ModifiersState",
    "MouseButton",
    "ElementState",
    "ScrollDeltaKind",
    "TouchPhase",
    "KeyLocation",
    "Theme",
    "TaoEvent",
    "ResizedEvent",
    "MovedEvent",
    "CloseRequestedEvent",
    "DestroyedEvent",
    "FocusedEvent",
    "UnfocusedEvent",
    "ScaleFactorChangedEvent",
    "ThemeChangedEvent",
    "MouseInputEvent",
    "CursorMovedEvent",
    "MouseWheelEvent",
    "KeyboardInputEvent",
    "ModifiersChangedEvent",
    "CursorEnteredEvent",
    "CursorLeftEvent",
    "RedrawRequestedEvent",
    "UserEvent",
    "LoopDestroyedEvent",
]
