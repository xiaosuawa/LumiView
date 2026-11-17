#!/usr/bin/env python3
"""Check that the sdist contains the generated client and no build junk."""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path


def main() -> int:
    sdists = sorted(Path("dist").glob("*.tar.gz"))
    if len(sdists) != 1:
        print(
            f"expected exactly one sdist in dist/, got: {[s.name for s in sdists]}",
            file=sys.stderr,
        )
        return 1

    sdist = sdists[0]
    with tarfile.open(sdist) as archive:
        names = archive.getnames()

    prefix = names[0].split("/", 1)[0]
    required = [
        "pyproject.toml",
        "Cargo.toml",
        "Cargo.lock",
        "python/lumiview/__init__.py",
        "python/lumiview/py.typed",
        "python/lumiview/_core.pyi",
        "python/lumiview/_bridge_client.py",
    ]
    missing = [
        path for path in required if f"{prefix}/{path}" not in names
    ]
    if missing:
        print(f"missing from sdist: {missing}", file=sys.stderr)
        return 1

    forbidden = ("target/", "js/node_modules/", "dist/", ".git/")
    junk = [
        name
        for name in names
        if any(part in name for part in forbidden)
    ]
    if junk:
        print(f"unexpected paths in sdist: {junk[:10]}", file=sys.stderr)
        return 1

    print(f"ok: {sdist.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
