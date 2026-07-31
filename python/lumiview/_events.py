"""Hook event types — use these instead of raw strings."""

from __future__ import annotations

from enum import Enum, auto


class AppHookEvent(Enum):
    """Events you can register for via ``app.on()``.

    ============================ =========================================
    Event                         Fires when …
    ============================ =========================================
    ``Ready``                     App started, asyncio loop running
    ``Close``                     Window is about to be destroyed
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
    ``NavigationRequested``       Navigation about to happen (can block)
    ``NewWindowRequested``        ``window.open()`` or similar
    ``WebMessageReceived``        Raw IPC message (non-bridge)
    ============================ =========================================
    """

    PageLoadStarted = auto()
    PageLoadFinished = auto()
    TitleChanged = auto()
    NavigationRequested = auto()
    NewWindowRequested = auto()
    WebMessageReceived = auto()
