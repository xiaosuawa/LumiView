/**
 * Typed client for the first-party `WindowControls` plugin.
 *
 * ```ts
 * import { windowControls } from "lumiview/window-controls";
 *
 * const wc = windowControls();          // default scope: "window"
 * await wc.minimize();
 * const unlisten = wc.onMaximizedChange((maximized) => console.log(maximized));
 * ```
 *
 * This module calls the plugin's commands directly — it does not depend on the
 * injected `window.__LUMIVIEW__.plugins.<name>` wrapper, so it works for bundled
 * frontends regardless of how the plugin is mounted.
 */

import { invokeAs, listen } from "./index";

/** Directions accepted by {@link WindowControlsApi.startResizeDragging}. */
export type ResizeDirection =
  | "east"
  | "north"
  | "north-east"
  | "north-west"
  | "south"
  | "south-east"
  | "south-west"
  | "west";

/** Page-side API exposed by the `WindowControls` plugin. */
export interface WindowControlsApi {
  /** Minimize the window. */
  minimize(): Promise<void>;
  /** Toggle maximized state; resolves `true` when now maximized. */
  toggleMaximize(): Promise<boolean>;
  /** Whether the window is maximized. */
  isMaximized(): Promise<boolean>;
  /** Apply the window's configured close behaviour. */
  close(): Promise<void>;
  /** Start an OS-level window drag (for custom titlebars). */
  startDragging(): Promise<void>;
  /** Start an OS-level resize drag. */
  startResizeDragging(direction: ResizeDirection): Promise<void>;
  /** Subscribe to maximize-state changes; returns an unsubscribe function. */
  onMaximizedChange(handler: (maximized: boolean) => void): () => void;
}

/**
 * Build the typed API for a mounted `WindowControls` plugin.
 *
 * *scope* is the plugin's mount path, matching
 * ``WindowControls(name=...)``; the default matches ``WindowControls()``.
 */
export function windowControls(scope = "window"): WindowControlsApi {
  const call = <T>(command: string, payload: unknown = {}): Promise<T> =>
    invokeAs<T>(`${scope}.${command}`, payload);

  return {
    minimize: () => call<void>("minimize"),
    toggleMaximize: () => call<boolean>("toggle_maximize"),
    isMaximized: () => call<boolean>("is_maximized"),
    close: () => call<void>("close"),
    startDragging: () => call<void>("start_dragging"),
    startResizeDragging: (direction) =>
      call<void>("start_resize_dragging", { direction }),
    onMaximizedChange(handler) {
      return listen(`${scope}.maximized-changed`, (payload) => {
        const value = (payload as { maximized?: unknown } | null)?.maximized;
        handler(Boolean(value));
      });
    },
  };
}

// Type the plugin's commands for the default mount so `invoke("window.minimize")`
// (or a future generic helper) is checked. Custom mounts fall back to `unknown`.
declare module "./index" {
  interface Commands {
    "window.minimize": { result: void };
    "window.toggle_maximize": { result: boolean };
    "window.is_maximized": { result: boolean };
    "window.close": { result: void };
    "window.start_dragging": { result: void };
    "window.start_resize_dragging": {
      payload: { direction: ResizeDirection };
      result: void;
    };
  }
}
