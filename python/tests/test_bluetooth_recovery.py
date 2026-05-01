from __future__ import annotations

from bm_gateway.bluetooth_recovery import is_fatal_bluetooth_error


def test_is_fatal_bluetooth_error_detects_any_missing_adapter() -> None:
    assert is_fatal_bluetooth_error(RuntimeError("adapter 'hci1' not found")) is True
    assert is_fatal_bluetooth_error(RuntimeError('adapter "hci2" not found')) is True


def test_is_fatal_bluetooth_error_ignores_unrelated_adapter_messages() -> None:
    assert is_fatal_bluetooth_error(RuntimeError("adapter recovered after retry")) is False
