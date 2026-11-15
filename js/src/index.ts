/**
 * Typed entry point for the LumiView JS <-> Python bridge.
 *
 * ```ts
 * import { invoke, listen } from "lumiview";
 *
 * const unlisten = listen("greeter.changed", (payload) => console.log(payload));
 * const greeting = await invoke("greeter.greet", { name: "LumiView" });
 * ```
 *
 * Commands can be typed end-to-end by augmenting {@link Commands}:
 *
 * ```ts
 * declare module "lumiview" {
 *   interface Commands {
 *     "greeter.greet": { payload: { name?: string }; result: string };
 *   }
 * }
 * ```
 *
 * This module is a facade over ``window.__LUMIVIEW__`` — it never creates
 * a second client, so pending calls and listeners stay in one place.
 */

import type { BridgeErrorShape, LumiViewClient } from "./client";

export type { BridgeErrorShape, LumiViewClient } from "./client";

/** Command name -> payload/result shapes. Augment to type {@link invoke}. */
export interface Commands {}

/** Payload type for a command (``unknown`` when it is not declared). */
export type PayloadOf<C extends string> = C extends keyof Commands
  ? Commands[C] extends { payload: infer P }
    ? P
    : unknown
  : unknown;

/** Result type for a command (``unknown`` when it is not declared). */
export type ResultOf<C extends string> = C extends keyof Commands
  ? Commands[C] extends { result: infer R }
    ? R
    : unknown
  : unknown;

/** The installed client object (``window.__LUMIVIEW__``). */
export function getClient(): LumiViewClient {
  const client = (globalThis as { __LUMIVIEW__?: LumiViewClient }).__LUMIVIEW__;
  if (!client) {
    throw new Error(
      "LumiView bridge is unavailable: this page is not running inside a " +
        "LumiView window, or the window was created with WindowOptions(untrusted=True).",
    );
  }
  return client;
}

/** True when the page runs inside a LumiView window with a live bridge. */
export function isLumiView(): boolean {
  return typeof (globalThis as { __LUMIVIEW__?: unknown }).__LUMIVIEW__ === "object";
}

/** Wire protocol version reported by the injected client. */
export function protocol(): number {
  return getClient().v;
}

/** LumiView version that injected this client (e.g. ``"0.2.0rc1"``). */
export function build(): string {
  return getClient().build;
}

/**
 * Call a Python command.
 *
 * Declared commands get typed payloads and results through
 * {@link Commands}; undeclared ones accept anything and resolve to
 * ``unknown`` (use {@link invokeAs} to pin the result type).
 */
export function invoke<C extends string>(
  command: C,
  payload?: PayloadOf<C>,
): Promise<ResultOf<C>> {
  try {
    return getClient().invoke(command, payload);
  } catch (error) {
    // Missing client: reject like any other bridge failure instead of throwing
    // synchronously, so `invoke(...).catch(...)` keeps working.
    return Promise.reject(error);
  }
}

/** Call a Python command with an explicit result type (escape hatch). */
export function invokeAs<T = unknown>(
  command: string,
  payload?: unknown,
): Promise<T> {
  try {
    return getClient().invoke<T>(command, payload);
  } catch (error) {
    return Promise.reject(error);
  }
}

/** Fire-and-forget event to Python (surfaces as ``WindowEvent.JsEvent``). */
export function emit(event: string, payload?: unknown): void {
  getClient().emit(event, payload);
}

/**
 * Subscribe to events emitted from Python.
 *
 * Returns an unsubscribe function.
 */
export function listen(
  event: string,
  handler: (payload: any) => void,
  options?: boolean | AddEventListenerOptions,
): () => void {
  return getClient().listen(event, handler, options);
}

/** Narrow an unknown rejection value to a bridge error (``code``/``data``). */
export function isBridgeError(error: unknown): error is BridgeErrorShape {
  return (
    error instanceof Error && typeof (error as { code?: unknown }).code === "string"
  );
}
