/**
 * LumiView JS client — the page half of the JS <-> Python bridge.
 *
 * One implementation, two build targets (see ``scripts/build.mjs``):
 *
 * * ``inject.ts`` → an IIFE that installs ``window.__LUMIVIEW__`` at
 *   document start; this is what the Python runtime embeds and injects.
 * * ``index.ts`` → the npm entry point: a thin typed facade over the
 *   already-installed client (it never creates a second one, so pending
 *   calls and listeners cannot be split across two instances).
 *
 * Page -> Python goes through ``window.ipc.postMessage`` (wry's channel);
 * Python -> page arrives via ``eval_js`` calling ``dispatch()``.
 */

/** Wire protocol version — bump when the message shapes change. */
export const PROTOCOL = 1;

declare global {
  interface Window {
    /** Installed by the injected client (or by the page, in tests). */
    __LUMIVIEW__?: LumiViewClient;
    /** wry's IPC bridge; present while an IPC handler is attached. */
    ipc?: { postMessage(message: string): void };
  }
}

/** Shape of an error raised by a Python command (``BridgeError``). */
export interface BridgeErrorShape extends Error {
  readonly code: string;
  readonly data?: unknown;
}

/** JS-side representation of :class:`lumiview.bridge.BridgeError`. */
export class BridgeError extends Error implements BridgeErrorShape {
  readonly code: string;
  readonly data?: unknown;

  constructor(code: string, message: string, data?: unknown) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
    this.data = data;
  }
}

/** The object installed as ``window.__LUMIVIEW__``. */
export interface LumiViewClient {
  /** Wire protocol version. */
  readonly v: number;
  /** Version of the LumiView build this client came from (``"0.2.0rc1"``). */
  readonly build: string;
  /** Namespace container for injected plugin APIs (e.g. ``plugins.window``). */
  readonly plugins: Record<string, unknown>;
  /** Class used for rejected promises, so ``instanceof`` works in-page. */
  readonly BridgeError: typeof BridgeError;

  /** Call a Python command. */
  invoke<T = unknown>(command: string, payload?: unknown): Promise<T>;
  /** Fire-and-forget event to Python (surfaces as ``WindowEvent.JsEvent``). */
  emit(event: string, payload?: unknown): void;
  /** Subscribe to events emitted from Python; returns an unsubscribe function. */
  listen(
    event: string,
    handler: (payload: unknown) => void,
    options?: boolean | AddEventListenerOptions,
  ): () => void;

  addEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject | null,
    options?: boolean | AddEventListenerOptions,
  ): void;
  removeEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject | null,
    options?: boolean | EventListenerOptions,
  ): void;

  /** Python -> page entry point. Called by the runtime via ``eval_js``. */
  dispatch(message: unknown): void;
}

/** Make every own property of *target* read-only but keep it extensible. */
function lock<T extends object>(target: T): T {
  for (const key of Object.keys(target)) {
    const value = (target as Record<string, unknown>)[key];
    Object.defineProperty(target, key, {
      value,
      writable: false,
      enumerable: true,
      configurable: false,
    });
  }
  return target;
}

/** Create the client. Only ``inject.ts`` calls this. */
export function createClient(build: string): LumiViewClient {
  const bus = new EventTarget();
  const pending = new Map<
    string,
    { resolve: (value: unknown) => void; reject: (reason: unknown) => void }
  >();
  let sequence = 0;

  function post(message: Record<string, unknown>): void {
    const ipc = window.ipc;
    if (!ipc || typeof ipc.postMessage !== "function") {
      throw new Error(
        "LumiView: window.ipc is unavailable — is this page running inside a LumiView window?",
      );
    }
    ipc.postMessage(JSON.stringify(message));
  }

  function invoke<T = unknown>(command: string, payload: unknown = {}): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const id = String(++sequence);
      pending.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
      });
      try {
        post({ v: PROTOCOL, type: "invoke", id, command, payload });
      } catch (error) {
        pending.delete(id);
        reject(error);
      }
    });
  }

  function emit(event: string, payload: unknown = null): void {
    post({ v: PROTOCOL, type: "emit", event, payload });
  }

  function listen(
    event: string,
    handler: (payload: unknown) => void,
    options?: boolean | AddEventListenerOptions,
  ): () => void {
    const wrapped = (nativeEvent: Event): void => {
      try {
        handler((nativeEvent as CustomEvent).detail);
      } catch (error) {
        console.error(error);
      }
    };
    // removeEventListener only matches on `capture`.
    const capture =
      typeof options === "object" && options !== null
        ? Boolean(options.capture)
        : Boolean(options);
    bus.addEventListener(event, wrapped, options);
    return () => bus.removeEventListener(event, wrapped, capture);
  }

  function dispatch(message: unknown): void {
    if (typeof message !== "object" || message === null) return;
    const msg = message as Record<string, unknown>;
    const type = msg["type"];

    if (type === "event") {
      const name = msg["event"];
      if (typeof name !== "string" || !name) return;
      bus.dispatchEvent(new CustomEvent(name, { detail: msg["payload"] }));
      return;
    }
    if (type !== "resolve" && type !== "reject") return;

    const id = msg["id"];
    if (typeof id !== "string") return;
    const call = pending.get(id);
    if (!call) return;
    pending.delete(id);

    if (type === "reject") {
      const error = (msg["error"] ?? {}) as Record<string, unknown>;
      const code =
        typeof error["code"] === "string" ? error["code"] : "internal_error";
      const text =
        typeof error["message"] === "string" ? error["message"] : "Bridge call failed";
      call.reject(new BridgeError(code, text, error["data"]));
    } else {
      call.resolve(msg["value"]);
    }
  }

  return lock<LumiViewClient>({
    v: PROTOCOL,
    build,
    plugins: {},
    BridgeError,
    invoke,
    emit,
    listen,
    addEventListener: bus.addEventListener.bind(bus),
    removeEventListener: bus.removeEventListener.bind(bus),
    dispatch,
  });
}
