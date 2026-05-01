from __future__ import annotations

import multiprocessing
from time import sleep
from typing import Any

import pytest
from bm_gateway.drivers.bm300 import BM300TimeoutError
from bm_gateway.subprocess_runner import run_in_subprocess_with_timeout


def _return_value(value: int) -> int:
    return value


def _raise_timeout(message: str) -> int:
    raise BM300TimeoutError(message)


def _sleep_forever(seconds: float) -> int:
    sleep(seconds)
    return 0


def test_run_in_subprocess_with_timeout_returns_result() -> None:
    result = run_in_subprocess_with_timeout(
        function=_return_value,
        args=(42,),
        timeout_seconds=5.0,
        timeout_error=lambda: RuntimeError("timed out"),
    )

    assert result == 42


def test_run_in_subprocess_with_timeout_reraises_worker_error() -> None:
    with pytest.raises(BM300TimeoutError, match="worker timeout"):
        run_in_subprocess_with_timeout(
            function=_raise_timeout,
            args=("worker timeout",),
            timeout_seconds=5.0,
            timeout_error=lambda: RuntimeError("timed out"),
        )


def test_run_in_subprocess_with_timeout_kills_hung_worker() -> None:
    with pytest.raises(BM300TimeoutError, match="hard timeout"):
        run_in_subprocess_with_timeout(
            function=_sleep_forever,
            args=(60.0,),
            timeout_seconds=0.5,
            timeout_error=lambda: BM300TimeoutError("hard timeout"),
        )


def test_run_in_subprocess_with_timeout_marks_worker_daemon_and_cleans_up_on_parent_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeQueue:
        def __init__(self) -> None:
            self.closed = False

        def poll(self, timeout: float) -> bool:
            _ = timeout
            return True

        def recv(self) -> tuple[str, object]:
            return ("result", 42)

        def close(self) -> None:
            self.closed = True

    class FakeProcess:
        def __init__(self) -> None:
            self.daemon = False
            self.started = False
            self.alive = True
            self.terminate_calls = 0
            self.join_calls: list[float] = []

        def start(self) -> None:
            self.started = True

        def join(self, timeout: float) -> None:
            self.join_calls.append(timeout)
            raise RuntimeError("join failed")

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            self.terminate_calls += 1
            self.alive = False

        def kill(self) -> None:
            raise AssertionError("kill should not be needed")

    class FakeContext:
        def __init__(self, queue: FakeQueue, process: FakeProcess) -> None:
            self._queue = queue
            self._process = process

        def Pipe(self, duplex: bool) -> tuple[FakeQueue, FakeQueue]:
            assert duplex is False
            return self._queue, self._queue

        def Process(
            self,
            target: Any,
            args: tuple[object, ...],
        ) -> FakeProcess:
            _ = (target, args)
            return self._process

    fake_queue = FakeQueue()
    fake_process = FakeProcess()
    fake_context = FakeContext(fake_queue, fake_process)

    monkeypatch.setattr(
        multiprocessing,
        "get_context",
        lambda method: fake_context if method == "spawn" else None,
    )

    with pytest.raises(RuntimeError, match="join failed"):
        run_in_subprocess_with_timeout(
            function=_return_value,
            args=(42,),
            timeout_seconds=5.0,
            timeout_error=lambda: RuntimeError("timed out"),
        )

    assert fake_process.daemon is True
    assert fake_process.started is True
    assert fake_process.terminate_calls == 1
    assert fake_queue.closed is True
