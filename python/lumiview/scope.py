from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterator, Sequence

if TYPE_CHECKING:
    from lumiview.window import Window
    from lumiview.window import WindowOptions

from lumiview.utils import match_pattern

# Permissions


@dataclass
class ScopePermission:
    """Allow/deny pattern lists for one scope node.

    Empty by default (no rules configured). ``check`` semantics:
    deny wins; an empty allow list means "no whitelist restriction"
    (deny-only blacklist). On the permission chain, unconfigured
    nodes are skipped; if NO node on the chain has any rule, the
    command is rejected by default (see :func:`check_chain`). The
    :class:`Bridge` root is initialized with ``allow=("*",)`` unless
    overridden.
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


# Command


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


# Context types


@dataclass
class BridgeContext:
    """System-injected parameter — see
    :data:`~lumiview._binding.INJECTED_TYPES`.

    Attributes:
        window: The :class:`~lumiview.window.Window` that made this call.
        payload: The raw payload (when no regular parameters exist).
        command: The full command name.
        scope: The :class:`Scope` node the command is registered on.
    """

    window: "Window"
    payload: Any
    command: str
    scope: "Scope"


@dataclass
class InitContext:
    """Context passed to :meth:`Plugin.on_init` (and
    ``Bridge._run_on_init``).

    Attributes:
        inject_script: JavaScript to inject into the page.
        window: The :class:`~lumiview.window.Window` shell under
            construction (before tao/webview creation).
        options: The :class:`~lumiview.window.WindowOptions` being
            applied. Injected by ``Window.create`` — plugins may
            register event hooks here so early events
            (``PageLoadStarted`` etc.) are not lost.
    """

    inject_script: str = ""
    window: Window | None = None
    options: WindowOptions | None = None


# Scope


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

    # Naming

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

    # Tree building

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
        ``scope.command(fn)`` all work; inside a subclass constructor
        use ``self.command(self.minimize)``.

        Parameters:
            fn: The callable to register.
            name: Override the command name (defaults to the function
                name).
            replace: Allow overwriting an existing command with the
                same name.
            strict: Reject unexpected payload keys on bridge calls.
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
        chain of the tree it already belongs to. Custom mount names are
        set at construction (``Scope(name=...)``); :meth:`include` has
        no prefix argument. Unnamed scopes cannot be mounted
        (:class:`ValueError`).
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

    # Permissions

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

    # Events

    def emit(
        self,
        event: str,
        payload: Any = None,
        *,
        window: "Window | None" = None,
    ) -> None:
        """Emit an event with this scope's namespace prefix.

        Requires ``window=`` (the target window). Inside commands:
        ``ctx.scope.emit("changed", {...}, window=ctx.window)``.
        """
        if window is None:
            raise RuntimeError("scope.emit() requires window=...")
        prefix = self._full_name("")
        full = f"{prefix}.{event}" if prefix else event
        window.emit(full, payload)

    # Lookup

    def lookup(self, full_name: str) -> Command | None:
        """Resolve a full command name by walking the tree.

        Scope and command names may contain dots: at each step the
        longest matching scope name wins, then the longest matching
        command name — names without dots resolve exactly as before.
        """
        parts = full_name.split(".")
        node = self
        i = 0
        # Descend: at each level try the longest scope-name prefix
        # (so dotted scope names like "a.b" resolve from "a.b.cmd").
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
        # Command lookup: longest remaining name first (dotted command
        # names like "read.log" resolve before single segments).
        for j in range(len(parts), i, -1):
            name = ".".join(parts[i:j])
            if name:
                cmd = node._commands.get(name)
                if cmd is not None:
                    return cmd
        return None


# Plugin (lifecycle hooks)


class Plugin(Scope):
    """A Scope with window-lifecycle hooks.

    Subclass and override :meth:`on_init` / :meth:`on_ready` to hook
    into window creation::

        class MyPlugin(Plugin):
            def on_init(self, ctx: InitContext) -> InitContext:
                ctx.inject_script += "// ..."
                return ctx

            def on_ready(self, window: Window) -> None:
                ...

    The :class:`Bridge` dispatches hooks to every ``Plugin`` node found
    by the tree walk (``isinstance`` check) — defining a method with
    the same name on a plain :class:`Scope` is ignored.
    """

    def on_init(self, ctx: InitContext) -> InitContext:
        """Pre-navigation hook, called at window creation."""
        return ctx

    def on_ready(self, window: "Window") -> None:
        """Post-navigation hook, called once per window using this bridge."""


# Module helpers


def check_chain(scope: Scope, full_name: str) -> bool:
    """Walk from the command's registration node up to the tree root.

    Each layer checks the path relative to itself, so rule semantics
    don't drift when a subtree is re-mounted (:meth:`Scope.include`).
    Layers without any rules are skipped; if NO layer has any rule, the
    command is rejected by default (safe default — an unconfigured
    chain must not accidentally allow everything).
    """
    parts = full_name.split(".")
    # Node chain (root → registration node).
    chain: list[Scope] = []
    node: Scope | None = scope
    while node is not None:
        chain.append(node)
        node = node._parent
    chain.reverse()
    # A node name may span multiple path segments when it contains
    # dots — track the segment offset per layer, so each layer's
    # relative path covers everything below it (the command's own
    # name is the tail).
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
        for child in node._children.values():
            if id(child) not in seen:
                yield from walk(child)

    seen: set[int] = set()
    yield from walk(root)
