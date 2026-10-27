"""Pure-Python unit tests for event filtering (``where=`` / ``when()``).

No App, event loop or WebView engine is involved — these exercise the
predicate construction and registration-time validation only.
"""

from __future__ import annotations

import pytest

from lumiview import contains, when
from lumiview.events import AppEvent, WindowEvent
from lumiview.utils import Where, passes_where, validate_where


class TestWhen:
    def test_matches_fields(self):
        event = WindowEvent.TitleChangedEvent(title="Done")
        assert when(title="Done")(event) is True
        assert when(title="Other")(event) is False

    def test_multiple_fields_all_must_match(self):
        event = WindowEvent.JsEvent(event="data.changed", payload=42)
        pred = when(event="data.changed", payload=42)
        assert pred(event) is True
        assert when(event="data.changed", payload=41)(event) is False

    def test_missing_attribute_does_not_match(self):
        event = WindowEvent.TitleChangedEvent(title="x")
        assert when(nope=1)(event) is False

    def test_requires_at_least_one_field(self):
        with pytest.raises(TypeError):
            when()

    def test_wraps_a_plain_predicate(self):
        pred = when(lambda e: e.width > 800)
        event = WindowEvent.ResizedEvent(width=1000, height=600)
        assert pred(event) is True
        assert pred(WindowEvent.ResizedEvent(width=400, height=600)) is False

    def test_wrapped_predicate_composes_with_fields(self):
        where = when(lambda e: e.width > 800) & when(height=600)
        assert where(WindowEvent.ResizedEvent(width=1000, height=600)) is True
        assert where(WindowEvent.ResizedEvent(width=1000, height=700)) is False
        assert where(WindowEvent.ResizedEvent(width=400, height=600)) is False

    def test_predicate_and_fields_are_mutually_exclusive(self):
        with pytest.raises(TypeError, match="either"):
            when(lambda e: True, width=1)

    def test_non_callable_predicate_raises(self):
        with pytest.raises(TypeError, match="callable"):
            when(42)

    def test_async_predicate_raises(self):
        async def pred(_event):
            return True

        with pytest.raises(TypeError, match="synchronous"):
            when(pred)

    def test_and(self):
        event = WindowEvent.ResizedEvent(width=800, height=600)
        assert (when(width=800) & when(height=600))(event) is True
        assert (when(width=800) & when(height=601))(event) is False

    def test_or(self):
        event = WindowEvent.ResizedEvent(width=800, height=600)
        assert (when(width=1) | when(height=600))(event) is True
        assert (when(width=1) | when(height=1))(event) is False

    def test_invert(self):
        event = WindowEvent.ResizedEvent(width=800, height=600)
        assert (~when(width=800))(event) is False
        assert (~when(width=1))(event) is True

    def test_composition_result_is_where(self):
        assert isinstance(when(a=1) & when(b=2), Where)
        assert isinstance(when(a=1) | when(b=2), Where)
        assert isinstance(~when(a=1), Where)


