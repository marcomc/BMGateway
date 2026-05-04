"""Shared BLE live-polling helpers for battery monitor drivers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class NotificationClient(Protocol):
    async def __aenter__(self) -> "NotificationClient": ...

    async def __aexit__(
        self,
        exc_type: object | None,
        exc: object | None,
        tb: object | None,
    ) -> None: ...

    async def start_notify(
        self,
        characteristic: str,
        callback: Callable[[object | None, bytearray], None],
    ) -> None: ...

    async def stop_notify(self, characteristic: str) -> None: ...


def device_rssi(device: object) -> int | None:
    direct = getattr(device, "rssi", None)
    if isinstance(direct, (int, float)):
        return int(direct)
    details = getattr(device, "details", None)
    if isinstance(details, dict):
        props = details.get("props")
        if isinstance(props, dict):
            rssi = props.get("RSSI")
            if isinstance(rssi, (int, float)):
                return int(rssi)
    return None


async def _read_notification_session(
    *,
    client: NotificationClient,
    notify_characteristic: str,
    read_attempt: Callable[..., Awaitable[bytes]],
    deadline: float,
) -> bytes:
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def notification_handler(_: object | None, data: bytearray) -> None:
        queue.put_nowait(bytes(data))

    async with client:
        await client.start_notify(notify_characteristic, notification_handler)
        try:
            return await read_attempt(
                client=client,
                packet_queue=queue,
                deadline=deadline,
            )
        finally:
            await client.stop_notify(notify_characteristic)


async def read_live_notification(
    *,
    address: str,
    timeout_seconds: float,
    scan_timeout_seconds: float,
    notify_characteristic: str,
    find_device_by_address: Callable[..., Awaitable[object | None]],
    client_factory: Callable[..., Any],
    read_attempt: Callable[..., Awaitable[bytes]],
    device_not_found_error: Callable[[str], BaseException],
    timeout_error: Callable[[str], BaseException],
    timeout_exception_types: tuple[type[BaseException], ...],
    scanner_kwargs: dict[str, object] | None = None,
    client_kwargs: dict[str, object] | None = None,
) -> tuple[bytes, int | None]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    last_error: BaseException | None = None
    scan_timeout = max(1.0, scan_timeout_seconds)
    active_scanner_kwargs = scanner_kwargs or {}
    active_client_kwargs = client_kwargs or {}

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            if last_error is not None:
                raise last_error
            raise device_not_found_error(address)

        device = await find_device_by_address(
            address,
            timeout=min(scan_timeout, remaining),
            **active_scanner_kwargs,
        )
        if device is None:
            continue
        rssi = device_rssi(device)

        client: NotificationClient = client_factory(
            device,
            timeout=min(scan_timeout, remaining),
            **active_client_kwargs,
        )
        try:
            encrypted = await asyncio.wait_for(
                _read_notification_session(
                    client=client,
                    notify_characteristic=notify_characteristic,
                    read_attempt=read_attempt,
                    deadline=deadline,
                ),
                timeout=max(deadline - loop.time(), 0.0),
            )
            return encrypted, rssi
        except TimeoutError as exc:
            last_error = timeout_error(address)
            if deadline - loop.time() <= 0:
                raise last_error from exc
        except timeout_exception_types:
            raise
        except Exception as exc:
            # The device was seen but failed to connect or complete the request
            # in this window. Retry discovery until the overall deadline expires.
            last_error = exc
            await asyncio.sleep(min(1.0, max(deadline - loop.time(), 0.0)))
            continue
