#!/usr/bin/env python3
"""Check that every version stamp agrees, and optionally that it matches a tag.

PEP 440 (pyproject.toml, __init__.py) and semver (Cargo.toml, package.json)
spell prereleases differently: ``0.2.0rc1`` vs ``0.2.0-rc.1``. Compare the
normalized forms, never the raw strings.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


def normalize(value: str) -> str:
    value = value.strip()
    if value.startswith("v"):
        value = value[1:]
    value = value.replace("-rc.", "rc")
    value = value.replace("-alpha.", "a")
    value = value.replace("-beta.", "b")
    value = value.replace("-dev.", ".dev")
    return value


def pyproject_version() -> str:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def cargo_version() -> str:
    data = tomllib.loads(Path("Cargo.toml").read_text(encoding="utf-8"))
    return data["package"]["version"]


def js_version() -> str:
    data = json.loads(Path("js/package.json").read_text(encoding="utf-8"))
    return data["version"]


def init_version() -> str:
    text = Path("python/lumiview/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("__version__ not found in python/lumiview/__init__.py")
    return match.group(1)


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else None

    versions = {
        "pyproject.toml": pyproject_version(),
        "Cargo.toml": cargo_version(),
        "js/package.json": js_version(),
        "python/lumiview/__init__.py": init_version(),
    }
    normalized = {name: normalize(value) for name, value in versions.items()}

    if len(set(normalized.values())) != 1:
        for name, value in normalized.items():
            print(f"{name}: {value}", file=sys.stderr)
        print("version mismatch", file=sys.stderr)
        return 1

    current = normalized["pyproject.toml"]
    if tag is not None and normalize(tag) != current:
        print(
            f"tag {tag!r} does not match version {current!r}",
            file=sys.stderr,
        )
        return 1

    print(f"versions agree: {current}" + (f" (tag {tag})" if tag else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
