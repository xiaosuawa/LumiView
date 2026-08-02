from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterator, Sequence

if TYPE_CHECKING:
    from lumiview._window import Window

# ── BridgeError ────────────────────────────────────────────────────────────
# Defined here (the shared type module) to avoid an import cycle between
# _scope and _bridge: _bridge re-exports it for backward compatibility.


class BridgeError(Exception):
    """Structured error returned to JavaScript on bridge call failure.

    Parameters:
        code: Machine-readable error code (e.g. ``"invalid_argument"``).
        message: Human-readable description.
        data: Optional additional context (must be JSON-serializable).
    """

    def __init__(self, code: str, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data

    def to_dict(self) -> dict:
        result: dict = {"code": self.code, "message": str(self)}
        if self.data is not None:
            result["data"] = self.data
        return result


# ── Pattern matching (shared with lumiview.utils) ──────────────────────────


def pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a ``*`` glob pattern to a compiled regex.

    ``*`` matches any sequence (including ``/``, ``.``, ``?``); every
    other character matches literally.
    """
    parts = pattern.split("*")
    source = "^" + re.escape(parts[0])
    for part in parts[1:]:
        source += ".*" + re.escape(part)
    source += "$"
    return re.compile(source)


def match_pattern(pattern: str, value: str) -> bool:
    """Match *value* against a ``*`` glob pattern."""
    return pattern_to_regex(pattern).match(value) is not None


# ── Permissions ────────────────────────────────────────────────────────────


@dataclass
class ScopePermission:
    """Allow/deny pattern lists for one scope node.

    Empty by default (no rules configured).  ``check`` semantics:
    deny wins; an empty allow list means "no whitelist restriction"
    (deny-only blacklist).  On the permission chain, unconfigured
    nodes are skipped; if NO node on the chain has any rule, the
    command is rejected by default (see ``check_chain``).  The Bridge
    root is initialized with ``allow=("*",)`` unless overridden.
    """

    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()

    def check(self, rel_path: str) -> bool:
        """Check a path relative to this scope node."""
        for pattern in self.deny:
            if match_pattern(pattern, rel_path):
                return False
        if not self.allow:
            return True
        return any(match_pattern(p, rel_path) for p in self.allow)


# ── Command ────────────────────────────────────────────────────────────────


@dataclass
class Command:
    """A registered command bound to its registration node."""

    fn: Callable[..., Any]
    name: str
    scope: "Scope"
    strict: bool = True

    @property
    def full_name(self) -> str:
        return self.scope._full_name(self.name)


# ── Context types ──────────────────────────────────────────────────────────


@dataclass
class BridgeContext:
    """System-injected parameter — see ``_binding.INJECTED_TYPES``.

    Fields:
        window: The Window that made this call.
        payload: The raw payload (when no regular parameters exist).
        command: The full command name.
        scope: The scope node the command is registered on.
    """

    window: "Window"
    payload: Any
    command: str
    scope: "Scope"


@dataclass
class InitContext:
    """Context threaded through the on_init chain at window creation."""

    inject_script: str = ""


# ── Scope ──────────────────────────────────────────────────────────────────


class Scope:
    """A node in the command tree (intermediate or leaf).

    Convenience constructor arguments (equivalent to calling the methods
    after creation)::

        fs = Scope("fs", includes=[read_scope], permissions=ScopePermission(allow=("read.*",)))
    """

    def __init__(
        self,
        name: str = "",
        *,
        includes: Sequence[Scope] = (),
        permissions: ScopePermission | None = None,
    ) -> None:
        self._name = name
        self._parent: Scope | None = None
        self._children: dict[str, Scope] = {}
        self._commands: dict[str, Command] = {}
        self._permissions = (
            permissions if permissions is not None else ScopePermission()
        )
        for scope in includes:
            self.include(scope)

    # ── Naming ──────────────────────────────────────────────────────────

    def _full_name(self, local: str) -> str:
        parts: list[str] = []
        node: Scope | None = self
        while node is not None:
            if node._name:
                parts.append(node._name)
            node = node._parent
        parts.reverse()
        if local:
            parts.append(local)
        return ".".join(parts)

    @property
    def _depth(self) -> int:
        depth = 0
        node = self._parent
        while node is not None:
            depth += 1
            node = node._parent
        return depth

    # ── Tree building ───────────────────────────────────────────────────

    def scope(self, name: str) -> Scope:
        """Get or create a child scope (returns the existing node)."""
        if name in self._children:
            return self._children[name]
        child = Scope(name)
        child._parent = self
        self._children[name] = child
        return child

    def command(
        self,
        fn: Callable[..., Any] | None = None,
        /,
        *,
        name: str | None = None,
        replace: bool = False,
        strict: bool = True,
    ) -> Callable[..., Any]:
        """Register a command — decorator or direct call.

        ``@scope.command`` / ``@scope.command(name=...)`` /
        ``scope.command(fn)`` all work; inside ``Scope.__init__`` use
        ``self.command(self.minimize)``.
        """
        if fn is None:

            def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
                self._register(f, name=name, replace=replace, strict=strict)
                return f

            return decorator
        self._register(fn, name=name, replace=replace, strict=strict)
        return fn

    def _register(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None,
        replace: bool,
        strict: bool,
    ) -> None:
        sig = inspect.signature(fn)
        for p in sig.parameters.values():
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                raise ValueError(
                    f"Command {fn.__name__!r} cannot use *args or **kwargs"
                )
        local = name or fn.__name__
        if "." in local:
            raise ValueError(f"Command name {local!r} must not contain '.'")
        if local in self._commands and not replace:
            raise ValueError(
                f"Command {local!r} already registered in scope "
                f"{self._full_name('')!r}. Use replace=True to overwrite."
            )
        self._commands[local] = Command(
            fn=fn, name=local, scope=self, strict=strict
        )

    def include(self, other: Scope) -> None:
        """Mount another scope onto this tree — pure mounting, no copying,
        no merging, never mutates *other* (names and permissions are
        relative paths, so the subtree is untouched).

        An instance can be mounted exactly once — re-mounting it would
        rewrite its parent pointer and silently change the permission
        chain of the tree it already belongs to.  Custom mount names are
        set at construction (``Scope(name=...)``); ``include()`` has no
        prefix argument.  Unnamed scopes cannot be mounted (ValueError).
        """
        if not isinstance(other, Scope):
            raise TypeError(
                f"include() expects a Scope instance, got {type(other).__name__}"
            )
        if not other._name:
            raise ValueError("include() requires a named scope")
        if other._parent is not None:
            raise ValueError(
                f"Scope {other._name!r} is already mounted elsewhere — "
                "mounting the same instance twice is not allowed"
            )
        node: Scope | None = self
        while node is not None:
            if node is other:
                raise ValueError(
                    f"Cannot mount {other._name!r} under its own subtree"
                )
            node = node._parent
        if other._name in self._children:
            raise ValueError(
                f"A scope named {other._name!r} is already mounted here"
            )
        other._parent = self
        self._children[other._name] = other

    # ── Permissions ─────────────────────────────────────────────────────

    def allow(self, *patterns: str) -> None:
        """Append allow rules (paths relative to this scope)."""
        self._permissions.allow = self._permissions.allow + tuple(patterns)

    def deny(self, *patterns: str) -> None:
        """Append deny rules (paths relative to this scope)."""
        self._permissions.deny = self._permissions.deny + tuple(patterns)

    @property
    def permissions(self) -> ScopePermission:
        return self._permissions

    @permissions.setter
    def permissions(self, value: ScopePermission) -> None:
        self._permissions = value

    def check_permission(self, rel_path: str) -> bool:
        """Check a path relative to THIS scope node."""
        return self._permissions.check(rel_path)

    # ── Events ──────────────────────────────────────────────────────────

    def emit(
        self,
        event: str,
        payload: Any = None,
        *,
        window: "Window | None" = None,
    ) -> None:
        """Emit an event with this scope's namespace prefix.

        Requires ``window=`` (the target window).  Inside commands:
        ``ctx.scope.emit("changed", {...}, window=ctx.window)``.
        """
        if window is None:
            raise RuntimeError("scope.emit() requires window=...")
        prefix = self._full_name("")
        full = f"{prefix}.{event}" if prefix else event
        window.emit(full, payload)

    # ── Lookup ──────────────────────────────────────────────────────────

    def lookup(self, full_name: str) -> Command | None:
        """Resolve a full command name by walking the tree."""
        parts = full_name.split(".")
        node = self
        for part in parts[:-1]:
            child = node._children.get(part)
            if child is None:
                return
            node = child
        return node._commands.get(parts[-1])


# ── Module helpers ─────────────────────────────────────────────────────────


def check_chain(scope: Scope, full_name: str) -> bool:
    """Walk from the command's registration node up to the tree root.

    Each layer checks the path relative to itself, so rule semantics
    don't drift when a subtree is re-mounted (``include``).  Layers
    without any rules are skipped; if NO layer has any rule, the
    command is rejected by default (safe default — an unconfigured
    chain must not accidentally allow everything).
    """
    parts = full_name.split(".")
    node: Scope | None = scope
    configured = False
    while node is not None:
        perms = node._permissions
        if perms.allow or perms.deny:
            configured = True
            rel = ".".join(parts[node._depth:])
            if not perms.check(rel):
                return False
        node = node._parent
    return configured


def iter_tree(root: Scope) -> Iterator[Scope]:
    """Depth-first pre-order walk, deduplicated by object identity."""

    def walk(node: Scope) -> Iterator[Scope]:
        seen.add(id(node))
        yield node
        for child in node._children.values():
            if id(child) not in seen:
                yield from walk(child)

    seen: set[int] = set()
    yield from walk(root)