class TestWhenContainers:
    def test_values_compare_exactly_by_default(self):
        event = WindowEvent.JsEvent(
            event="x", payload={"type": "test", "value": 42}
        )
        assert when(payload={"type": "test"})(event) is False
        assert when(payload={"type": "test", "value": 42})(event) is True

    def test_contains_dict_is_a_subset(self):
        event = WindowEvent.JsEvent(
            event="x", payload={"type": "test", "value": 42}
        )
        assert when(payload=contains({"type": "test"}))(event) is True
        assert when(payload=contains({"type": "other"}))(event) is False
        assert when(payload=contains({"missing": 1}))(event) is False

    def test_contains_nested_dict(self):
        event = WindowEvent.JsEvent(
            event="x", payload={"a": {"b": 1, "c": 2}}
        )
        assert when(payload=contains({"a": {"b": 1}}))(event) is True
        assert when(payload=contains({"a": {"b": 2}}))(event) is False

    def test_contains_list_means_at_least_one_element(self):
        event = WindowEvent.JsEvent(event="x", payload=["x", "a", "y"])
        assert when(payload=contains("a"))(event) is True
        assert when(payload=contains("z"))(event) is False

    def test_contains_list_of_dicts_is_exists(self):
        event = WindowEvent.JsEvent(
            event="x", payload=[{"type": "a"}, {"type": "b", "extra": 1}]
        )
        assert when(payload=contains({"type": "b"}))(event) is True
        assert when(payload=contains({"type": "c"}))(event) is False

    def test_contains_string_is_substring(self):
        event = WindowEvent.TitleChangedEvent(title="Loading Done")
        assert when(title=contains("Done"))(event) is True
        assert when(title=contains("Error"))(event) is False

    def test_contains_dict_matches_both_object_and_array(self):
        # "Contains" is shape-agnostic: a dict actual matches as a
        # subset, a list actual matches when an element does.
        pattern = contains({"type": "test"})
        assert pattern == {"type": "test", "a": 1}
        assert pattern == [{"type": "test"}]
        assert pattern == [{"type": "a"}, {"type": "test", "x": 1}]
        assert pattern != []

    def test_contains_type_mismatch(self):
        event = WindowEvent.JsEvent(event="x", payload=[1, 2])
        assert when(payload=contains({"a": 1}))(event) is False

    def test_contains_repr(self):
        assert repr(contains({"a": 1})) == "contains({'a': 1})"

    def test_scalar_equality_unchanged(self):
        event = WindowEvent.JsEvent(event="x", payload=42)
        assert when(payload=42)(event) is True
        assert when(payload=41)(event) is False


class TestValidateWhere:
    def test_known_fields_pass(self):
        validate_where(WindowEvent.TitleChangedEvent, when(title="x"))
        validate_where(WindowEvent.JsEvent, when(event="x", payload=1))

    def test_inherited_fields_pass(self):
        validate_where(WindowEvent.TitleChangedEvent, when(prevented=False))

    def test_unknown_field_raises(self):
        with pytest.raises(TypeError, match="event"):
            validate_where(WindowEvent.TitleChangedEvent, when(event="x"))

    def test_plain_callable_not_checked(self):
        validate_where(WindowEvent.TitleChangedEvent, lambda e: True)

    def test_composed_predicate_not_checked(self):
        # Field metadata is lost after composition; validation skips it
        # rather than rejecting a legitimate predicate.
        validate_where(WindowEvent.TitleChangedEvent, when(typo=1) & when(title="x"))

    def test_event_class_without_dataclass_fields_raises(self):
        with pytest.raises(TypeError):
            validate_where(AppEvent.ReadyEvent, when(anything=1))

    def test_none_is_allowed(self):
        validate_where(WindowEvent.TitleChangedEvent, None)

    def test_non_callable_raises(self):
        with pytest.raises(TypeError, match="callable"):
            validate_where(WindowEvent.TitleChangedEvent, {"title": "x"})

    def test_coroutine_function_raises(self):
        async def pred(_event):
            return True

        with pytest.raises(TypeError, match="synchronous"):
            validate_where(WindowEvent.TitleChangedEvent, pred)


class TestPassesWhere:
    def test_none_matches_everything(self):
        assert passes_where(None, object()) is True

    def test_predicate_exception_is_a_non_match(self, caplog):
        def boom(_event):
            raise RuntimeError("nope")

        assert passes_where(boom, object()) is False
        assert "event predicate raised" in caplog.text


class TestJsEvent:
    def test_defaults(self):
        event = WindowEvent.JsEvent(event="ping")
        assert event.event == "ping"
        assert event.payload is None
        assert event.window is None
        assert event.prevented is False

    def test_payload_roundtrip(self):
        event = WindowEvent.JsEvent(event="x", payload={"a": [1, 2]})
        assert event.payload == {"a": [1, 2]}
