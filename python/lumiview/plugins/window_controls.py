"""WindowControls plugin — custom titlebar controls.

Injected scripts are generated in ``on_init`` with the commands' actual full
names (they follow the mount path, e.g. ``x.titlebar.minimize`` when constructed
as ``WindowControls(name="x.titlebar")``). The JS API lands under
``window.__LUMIVIEW__.plugins.<last mount segment>``, so several instances can
coexist on one page.
"""

from __future__ import annotations

import weakref

from lumiview.bridge import BridgeError
from lumiview._core import ResizeDirection
from lumiview.events import WindowBaseEvent, WindowEvent
from lumiview.scope import BridgeContext, InitContext, Plugin
from lumiview.window import Window

API_SCRIPT_TEMPLATE = """\
(() => {
  const client = window.__LUMIVIEW__;
  if (!client) return;
  const plugins = client.plugins;
  if (plugins["{{ns}}"]) {
    console.warn("[lumiview] WindowControls namespace '{{ns}}' is already in use");
    return;
  }
  plugins["{{ns}}"] = {
    minimize() { return client.invoke("{{scope}}.minimize", {}); },
    toggleMaximize() { return client.invoke("{{scope}}.toggle_maximize", {}); },
    isMaximized() { return client.invoke("{{scope}}.is_maximized", {}); },
    close() { return client.invoke("{{scope}}.close", {}); },
    onMaximizedChange(handler) {
      return client.listen("{{scope}}.maximized-changed",
        (p) => handler(p.maximized));
    },
    startDragging() { return client.invoke("{{scope}}.start_dragging", {}); },
    startResizeDragging(direction) {
      return client.invoke("{{scope}}.start_resize_dragging", {direction});
    },
  };
})();
"""

# Per-page install markers live on the client as symbols: `Symbol.for` is
# process-wide, so a second evaluation of the same script is a no-op, while
# `Object.keys(window.__LUMIVIEW__)` stays free of implementation details.
FULLSCREEN_LINK_TEMPLATE = """\
(() => {
  const client = window.__LUMIVIEW__;
  const INSTALLED = Symbol.for("lumiview.fullscreenLink");
  if (!client || client[INSTALLED]) return;
  client[INSTALLED] = true;
  document.addEventListener("fullscreenchange", () => {
    const fullscreen = !!document.fullscreenElement;
    client
      .invoke("{{scope}}.sync_fullscreen", {fullscreen})
      .catch(() => {});
  });
})();
"""

