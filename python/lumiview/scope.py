from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterator,
    Sequence,
    TypeVar,
    get_type_hints,
    overload,
)

if TYPE_CHECKING:
    from lumiview.window import Window
    from lumiview.window import WindowOptions

from lumiview._utils import match_pattern

_F = TypeVar("_F", bound=Callable[..., Any])

@dataclass
class ScopePermission:
    """Allow/deny pattern lists for one scope node.

    Deny wins; an empty allow list means deny-only. A chain with no rules at all
    rejects by default (the Bridge root starts with ``allow=("*",)``).
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


@dataclass
class Command:
    """A registered command bound to its registration node."""

    fn: Callable
    name: str
    scope: "Scope"
    strict: bool = True

    # Cached at registration so bind_arguments does no per-call introspection.
    signature: inspect.Signature | None = field(
        default=None, init=False, repr=False, compare=False
    )
    type_hints: dict[str, Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    @property
    def full_name(self) -> str:
        return self.scope._full_name(self.name)


@dataclass
class BridgeContext:
    """System-injected call context (``window``, ``payload``, ``command``, ``scope``)."""

    window: "Window"
    payload: Any
    command: str
    scope: "Scope"


@dataclass
class InitContext:
    """Context passed to :meth:`Plugin.on_init`.

    ``options`` is still being applied, so hooks registered here see early events.
    """

    inject_script: str = ""
    window: Window | None = None
    options: WindowOptions | None = None


class Scope:
    """A node in the command tree (intermediate or leaf)."""

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

    def scope(self, name: str) -> Scope:
        """Get or create a child scope (returns the existing node)."""
        if name in self._children:
            return self._children[name]
        child = Scope(name)
        child._parent = self
        self._children[name] = child
        return child

    @overload
    def command(
        self,
        fn: _F,
        /,
        *,
        name: str | None = None,
        replace: bool = False,
        strict: bool = True,
    ) -> _F: ...

    @overload
    def command(
        self,
        fn: None = None,
        /,
        *,
        name: str | None = None,
        replace: bool = False,
        strict: bool = True,
    ) -> Callable[[_F], _F]: ...

    def command(
        self,
        fn: Callable[..., Any] | None = None,
        /,
        *,
        name: str | None = None,
        replace: bool = False,
        strict: bool = True,
    ) -> Callable[..., Any]:
        """Register a command (decorator or direct call).

        ``replace`` allows overwriting a name; ``strict`` rejects unexpected payload keys.
        """
        if fn is None:

            def decorator(f: _F) -> _F:
                self._register(f, name=name, replace=replace, strict=strict)
                return f

            return decorator
        self._register(fn, name=name, replace=replace, strict=strict)
        return fn

    def _register(
        self,
        fn: Callable,
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
        if local in self._commands and not replace:
            raise ValueError(
                f"Command {local!r} already registered in scope "
                f"{self._full_name('')!r}. Use replace=True to overwrite."
            )
        # Cache once; None means "retry at IPC time" (forward refs).
        try:
            type_hints = get_type_hints(fn)
        except (NameError, TypeError):
            type_hints = None
        cmd = Command(fn=fn, name=local, scope=self, strict=strict)
        # init=False fields — assign after construction.
        cmd.signature = sig
        cmd.type_hints = type_hints
        self._commands[local] = cmd

    def include(self, other: Scope) -> None:
        """Mount another scope (pure mounting — names and permissions stay relative).

        An instance can be mounted once; unnamed scopes raise ``ValueError``.
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
                raise ValueError(f"Cannot mount {other._name!r} under its own subtree")
            node = node._parent
        if other._name in self._children:
            raise ValueError(f"A scope named {other._name!r} is already mounted here")
        other._parent = self
        self._children[other._name] = other

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

    def emit(
        self,
        event: str,
        payload: Any = None,
        *,
        window: "Window | None" = None,
    ) -> None:
        """Emit an event with this scope's namespace prefix (``window=`` required)."""
        if window is None:
            raise RuntimeError("scope.emit() requires window=...")
        prefix = self._full_name("")
        full = f"{prefix}.{event}" if prefix else event
        window.emit(full, payload)

    def lookup(self, full_name: str) -> Command | None:
        """Resolve a full command name by walking the tree (longest match wins)."""
        parts = full_name.split(".")
        node = self
        i = 0
        # Longest scope-name prefix wins at each level.
        while i < len(parts) - 1:
            child = None
            for j in range(len(parts), i, -1):
                name = ".".join(parts[i:j])
                if name and name in node._children:
                    child = node._children[name]
                    i = j
                    break
            if child is None:
                break
            node = child
        # Longest command name wins.
        for j in range(len(parts), i, -1):
            name = ".".join(parts[i:j])
            if name:
                cmd = node._commands.get(name)
                if cmd is not None:
                    return cmd
        return None


class Plugin(Scope):
    """A Scope with window-lifecycle hooks (``on_init`` / ``on_ready``).

    The Bridge calls them on every Plugin node found by the tree walk.
    """

    def on_init(self, ctx: InitContext) -> InitContext:
        """Pre-navigation hook, called at window creation."""
        return ctx

    def on_ready(self, window: "Window") -> None:
        """Post-navigation hook, called once per window using this bridge."""


def check_chain(scope: Scope, full_name: str) -> bool:
    """Walk from the command's node up to the root, checking each layer.

    Layers without rules are skipped; a chain with no rules rejects by default.
    """
    parts = full_name.split(".")
    chain: list[Scope] = []
    node: Scope | None = scope
    while node is not None:
        chain.append(node)
        node = node._parent
    chain.reverse()
    # Dotted names span segments; track the offset per layer.
    offset = 0
    configured = False
    for nd in chain:
        if nd._name:
            offset += len(nd._name.split("."))
        perms = nd._permissions
        if perms.allow or perms.deny:
            configured = True
            rel = ".".join(parts[offset:])
            if not perms.check(rel):
                return False
    return configured


def iter_tree(root: Scope) -> Iterator[Scope]:
    """Depth-first pre-order walk, deduplicated by object identity."""

    def walk(node: Scope) -> Iterator[Scope]:
        seen.add(id(node))
        yield node
        for child in list(node._children.values()):
            if id(child) not in seen:
                yield from walk(child)

    seen: set[int] = set()
    yield from walk(root)
