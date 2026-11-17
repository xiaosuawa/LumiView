"""Pure-Python unit tests for the event surface and ``where=`` filtering.

No App, event loop or WebView engine is involved — these exercise the
predicate validation, the preventable/non-preventable split and the event
defaults only.
"""

from __future__ import annotations

import pytest

from lumiview.events import (
    AppBaseEvent,
    AppEvent,
    AppPreventableEvent,
    WindowBaseEvent,
    WindowEvent,
    WindowPreventableEvent,
)
from lumiview._utils import passes_where


class TestPassesWhere:
    def test_none_matches_everything(self):
        assert passes_where(None, object()) is True

    def test_predicate_runs_against_the_event(self):
        event = WindowEvent.TitleChangedEvent(title="Done")
        assert passes_where(lambda e: e.title == "Done", event) is True
        assert passes_where(lambda e: e.title == "Other", event) is False

    def test_predicate_exception_is_a_non_match(self, caplog):
        def boom(_event):
            raise RuntimeError("nope")

        assert passes_where(boom, object()) is False
        assert "event filter raised" in caplog.text


class TestJsEvent:
    def test_defaults(self):
        event = WindowEvent.JsEvent(event="ping")
        assert event.event == "ping"
        assert event.payload is None
        assert event.window is None

    def test_payload_roundtrip(self):
        event = WindowEvent.JsEvent(event="x", payload={"a": [1, 2]})
        assert event.payload == {"a": [1, 2]}


class TestPreventableSurface:
    @pytest.mark.parametrize(
        "event",
        [
            WindowEvent.NavigationRequestedEvent(url="https://example.com"),
            WindowEvent.NewWindowRequestedEvent(url="https://example.com"),
            WindowEvent.DownloadStartedEvent(url="u", suggested_path="p"),
            WindowEvent.CloseRequestedEvent(),
        ],
    )
    def test_window_events_are_preventable(self, event):
        assert isinstance(event, WindowPreventableEvent)
        assert isinstance(event, WindowBaseEvent)
        assert event.prevented is False
        event.prevent()
        assert event.prevented is True

    def test_app_close_is_preventable(self):
        event = AppEvent.CloseRequestedEvent(exit_code=3)
        assert isinstance(event, AppPreventableEvent)
        assert isinstance(event, AppBaseEvent)
        assert event.prevented is False
        event.prevent()
        assert event.prevented is True
        assert event.exit_code == 3

    @pytest.mark.parametrize(
        "event",
        [
            WindowEvent.TitleChangedEvent(title="t"),
            WindowEvent.JsEvent(event="ping"),
            WindowEvent.ClosedEvent(),
            AppEvent.ReadyEvent(),
            AppEvent.ClosedEvent(),
            AppEvent.ReopenEvent(has_visible_windows=False),
        ],
    )
    def test_other_events_have_no_prevent(self, event):
        assert not isinstance(event, (WindowPreventableEvent, AppPreventableEvent))
        assert not hasattr(event, "prevent")
        assert not hasattr(event, "prevented")

    def test_prevent_sets_only_the_flag(self):
        """``prevent()`` must not disturb the event fields."""
        event = WindowEvent.NewWindowRequestedEvent(url="https://example.com")
        event.prevent()
        assert event.url == "https://example.com"
        assert event.window is None


class TestAppLifecycleEvents:
    def test_closed_carries_the_exit_code(self):
        assert AppEvent.ClosedEvent().exit_code == 0
        assert AppEvent.ClosedEvent(exit_code=7).exit_code == 7

    def test_closed_has_no_prevent(self):
        assert not hasattr(AppEvent.ClosedEvent(), "prevent")
