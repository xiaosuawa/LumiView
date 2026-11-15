/**
 * Injected entry point — installed at document start, before any page
 * script runs. Build output is embedded into the Python wheel as
 * ``lumiview/_bridge_client.py``.
 */

import { createClient } from "./client";

declare const __LV_VERSION__: string;

if (!window.__LUMIVIEW__) {
  Object.defineProperty(window, "__LUMIVIEW__", {
    value: createClient(__LV_VERSION__),
    writable: false,
    enumerable: false, // keeps `Object.keys(window)` clean
    configurable: false,
  });
}