# Declarative drag / resize regions — pattern from Tauri's drag.js:
DRAG_REGION_SCRIPT = """\
(() => {
  const CLICKABLE = "button, a, input, select, textarea, [role='button'], "
    + "[data-lumiview-no-drag]";
  const client = window.__LUMIVIEW__;
  const INSTALLED = Symbol.for("lumiview.dragRegions");
  if (!client || client[INSTALLED]) return;
  client[INSTALLED] = true;
  const controls = () => client.plugins["{{ns}}"];
  document.addEventListener("mousedown", (event) => {
    if (event.button !== 0 || !(event.target instanceof Element)) return;
    const windowControls = controls();
    if (!windowControls) return;

    const resizeRegion = event.target.closest(
      "[data-lumiview-resize-region]",
    );
    if (resizeRegion) {
      const direction = resizeRegion.getAttribute(
        "data-lumiview-resize-region",
      );
      if (direction) {
        event.preventDefault();
        void windowControls.startResizeDragging(direction).catch(() => {});
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
      void windowControls.toggleMaximize().catch(() => {});
    } else {
      void windowControls.startDragging().catch(() => {});
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


class WindowControls(Plugin):
    """Custom titlebar controls for undecorated windows.

    Provides two things:

    * ``window.__LUMIVIEW__.plugins.<name>`` — the JS API (``minimize``,
      ``toggleMaximize``, ``isMaximized``, ``close``, ``startDragging``,
      ``startResizeDragging``, ``onMaximizedChange``);
    * ``data-lumiview-drag-region`` / ``data-lumiview-resize-region`` markup
      plus fullscreen and maximize-state syncing.

    ``name`` is the mount path for the commands; the JS namespace is its last
    segment (``WindowControls(name="titlebar")`` →
    ``__LUMIVIEW__.plugins.titlebar`` and ``titlebar.minimize``).

    NOTE: window-edge resizing needs no markup — for undecorated windows tao
    already handles the 8 edge/corner hit-tests natively (WM_NCHITTEST) and
    disables them when maximized/fullscreen. Use data-lumiview-resize-region
    only for resize handles *inside* the client area (e.g. a splitter bar);
    do not cover the window border with it.
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
        # Per-window state: one plugin instance may serve several windows
        # (a Bridge can be shared), so window state must never live on self —
        # the last window's values would silently overwrite the others'.
        self._maximized: weakref.WeakKeyDictionary[Window, bool] = (
            weakref.WeakKeyDictionary()
        )
        self.command(self.minimize)
        self.command(self.toggle_maximize)
        self.command(self.is_maximized)
        self.command(self.close)
        self.command(self.start_dragging)
        self.command(self.start_resize_dragging)
        self.command(self.sync_fullscreen)

    @property
    def namespace(self) -> str:
        """Key under ``__LUMIVIEW__.plugins`` (last segment of the mount path)."""

        return self._full_name("").split(".")[-1]

    # Lifecycle

    def on_init(self, ctx: InitContext) -> InitContext:
        scope_path = self._full_name("")
        parts = [API_SCRIPT_TEMPLATE]
        if self._drag_regions:
            parts.append(DRAG_REGION_SCRIPT)
        if self._link_fullscreen:
            parts.append(FULLSCREEN_LINK_TEMPLATE)
        script = "\n".join(parts)
        script = script.replace("{{scope}}", scope_path).replace(
            "{{ns}}", self.namespace
        )
        ctx.inject_script += "\n" + script
        return ctx

    def on_ready(self, window: Window) -> None:
        if not self._link_maximized:
            return
        self._maximized[window] = window.is_maximized().result()
        self._emit_maximized(window)
        window.on(WindowEvent.ResizedEvent)(self._sync_maximized)

    async def _sync_maximized(self, evt: WindowBaseEvent) -> None:
        """Hook handler: broadcast maximize-state changes to JS."""
        window = evt.window
        if window is None:
            return
        maximized = await window.is_maximized()
        if maximized == self._maximized.get(window):
            return
        self._maximized[window] = maximized
        self._emit_maximized(window)

    def _emit_maximized(self, window: Window) -> None:
        """Fire the maximize-state event to JS listeners."""
        window.emit(
            f"{self._full_name('')}.maximized-changed",
            {"maximized": self._maximized.get(window, False)},
        )

    # Commands (called from JS via the bridge)
    async def minimize(self, ctx: BridgeContext) -> None:
        """Minimize the window."""

        await ctx.window.set_minimized(True)

    async def toggle_maximize(self, ctx: BridgeContext) -> bool:
        """Toggle maximize state; returns True if now maximized."""

        return await ctx.window.toggle_maximize()

    async def is_maximized(self, ctx: BridgeContext) -> bool:
        """True if the window is maximized."""

        return await ctx.window.is_maximized()

    async def close(self, ctx: BridgeContext) -> None:
        """Apply the window's close behavior (request_close)."""

        await ctx.window.request_close()

    async def start_dragging(self, ctx: BridgeContext) -> None:
        """Start an OS-level window drag."""

        await ctx.window.start_dragging()

    async def start_resize_dragging(self, ctx: BridgeContext, direction: str) -> None:
        """Start an OS-level resize drag.

        Parameters:
            direction: One of ``"north"``, ``"south"``, ``"east"``,
                ``"west"`` and their diagonal combinations.
        """

        target = _RESIZE_DIRECTIONS.get(direction)
        if target is None:
            raise BridgeError(
                "invalid_argument",
                f"Unknown resize direction: {direction!r}",
            )
        await ctx.window.start_resize_dragging(target)

    async def sync_fullscreen(self, ctx: BridgeContext, fullscreen: bool) -> None:
        """Sync the window's fullscreen state to the OS."""

        await ctx.window.set_fullscreen(fullscreen)
