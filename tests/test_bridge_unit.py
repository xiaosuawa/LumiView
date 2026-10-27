"""Pure-Python unit tests for the Bridge/Scope/binding layer.

These exercise the logic that does NOT need a real WebView engine or OS
window — the permission chain, command binding + strict mode, tree
lookup/mounting, and the synchronous dispatch branches of
``Bridge._on_message``. They run fast and are deterministic everywhere.

The only native dependency is ``lumiview._core`` (loaded by importing an
already-installed ``lumiview``) — no WebView2 / WKWebKit / GTK engine is
spawned.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from lumiview._binding import _strict_scalar, bind_arguments
from lumiview.bridge import Bridge, BridgeError
from lumiview.events import WindowEvent
from lumiview.scope import (
    BridgeContext,
    Scope,
    ScopePermission,
    check_chain,
    iter_tree,
)

# ---------------------------------------------------------------------------
# _strict_scalar — exact-match type checks (no silent coercion)
# ---------------------------------------------------------------------------


class TestStrictScalar:
    @pytest.mark.parametrize(
        "value", [1.5, 3, 0, -2.7], ids=["float", "int", "zero", "negative-float"]
    )
    def test_float_accepts_int_and_float(self, value):
        assert _strict_scalar(value, float) == value

    @pytest.mark.parametrize(
        "value",
        [True, "3.5", "x", None, [1.0], {"a": 1.5}],
        ids=[
            "bool",
            "str-float",
            "str",
            "none",
            "list",
            "dict",
        ],
    )
    def test_float_rejects_non_numeric(self, value):
        with pytest.raises(Exception):
            _strict_scalar(value, float)

    @pytest.mark.parametrize("value", [5, 0, -8], ids=["int", "zero", "negative"])
    def test_int_accepts_int(self, value):
        assert _strict_scalar(value, int) == value

    def test_int_accepts_float_that_is_integral(self):
        assert _strict_scalar(3.0, int) == 3

    @pytest.mark.parametrize(
        "value",
        [True, 3.5, "3", "x", None],
        ids=[
            "bool",
            "non-integral-float",
            "str-int",
            "str",
            "none",
        ],
    )
    def test_int_rejects_non_int(self, value):
        with pytest.raises(Exception):
            _strict_scalar(value, int)

    def test_str_requires_exact_type(self):
        assert _strict_scalar("hi", str) == "hi"
        with pytest.raises(Exception):
            _strict_scalar(5, str)

    def test_bool_requires_exact_type(self):
        assert _strict_scalar(True, bool) is True
        # bool is an int subclass — must NOT be accepted as int above;
        # and int is not a bool.
        with pytest.raises(Exception):
            _strict_scalar(1, bool)


# ---------------------------------------------------------------------------
# bind_arguments — payload → kwargs
# ---------------------------------------------------------------------------


class TestBindArguments:
    def _scope_with(self, fn, *, strict=True, name="cmd"):
        # Root Scope("") defines the path prefix; commands live on children.
        root = Scope("")
        scope = root.scope("s")
        scope.command(fn, name=name, strict=strict)
        cmd = root.lookup(f"s.{name}")
        assert cmd is not None
        return cmd

    def test_binds_regular_params(self):
        def add(a: int, b: int) -> int:
            return a + b

        cmd = self._scope_with(add)
        kwargs = bind_arguments(cmd, {"a": 2, "b": 3}, None)
        assert kwargs == {"a": 2, "b": 3}

    def test_injects_bridge_context(self):
        seen = {}

        def go(ctx: BridgeContext, name: str) -> None:
            seen["ctx"] = ctx
            return None

        cmd = self._scope_with(go)
        kwargs = bind_arguments(cmd, {"name": "x"}, None)
        assert kwargs["name"] == "x"
        ctx = kwargs["ctx"]
        assert isinstance(ctx, BridgeContext)
        # _scope_with registers under name="cmd" by default.
        assert ctx.command == "s.cmd"
        assert ctx.payload == {"name": "x"}
        assert isinstance(ctx.scope, Scope)

    def test_missing_required_arg_raises(self):
        def add(a: int, b: int) -> int:
            return a + b

        cmd = self._scope_with(add)
        with pytest.raises(BridgeError) as ei:
            bind_arguments(cmd, {"a": 1}, None)
        assert ei.value.code == "invalid_argument"
        assert "b" in str(ei.value)

    def test_strict_rejects_extra_key(self):
        def add(a: int) -> int:
            return a

        cmd = self._scope_with(add, strict=True)
        with pytest.raises(BridgeError) as ei:
            bind_arguments(cmd, {"a": 1, "bogus": 2}, None)
        assert ei.value.code == "invalid_argument"
        assert "bogus" in str(ei.value)

    def test_strict_false_allows_extra_key(self):
        def add(a: int) -> int:
            return a

        cmd = self._scope_with(add, strict=False)
        kwargs = bind_arguments(cmd, {"a": 1, "extra": 2}, None)
        assert kwargs == {"a": 1}

    def test_payload_non_dict_raises(self):
        def add(a: int) -> int:
            return a

        cmd = self._scope_with(add)
        with pytest.raises(BridgeError) as ei:
            bind_arguments(cmd, [1, 2], None)
        assert ei.value.code == "invalid_argument"

    def test_default_used_when_key_absent(self):
        def add(a: int, b: int = 100) -> int:
            return a + b

        cmd = self._scope_with(add)
        kwargs = bind_arguments(cmd, {"a": 1}, None)
        assert kwargs == {"a": 1}  # b omitted → Python default

    def test_invalid_type_raises(self):
        def add(a: int) -> int:
            return a

        cmd = self._scope_with(add)
        # bool should NOT smuggle in as an int despite being a subclass.
        with pytest.raises(BridgeError) as ei:
            bind_arguments(cmd, {"a": True}, None)
        assert ei.value.code == "invalid_argument"

    def test_forward_ref_annotation_resolved_at_call_time(self, monkeypatch):
        root = Scope("")
        scope = root.scope("s")

        # `LaterItem` is defined below registration time (like a module
        # with a forward reference). Registration must cache None, not {},
        # so binding retries get_type_hints when the command is invoked.
        @scope.command(name="save")
        def save(item: LaterItem) -> None:  # noqa: F821 — defined after
            return None

        cmd = root.lookup("s.save")
        assert cmd is not None
        assert cmd.type_hints is None

        @dataclass
        class LaterItem:
            name: str

        monkeypatch.setitem(globals(), "LaterItem", LaterItem)
        kwargs = bind_arguments(cmd, {"item": {"name": "x"}}, None)
        assert isinstance(kwargs["item"], LaterItem)
        assert kwargs["item"].name == "x"


# ---------------------------------------------------------------------------
# ScopePermission.check + check_chain
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_deny_wins_over_allow(self):
        p = ScopePermission(allow=("fs.*",), deny=("fs.secret",))
        assert p.check("fs.read") is True
        assert p.check("fs.secret") is False

    def test_empty_allow_is_blacklist_only(self):
        p = ScopePermission(deny=("sec.*",))
        assert p.check("allow.anything") is True
        assert p.check("sec.internal") is False

    def test_allow_hit(self):
        p = ScopePermission(allow=("read.*", "write.*"))
        assert p.check("read.1") is True
        assert p.check("write.1") is True
        assert p.check("exec.1") is False

    def test_check_chain_unconfigured_defaults_reject(self):
        # No node has any rule → safe default is reject.
        root = Scope("")
        child = root.scope("a").scope("b")
        child.command(lambda: None, name="run")
        assert check_chain(child._commands["run"].scope, "a.b.run") is False

    def test_check_chain_single_allow(self):
        root = Scope("", permissions=ScopePermission(allow=("*",)))
        child = root.scope("a")
        child.command(lambda: None, name="run")
        assert check_chain(child._commands["run"].scope, "a.run") is True

    def test_check_chain_nested_relative(self):
        # allow on the 'a' node, command under a.b — path relative to 'a'
        # is 'b.run', which 'a.*' covers.
        root = Scope("")
        a = root.scope("a")
        a.permissions = ScopePermission(allow=("b.*",))
        b = a.scope("b")
        b.command(lambda: None, name="run")
        assert check_chain(b._commands["run"].scope, "a.b.run") is True

    def test_check_chain_include_semantics_preserved(self):
        root = Scope("", permissions=ScopePermission(allow=("*",)))
        sub = Scope("sub", permissions=ScopePermission(allow=("go",)))
        sub.command(lambda: None, name="go")
        root.include(sub)
        # 'sub.go' allowed via sub's own rule; root '*' also allows.
        assert check_chain(sub._commands["go"].scope, "sub.go") is True

    def test_check_chain_dotted_scope_offset(self):
        root = Scope("", permissions=ScopePermission(allow=("*",)))
        ab = root.scope("a.b")  # a dotted scope name spans two segments
        ab.command(lambda: None, name="run")
        assert check_chain(ab._commands["run"].scope, "a.b.run") is True


# ---------------------------------------------------------------------------
# Scope.lookup — dotted-name longest-match resolution
# ---------------------------------------------------------------------------


class TestLookup:
    def test_plain_name_exact(self):
        root = Scope("")
        fn = root.command(lambda: None, name="ping")
        # root.command returns the fn; lookup returns the Command wrapping it.
        cmd = root.lookup("ping")
        assert cmd is not None
        assert cmd.fn is fn
        assert cmd.name == "ping"

    def test_dotted_scope_name_longest_match(self):
        root = Scope("")
        # One scope node whose _name contains a dot ("a.b") — this is the
        # look-it-up-as-a-single-segment case the longest-match walk handles.
        nb = root.scope("a.b")
        fn = nb.command(lambda: None, name="run")
        cmd = root.lookup("a.b.run")
        assert cmd is not None
        assert cmd.fn is fn


# ---------------------------------------------------------------------------
# Scope.command registration / replace / signature guards
# ---------------------------------------------------------------------------


class TestCommandRegistration:
    def test_replace_detects_conflict(self):
        root = Scope("")
        root.command(lambda: None, name="dup")
        with pytest.raises(ValueError):
            root.command(lambda: None, name="dup")

    def test_replace_allows_overwrite(self):
        root = Scope("")
        root.command(lambda: None, name="dup")
        root.command(lambda: None, name="dup", replace=True)  # no raise

    def test_var_args_rejected(self):
        root = Scope("")
        with pytest.raises(ValueError):
            root.command(lambda *a: None, name="va")
        with pytest.raises(ValueError):
            root.command(lambda **k: None, name="kw")


# ---------------------------------------------------------------------------
# Scope.include guards
# ---------------------------------------------------------------------------


class TestInclude:
    def test_anonymous_scope_rejected(self):
        root = Scope("")
        with pytest.raises(ValueError):
            root.include(Scope(""))  # unnamed

    def test_already_mounted_rejected(self):
        root = Scope("")
        sub = Scope("sub")
        root.include(sub)
        with pytest.raises(ValueError):
            root.include(sub)  # same instance re-mounted

    def test_self_under_own_subtree_rejected(self):
        root = Scope("root")
        with pytest.raises(ValueError):
            root.include(root)  # cannot mount under itself

    def test_include_non_scope_rejected(self):
        root = Scope("")
        with pytest.raises(TypeError):
            root.include("not-a-scope")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# iter_tree order + dedup
# ---------------------------------------------------------------------------


class TestIterTree:
    def test_preorder_and_dedup(self):
        root = Scope("root")
        a = root.scope("a")
        b = root.scope("b")
        a.scope("a1")
        names = [s._name for s in iter_tree(root)]
        assert names == ["root", "a", "a1", "b"]


# ---------------------------------------------------------------------------
# BridgeError serialization
# ---------------------------------------------------------------------------


class TestBridgeError:
    def test_to_dict_includes_code_and_message(self):
        e = BridgeError("invalid_argument", "bad input")
        d = e.to_dict()
        assert d == {"code": "invalid_argument", "message": "bad input"}

    def test_to_dict_includes_optional_data(self):
        e = BridgeError("forbidden", "nope", data={"path": "x"})
        assert e.to_dict()["data"] == {"path": "x"}

    def test_str_is_message(self):
        assert str(BridgeError("x", "msg")) == "msg"


# ---------------------------------------------------------------------------
# Bridge._on_message — synchronous dispatch branches (no live app/WebView)
# ---------------------------------------------------------------------------


class _StubWindow:
    """Minimal stand-in for a Window: only carries _webview (never deref'd
    in the branches under test)."""

    def __init__(self):
        self._webview = None


class TestOnMessage:
    def _send_collector(self):
        captured = []
        return captured, captured.append

    def test_non_json_ignored(self):
        b = Bridge()
        captured, send = self._send_collector()
        # Should not raise; nothing added since there's no call_id/command path.
        b._on_message(_StubWindow(), "not-json{{{", send=send)
        assert captured == []

    def test_non_object_ignored(self):
        b = Bridge()
        captured, send = self._send_collector()
        b._on_message(_StubWindow(), json.dumps(["a", "b"]), send=send)
        assert captured == []

    def test_non_invoke_type_ignored(self):
        b = Bridge()
        captured, send = self._send_collector()
        b._on_message(
            _StubWindow(),
            json.dumps({"type": "listen", "id": "1", "command": "x"}),
            send=send,
        )
        assert captured == []

    def test_missing_call_id_ignored(self):
        b = Bridge()
        captured, send = self._send_collector()
        b._on_message(
            _StubWindow(),
            json.dumps({"type": "invoke", "command": "x"}),
            send=send,
        )
        assert captured == []

    def test_unknown_command_responds(self):
        b = Bridge()
        captured, send = self._send_collector()
        b._on_message(
            _StubWindow(),
            json.dumps({"type": "invoke", "id": "9", "command": "nope"}),
            send=send,
        )
        assert len(captured) == 1
        script = captured[0]
        # script is window.lumiview._dispatchResponse({...}); assert the JSON.
        payload = json.loads(script[len("window.lumiview._dispatchResponse(") : -1])
        assert payload["type"] == "reject"
        assert payload["error"]["code"] == "unknown_command"

    def test_forbidden_when_not_in_chain(self):
        # A command exists but is not allowed by the permission chain.
        b = Bridge(permissions=ScopePermission(allow=("ping",)))
        b.command(lambda ctx: None, name="ping")
        b.command(lambda ctx: None, name="secret")
        captured, send = self._send_collector()
        b._on_message(
            _StubWindow(),
            json.dumps({"type": "invoke", "id": "5", "command": "secret"}),
            send=send,
        )
        assert len(captured) == 1
        payload = json.loads(
            captured[0][len("window.lumiview._dispatchResponse(") : -1]
        )
        assert payload["error"]["code"] == "forbidden"

    def test_app_not_running_when_get_raises(self, monkeypatch):
        b = Bridge()
        b.command(lambda: None, name="ping")

        def _boom():
            raise RuntimeError("no App")

        # `_on_message` does `from lumiview.app import App; App.get()`. Patch
        # the classmethod so it raises (App not yet created).
        import lumiview.app as app_mod

        monkeypatch.setattr(app_mod.App, "get", staticmethod(_boom))
        captured, send = self._send_collector()
        b._on_message(
            _StubWindow(),
            json.dumps({"type": "invoke", "id": "1", "command": "ping"}),
            send=send,
        )
        assert len(captured) == 1
        payload = json.loads(
            captured[0][len("window.lumiview._dispatchResponse(") : -1]
        )
        assert payload["error"]["code"] == "internal_error"
        assert "App not running" in str(payload["error"]["message"])


# ---------------------------------------------------------------------------
# Bridge._on_message — JS → Python events (window.lumiview.emit)
# ---------------------------------------------------------------------------


class _EventStubWindow(_StubWindow):
    """Stub that records dispatched window events."""

    def __init__(self):
        super().__init__()
        self.events = []

    def _emit(self, event):
        self.events.append(event)


class TestOnMessageEmit:
    def test_emit_dispatches_js_event(self):
        b = Bridge()
        win = _EventStubWindow()
        b._on_message(
            win,
            json.dumps(
                {"type": "emit", "event": "data.changed", "payload": {"value": 42}}
            ),
        )
        assert len(win.events) == 1
        event = win.events[0]
        assert isinstance(event, WindowEvent.JsEvent)
        assert event.event == "data.changed"
        assert event.payload == {"value": 42}

    def test_emit_without_payload(self):
        b = Bridge()
        win = _EventStubWindow()
        b._on_message(win, json.dumps({"type": "emit", "event": "ping"}))
        assert len(win.events) == 1
        assert win.events[0].payload is None

    def test_emit_without_name_ignored(self):
        b = Bridge()
        win = _EventStubWindow()
        b._on_message(win, json.dumps({"type": "emit", "payload": {}}))
        assert win.events == []

    def test_emit_non_string_name_ignored(self):
        b = Bridge()
        win = _EventStubWindow()
        b._on_message(win, json.dumps({"type": "emit", "event": 7}))
        assert win.events == []

    def test_emit_does_not_need_a_command(self):
        # Events are notifications, not commands — no scope registration
        # and no permission chain are involved.
        b = Bridge(permissions=ScopePermission(allow=()))
        win = _EventStubWindow()
        b._on_message(win, json.dumps({"type": "emit", "event": "anything"}))
        assert len(win.events) == 1
