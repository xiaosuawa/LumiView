from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_scenario(
    name: str,
    *,
    env: dict[str, str] | None = None,
    timeout: int = 45,
) -> int:
    """Run ``tests/scenarios/<name>.py`` as a child process.

    Returns ``(exit_code, stdout, stderr)``.

    The child reuses ``sys.executable`` (so it imports the *installed*
    ``lumiview`` from ``maturin develop``) with cwd pinned to the repo root.
    A timeout yields ``exit_code == -1`` with a ``[TEST TIMEOUT]`` marker
    appended to stderr, so "stuck" (GUI thread deadlock / WebView2 renderer
    hang) is distinguishable from a plain failure.
    """
    script = ROOT / "tests" / "scenarios" / f"{name}.py"
    if not script.exists():
        raise FileNotFoundError(f"Scenario script missing: {script}")

    full_env = os.environ.copy()
    full_env.update(env or {})

    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            env=full_env,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"[TEST TIMEOUT] {name} (timeout={timeout}s)", file=sys.stderr)
        return -1

    return proc.returncode


def test_app_import_singleton():
    code = run_scenario("app_import_singleton")
    assert code == 0


def test_run_once_exit_code():
    code = run_scenario("run_once_exit_code")
    assert code == 0


def test_ready_before_entry():
    code = run_scenario("ready_before_entry")
    assert code == 0


def test_app_wait_for():
    code = run_scenario("app_wait_for")
    assert code == 0


def test_window_waiter_on_shutdown():
    code = run_scenario("window_waiter_on_shutdown")
    assert code == 0


def test_window_close_waiter():
    code = run_scenario("window_close_waiter")
    assert code == 0


def test_entry_raises_exit1():
    code = run_scenario("entry_raises_exit1")
    assert code == 1


def test_window_html_eval_js():
    code = run_scenario("window_html_eval_js")
    assert code == 0


def test_ipc_roundtrip_permission():
    code = run_scenario("ipc_roundtrip_permission")
    assert code == 0


def test_untrusted_and_raw_message():
    code = run_scenario("untrusted_and_raw_message")
    assert code == 0


def test_multi_window():
    code = run_scenario("multi_window")
    assert code == 0


def test_serve_adapters():
    code = run_scenario("serve_all")
    assert code == 0


def test_emit_listen():
    code = run_scenario("emit_listen")
    assert code == 0


def test_bridge_swap():
    code = run_scenario("bridge_swap")
    assert code == 0
