"""Task regressions: settling the wrapper after it was cancelled."""

from __future__ import annotations

import concurrent.futures
import logging

from lumiview.task import Task, _settle


def test_settle_resolves_a_pending_task():
    task: Task[int] = Task()
    _settle(task, result=42)
    assert task.result() == 42


def test_settle_ignores_an_already_cancelled_task():
    task: Task[int] = Task()
    task.cancel()
    _settle(task, result=42)
    assert task.cancelled()


def test_from_future_ignores_an_already_cancelled_wrapper(caplog):
    """A cancelled Task must not be re-settled by the pool future callback
    (set_result on a CANCELLED future raises InvalidStateError, which
    concurrent.futures would only log)."""
    future: concurrent.futures.Future[int] = concurrent.futures.Future()
    task = Task._from_future(future)

    task.cancel()
    with caplog.at_level(logging.ERROR, logger="concurrent.futures"):
        future.set_result(42)

    assert task.cancelled()
    assert not [
        record
        for record in caplog.records
        if "exception calling callback" in record.getMessage()
    ]
