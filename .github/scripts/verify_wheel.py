#!/usr/bin/env python3
"""Check that a wheel build produced the expected tag and payload."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_wheel.py <expected-tag>", file=sys.stderr)
        return 2

    expected = sys.argv[1]
    wheels = sorted(Path("dist").glob("*.whl"))
    if len(wheels) != 1:
        print(
            f"expected exactly one wheel in dist/, got: {[w.name for w in wheels]}",
            file=sys.stderr,
        )
        return 1

    wheel = wheels[0]
    if f"-{expected}-" not in wheel.name:
        print(
            f"unexpected wheel tag: {wheel.name} (expected {expected})",
            file=sys.stderr,
        )
        return 1

    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()

    required = [
        "lumiview/__init__.py",
        "lumiview/py.typed",
        "lumiview/_core.pyi",
        "lumiview/_bridge_client.py",
    ]
    missing = [name for name in required if name not in names]
    if missing:
        print(f"missing from wheel: {missing}", file=sys.stderr)
        return 1

    has_native = any(
        name.startswith("lumiview/_core.") and name.endswith((".so", ".pyd"))
        for name in names
    )
    if not has_native:
        print("missing native extension lumiview/_core.*", file=sys.stderr)
        return 1

    print(f"ok: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
