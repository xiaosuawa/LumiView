"""Pure-Python unit tests for event filtering (``where=``).

No App, event loop or WebView engine is involved — these exercise the
predicate validation and dispatch-time evaluation only.
"""

from __future__ import annotations

import pytest

from lumiview.events import WindowEvent
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
        assert event.prevented is False

    def test_payload_roundtrip(self):
        event = WindowEvent.JsEvent(event="x", payload={"a": [1, 2]})
        assert event.payload == {"a": [1, 2]}
