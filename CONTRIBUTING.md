# Contributing to LumiView

Thank you for your interest in contributing! LumiView is in early development, and we welcome feedback, bug reports, and thoughtful PRs.

**Before starting any significant work**, please open a [Discussion](https://github.com/xiaosuawa/LumiView/discussions) or [Issue](https://github.com/xiaosuawa/LumiView/issues) to align on the approach. Unsolicited PRs that touch the public API may not be merged if they conflict with the planned direction.

## Ways to Contribute

### 🐛 Bug Reports

- Check existing [Issues](https://github.com/xiaosuawa/LumiView/issues) first.
- Include: OS + version, Python version, `lumiview` version, minimal repro code.
- **Include logs**: run the repro with DEBUG logging enabled and paste
  the relevant output:

  ```python
  import logging

  logging.getLogger("lumiview").setLevel(logging.DEBUG)
  ```

  The `lumiview.*` log tree covers window / tray lifecycle and event
  dispatch — it usually pinpoints the issue faster than the repro alone.

### 💡 Feature Ideas

- Use [Discussions](https://github.com/xiaosuawa/LumiView/discussions) for brainstorming.
- Tell us about your use case — it helps us prioritize.

### 📖 Examples & Documentation

- Improvements to the [`examples/`](examples/) directory are always welcome forever.
- Docstring improvements and typo fixes don't need prior discussion.

### 🔧 Code Contributions

1. **Discuss first** — open an issue or discussion for anything beyond small fixes.
2. **Follow existing patterns** — match the code style, type annotations, and docstring conventions.
3. **Keep PRs focused** — one thing per PR.

## Development Setup

```bash
# Clone and install dev dependencies
git clone https://github.com/xiaosuawa/LumiView.git
cd lumiview
pip install maturin

# Build and install in debug mode
maturin develop

# Run an example
python examples/hello_world.py
```

## Project Structure

```
src/              Rust bindings (PyO3 + tao + wryview)
python/lumiview/ Python layer (App, Window, Bridge, Task, serve)
examples/         Runnable example scripts
```

## Code Style

- Python: follow existing type annotation patterns (all public APIs are typed)
- Rust: standard `cargo fmt` + `cargo clippy`
- Docstrings: Google-style for Python, `///` for Rust

## License

By contributing, you agree that your contributions will be licensed under the [MPL-2.0](LICENSE).
