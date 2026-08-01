"""Hook event types — use these instead of raw strings."""

from __future__ import annotations

from enum import Enum, auto


class AppHookEvent(Enum):
    """Events you can register for via ``app.on()``.

    ============================ =========================================
    Event                         Fires when …
    ============================ =========================================
    ``Ready``                     App started, asyncio loop running
    ``Close``                     App shutdown flow (fires exactly once,
                                  after all windows are closed)
    ============================ =========================================
    """

    # App events
    Ready = auto()
    Close = auto()


class WindowHookEvent(Enum):
    """Events you can register for via ``win.on()``.

    ============================ =========================================
    Event                         Fires when …
    ============================ =========================================
    ``PageLoadStarted``           A new URL begins loading
    ``PageLoadFinished``          Page load complete
    ``TitleChanged``              ``document.title`` changed
    ``NavigationRequested``       Navigation about to happen
    ``NewWindowRequested``        ``window.open()`` or similar
    ``CloseRequested``            Window close requested (per :class:`CloseBehavior`)
    ``WebMessageReceived``        Raw IPC message (non-bridge)
    ``Resized``                   Window size changed (``width, height``,
                                  physical pixels)
    ``Moved``                     Window position changed (``x, y``,
                                  physical screen coordinates)
    ``Focused``                   Window gained keyboard focus
    ``Unfocused``                 Window lost keyboard focus
    ``ScaleFactorChanged``        DPI scale factor changed (``new_scale_factor``)
    ``ThemeChanged``              System theme changed (``theme``)
    ============================ =========================================
    """

    PageLoadStarted = auto()
    PageLoadFinished = auto()
    TitleChanged = auto()
    NavigationRequested = auto()
    NewWindowRequested = auto()
    CloseRequested = auto()
    WebMessageReceived = auto()
    Resized = auto()
    Moved = auto()
    Focused = auto()
    Unfocused = auto()
    ScaleFactorChanged = auto()
    ThemeChanged = auto()
