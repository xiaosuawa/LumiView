from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _dump_child_output(label: str, data: str | bytes | None, *, tail: int = 150) -> None:
    """Print the tail of a child's captured stream so a CI failure shows the
    step the scenario actually reached."""

    if not data:
        return
    text = data if isinstance(data, str) else data.decode("utf-8", "replace")
    lines = text.splitlines()
    if len(lines) > tail:
        omitted = len(lines) - tail
        lines = [f"... ({omitted} earlier line(s) omitted) ..."] + lines[-tail:]
    print(f"--- {label} ---", file=sys.stderr)
    print("\n".join(lines), file=sys.stderr)


def run_scenario(
    name: str,
    *,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> int:
    """Run ``tests/scenarios/<name>.py`` as a child process.

    Returns the child's exit code. The child reuses ``sys.executable`` (so
    it imports the *installed* ``lumiview``) with cwd pinned to the repo
    root. On failure or timeout the tail of the child's stdout/stderr is
    printed, so the scenario's last step is visible in CI. A timeout yields
    ``exit_code == -1`` with a ``[TEST TIMEOUT]`` marker.

    The budget is generous because CI runners without a GPU can take tens of
    seconds per WebView2/WebKitGTK instance; it is a hang detector, not a
    performance assertion.
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
            capture_output=True,
        )
    except subprocess.TimeoutExpired as exc:
        print(f"[TEST TIMEOUT] {name} (timeout={timeout}s)", file=sys.stderr)
        _dump_child_output("child stdout", exc.stdout)
        _dump_child_output("child stderr", exc.stderr)
        return -1

    if proc.returncode != 0:
        _dump_child_output("child stdout", proc.stdout)
        _dump_child_output("child stderr", proc.stderr)
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
    # Four adapters, one window each. WebKitGTK on the Linux CI runner
    # (software rendering under Xvfb) needs well over the default budget
    # for four sequential WebView instances.
    code = run_scenario("serve_all", timeout=180)
    assert code == 0


def test_emit_listen():
    code = run_scenario("emit_listen")
    assert code == 0


def test_bridge_swap():
    code = run_scenario("bridge_swap")
    assert code == 0
