# Contributing to LumiView

Thank you for your interest in contributing! LumiView is in early development, and we welcome feedback, bug reports, and thoughtful PRs.

**Before starting any significant work**, please open a [Discussion](https://github.com/xiaosuawa/LumiView/discussions) or [Issue](https://github.com/xiaosuawa/LumiView/issues) to align on the approach. Unsolicited PRs that touch the public API may not be merged if they conflict with the planned direction.

## Ways to Contribute

### 🐛 Bug Reports

- Check existing [Issues](https://github.com/xiaosuawa/LumiView/issues) first
- Include: OS + version, Python version, `lumiview` version, minimal repro code
- **Include logs**: run the repro with DEBUG logging enabled and paste
  the relevant output:

  ```python
  import logging

  logging.getLogger("lumiview").setLevel(logging.DEBUG)
  ```

  The `lumiview.*` log tree covers window / tray lifecycle and event
  dispatch — it usually pinpoints the issue faster than the repro alone.

### 💡 Feature Ideas

- Use [Discussions](https://github.com/xiaosuawa/LumiView/discussions) for brainstorming
- Tell us about your use case — it helps us prioritize

### 📖 Examples & Documentation

- Improvements to the [`examples/`](examples/) directory are always welcome
- Docstring improvements and typo fixes don't need prior discussion

### 🔧 Code Contributions

1. **Discuss first** — open an issue or discussion for anything beyond small fixes
2. **Follow existing patterns** — match the code style, type annotations, and docstring conventions
3. **Keep PRs focused** — one thing per PR

## Development Setup

```bash
# Clone and install dev dependencies
git clone https://github.com/xiaosuawa/LumiView.git
cd lumiview
pip install maturin

# The page-side JS client is generated (not committed) — Node 18+ required
npm --prefix js install
npm --prefix js run build

# Build and install in debug mode
maturin develop

# Run an example
python examples/hello_world.py
```

`npm --prefix js run build` writes `python/lumiview/_bridge_client.py` (git-ignored) and the npm package into `js/dist`. Re-run it after changing anything under `js/src`.

## Testing

```bash
python -m pytest -q                              # full suite (opens real windows)
python -m pytest tests/test_bridge_unit.py tests/test_events_unit.py \
    tests/test_public_api_unit.py tests/test_serve_unit.py \
    tests/test_task_unit.py tests/test_thread_safety_unit.py -q
npm --prefix js test                             # page-side client (Node)
```

`tests/test_*_unit.py` never creates a WebView. `tests/test_scenarios.py` runs
`tests/scenarios/<name>.py` in a child process and opens real windows, so it needs
WebView2 / WKWebView / WebKitGTK and a display (on Linux, run it under Xvfb).

## Documentation

User docs live in `docs/` — English `*.md` and Chinese `*.zh.md` side by side. Keep
both versions in sync, and add a [CHANGELOG.md](CHANGELOG.md) entry for every
user-visible change.

## Project Structure

```
src/              Rust bindings (PyO3 + tao + wryview)
python/lumiview/ Python layer (App, Window, Bridge, Task, serve)
js/               Page-side TypeScript client (injected + npm package)
docs/             User docs (English `*.md`, Chinese `*.zh.md`)
examples/         Runnable example scripts
```

## Code Style

- Python: follow existing type annotation patterns (all public APIs are typed)
- Rust: standard `cargo fmt` + `cargo clippy`
- Docstrings: Google-style for Python, `///` for Rust

## License

By contributing, you agree that your contributions will be licensed under the [MPL-2.0](LICENSE).
