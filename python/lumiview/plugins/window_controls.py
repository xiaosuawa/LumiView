"""WindowControls plugin — custom titlebar controls.

Injected scripts are generated in ``on_init`` with the commands' actual
full names (they follow the mount path, e.g. ``x.window.minimize`` when
constructed as ``WindowControls(name="x")``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lumiview._bridge import BridgeError
from lumiview._core import ResizeDirection
from lumiview._events import WindowHookEvent
from lumiview._scope import BridgeContext, InitContext, Scope

if TYPE_CHECKING:
    from lumiview._window import Window

API_SCRIPT_TEMPLATE = """\
(() => {
  const lumiview = window.lumiview || (window.lumiview = {});
  if (lumiview.window) return;
  lumiview.window = {
    minimize() { return lumiview.invoke("{{scope}}.minimize", {}); },
    toggleMaximize() { return lumiview.invoke("{{scope}}.toggle_maximize", {}); },
    isMaximized() { return lumiview.invoke("{{scope}}.is_maximized", {}); },
    close() { return lumiview.invoke("{{scope}}.close", {}); },
    onMaximizedChange(handler) {
      return lumiview.listen("{{scope}}.maximized-changed",
        (p) => handler(p.maximized));
    },
    startDragging() { return lumiview.invoke("{{scope}}.start_dragging", {}); },
    startResizeDragging(direction) {
      return lumiview.invoke("{{scope}}.start_resize_dragging", {direction});
    },
  };
})();
"""

FULLSCREEN_LINK_TEMPLATE = """\
(() => {
  document.addEventListener("fullscreenchange", () => {
    const fullscreen = !!document.fullscreenElement;
    lumiview.invoke("{{scope}}.sync_fullscreen", {fullscreen}).catch(() => {});
  });
})();
"""

# Declarative drag / resize regions — pattern from Tauri's drag.js:
DRAG_REGION_SCRIPT = """\
(() => {
  const CLICKABLE = "button, a, input, select, textarea, [role='button'], "
    + "[data-lumiview-no-drag]";
  document.addEventListener("mousedown", (event) => {
    if (event.button !== 0 || !(event.target instanceof Element)) return;

    const resizeRegion = event.target.closest(
      "[data-lumiview-resize-region]",
    );
    if (resizeRegion) {
      const direction = resizeRegion.getAttribute(
        "data-lumiview-resize-region",
      );
      if (direction) {
        event.preventDefault();
        void lumiview.window.startResizeDragging(direction).catch(() => {});
      }
      return;
    }

    const dragRegion = event.target.closest("[data-lumiview-drag-region]");
    if (!dragRegion) return;
    if (event.target.closest(CLICKABLE)) return;
    if (event.detail !== 1 && event.detail !== 2) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    // Second press of a double-click maximizes; otherwise start the
    // drag. detail=2 requires the presses to be close in time and
    // position, so a drag that actually moved the window still counts
    // as a plain drag.
    if (event.detail === 2) {
      void lumiview.window.toggleMaximize().catch(() => {});
    } else {
      void lumiview.window.startDragging().catch(() => {});
    }
  }, true);
})();
"""

_RESIZE_DIRECTIONS = {
    "east": ResizeDirection.East,
    "north": ResizeDirection.North,
    "north-east": ResizeDirection.NorthEast,
    "north-west": ResizeDirection.NorthWest,
    "south": ResizeDirection.South,
    "south-east": ResizeDirection.SouthEast,
    "south-west": ResizeDirection.SouthWest,
    "west": ResizeDirection.West,
}


class WindowControls(Scope):
    """Custom titlebar controls (window.* JS API + drag regions + fullscreen
    and maximize-state sync).

    All commands resolve their Task synchronously via ``.result()`` —
    they run on the thread pool, never on the GUI thread.
    """

    def __init__(
        self,
        *,
        name: str = "window",
        drag_regions: bool = True,
        link_fullscreen: bool = True,
        link_maximized: bool = True,
    ) -> None:
        super().__init__(name)
        self._drag_regions = drag_regions
        self._link_fullscreen = link_fullscreen
        self._link_maximized = link_maximized
        self._window: Window | None = None
        self._maximized = False
        self.command(self.minimize)
        self.command(self.toggle_maximize)
        self.command(self.is_maximized)
        self.command(self.close)
        self.command(self.start_dragging)
        self.command(self.start_resize_dragging)
        self.command(self.sync_fullscreen)

    # ── Lifecycle ───────────────────────────────────────────────────────

    def on_init(self, ctx: InitContext) -> InitContext:
        scope_path = self._full_name("")
        parts = [API_SCRIPT_TEMPLATE]
        if self._drag_regions:
            parts.append(DRAG_REGION_SCRIPT)
        if self._link_fullscreen:
            parts.append(FULLSCREEN_LINK_TEMPLATE)
        ctx.inject_script += "\n" + "\n".join(parts).replace("{{scope}}", scope_path)
        return ctx

    def on_ready(self, window: Window) -> None:
        if not self._link_maximized:
            return
        self._window = window
        self._maximized = window.is_maximized().result()
        self._emit_maximized()
        window.on(WindowHookEvent.Resized)(self._sync_maximized)

    async def _sync_maximized(self, *_: object) -> None:
        """Hook handler: broadcast maximize-state changes to JS."""
        if self._window is None:
            return
        maximized = await self._window.is_maximized()
        if maximized == self._maximized:
            return
        self._maximized = maximized
        self._emit_maximized()

    def _emit_maximized(self) -> None:
        """Fire the maximize-state event to JS listeners."""
        if self._window is None:
            return
        self._window.emit(
            f"{self._full_name('')}.maximized-changed",
            {"maximized": self._maximized},
        )

    # ── Commands ────────────────────────────────────────────────────────

    def minimize(self, ctx: BridgeContext) -> None:
        ctx.window.minimize().result()

    def toggle_maximize(self, ctx: BridgeContext) -> bool:
        return ctx.window.toggle_maximize().result()

    def is_maximized(self, ctx: BridgeContext) -> bool:
        return ctx.window.is_maximized().result()

    def close(self, ctx: BridgeContext) -> None:
        ctx.window.request_close().result()

    def start_dragging(self, ctx: BridgeContext) -> None:
        ctx.window.start_dragging().result()

    def start_resize_dragging(self, ctx: BridgeContext, direction: str) -> None:
        target = _RESIZE_DIRECTIONS.get(direction)
        if target is None:
            raise BridgeError(
                "invalid_argument",
                f"Unknown resize direction: {direction!r}",
            )
        ctx.window.start_resize_dragging(target).result()

    def sync_fullscreen(self, ctx: BridgeContext, fullscreen: bool) -> None:
        ctx.window.set_fullscreen(fullscreen).result()
