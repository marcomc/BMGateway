"""Helpers for running blocking work in a child process with a hard timeout."""

from __future__ import annotations

import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Callable, TypeVar, cast

T = TypeVar("T")


def _subprocess_entry(
    connection: Connection,
    function: Callable[..., T],
    args: tuple[object, ...],
) -> None:
    try:
        result = function(*args)
    except BaseException as exc:  # pragma: no cover - exercised via parent process
        try:
            connection.send(("error", exc))
        except Exception as connection_error:
            connection.send(
                (
                    "error",
                    RuntimeError(
                        f"Child process failed while reporting {exc.__class__.__name__}: {exc}"
                    ),
                )
            )
            raise connection_error
    else:
        connection.send(("result", result))
    finally:
        connection.close()


def _terminate_process(process: BaseProcess) -> None:
    if not process.is_alive():
        return
    process.terminate()
    process.join(5.0)
    if process.is_alive():
        process.kill()
        process.join(5.0)


def run_in_subprocess_with_timeout(
    *,
    function: Callable[..., T],
    args: tuple[object, ...],
    timeout_seconds: float,
    timeout_error: Callable[[], BaseException],
) -> T:
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_subprocess_entry,
        args=(child_connection, function, args),
    )
    process.daemon = True
    process.start()
    child_connection.close()
    try:
        process.join(timeout_seconds)
        if process.is_alive():
            _terminate_process(process)
            raise timeout_error()

        if not parent_connection.poll(1.0):
            raise RuntimeError("Child process exited without returning a result.")
        kind, payload = parent_connection.recv()

        if kind == "result":
            return cast(T, payload)
        raise cast(BaseException, payload)
    except BaseException:
        _terminate_process(process)
        raise
    finally:
        parent_connection.close()
