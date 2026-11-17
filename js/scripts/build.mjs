/**
 * Build the JS artifacts.
 *
 * Outputs (all git-ignored):
 *
 * * ``dist/index.mjs`` / ``dist/index.cjs`` / ``dist/index.d.ts`` — npm package
 * * ``../python/lumiview/_bridge_client.py`` — injected client, embedded in the
 *   wheel (see ``lumiview.bridge.client_script``)
 *
 * The injected script is deliberately **not** minified: it is small, and
 * readable output makes `__LUMIVIEW__` in devtools debuggable.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = path.resolve(root, "..");
const dist = path.join(root, "dist");

const pkg = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));
const version = pkg.version;

const pyproject = readFileSync(path.join(repo, "pyproject.toml"), "utf8");
const pyVersion = /^version\s*=\s*"(.+?)"/m.exec(pyproject)?.[1];

// Start from a clean slate: a stale `dist` (e.g. from a different compiler
// version) must not leak into the npm package.
rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });

// 1. Injected IIFE -> Python module.
const injected = await build({
  entryPoints: [path.join(root, "src/inject.ts")],
  bundle: true,
  format: "iife",
  target: "es2020",
  platform: "browser",
  minify: false,
  charset: "utf8",
  legalComments: "none",
  define: { __LV_VERSION__: JSON.stringify(pyVersion) },
  write: false,
});
const script = injected.outputFiles[0].text.trimEnd();

if (script.includes('"""') || script.endsWith("\\")) {
  throw new Error("Injected JS cannot be embedded in a raw Python string as-is");
}

const generated = `"""Injected JS client for the LumiView bridge (generated).

Build with "npm --prefix js run build" — do not edit by hand.
"""

CLIENT_SCRIPT = r"""${script}
"""
`;
const target = path.join(repo, "python", "lumiview", "_bridge_client.py");
writeFileSync(target, generated, "utf8");

// Keep a readable copy around for debugging / the JS test suite.
writeFileSync(path.join(dist, "inject.iife.js"), script + "\n", "utf8");

// 2. npm package (ESM + CJS), one bundle per entry point.
const entries = ["index", "window-controls"];
for (const entry of entries) {
  for (const format of ["esm", "cjs"]) {
    await build({
      entryPoints: [path.join(root, `src/${entry}.ts`)],
      bundle: true,
      format,
      target: "es2020",
      platform: "neutral",
      minify: false,
      charset: "utf8",
      legalComments: "none",
      outfile: path.join(dist, `${entry}.${format === "esm" ? "mjs" : "cjs"}`),
    });
  }
}

// 3. Type declarations (tsc emits `inject.d.ts` too — drop it).
execFileSync(
  process.execPath,
  [
    path.join(root, "node_modules", "typescript", "bin", "tsc"),
    "-p",
    path.join(root, "tsconfig.json"),
  ],
  { stdio: "inherit" },
);
rmSync(path.join(dist, "inject.d.ts"), { force: true });

console.log(
  `built lumiview ${pyVersion} (npm ${version}): dist/{index,window-controls}.{mjs,cjs,d.ts} + python/lumiview/_bridge_client.py (${script.length} bytes)`,
);
