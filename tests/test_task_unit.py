"""Task regressions: settling the wrapper after it was cancelled."""

from __future__ import annotations

import asyncio
import concurrent.futures
import gc
import logging
import weakref

from lumiview.task import Task


def test_settle_resolves_a_pending_task():
    task: Task[int] = Task()
    task._settle(result=42)
    assert task.result() == 42


def test_settle_ignores_an_already_cancelled_task():
    task: Task[int] = Task()
    task.cancel()
    task._settle(result=42)
    assert task.cancelled()


def test_settle_keeps_the_first_settlement():
    """Two racing producers (a callback and a close watcher) are the norm."""
    task: Task[int] = Task()
    task._settle(result=1)
    task._settle(result=2)
    task._settle(exc=ValueError("late"))
    assert task.result() == 1


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


def test_unhandled_failure_is_logged_when_collected(caplog):
    """__del__ is the last line of defence for a dropped failed Task.

    The check must not go through ``Task.exception()``: that override marks
    the exception as retrieved and would disable the safety net entirely.
    """
    task = Task._failed(ValueError("boom"))
    ref = weakref.ref(task)

    with caplog.at_level(logging.ERROR, logger="lumiview.task"):
        del task
        gc.collect()

    assert ref() is None
    assert any(
        "never retrieved" in record.getMessage() for record in caplog.records
    ), [record.getMessage() for record in caplog.records]


def test_retrieved_failure_is_not_logged_when_collected(caplog):
    task = Task._failed(ValueError("handled"))
    assert isinstance(task.exception(), ValueError)

    with caplog.at_level(logging.ERROR, logger="lumiview.task"):
        del task
        gc.collect()

    assert not [
        record
        for record in caplog.records
        if "never retrieved" in record.getMessage()
    ]


def test_cancelled_awaitable_is_not_logged(caplog):
    """The shutdown sweep settles dispatches with CancelledError; a dropped
    fire-and-forget dispatch must not be reported as an unhandled failure."""
    task: Task[None] = Task()
    task.set_exception(asyncio.CancelledError())
    ref = weakref.ref(task)

    with caplog.at_level(logging.ERROR, logger="lumiview.task"):
        del task
        gc.collect()

    assert ref() is None
    assert not [
        record
        for record in caplog.records
        if "never retrieved" in record.getMessage()
    ]
