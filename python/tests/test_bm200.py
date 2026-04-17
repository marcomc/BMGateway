from __future__ import annotations

from bm_gateway.drivers.bm200 import (
    BM200Measurement,
    decrypt_payload,
    encrypt_payload,
    parse_plaintext_measurement,
    parse_voltage_notification,
)


def test_parse_plaintext_measurement_decodes_voltage_soc_and_state() -> None:
    plaintext = bytes.fromhex("f54f923a000000000000000000000000")

    measurement = parse_plaintext_measurement(plaintext)

    assert measurement == BM200Measurement(
        voltage=12.73,
        soc=58,
        status_code=2,
        state="normal",
    )


def test_parse_voltage_notification_decrypts_before_parsing() -> None:
    plaintext = bytes.fromhex("f54f923a000000000000000000000000")
    encrypted = encrypt_payload(plaintext)

    measurement = parse_voltage_notification(encrypted)

    assert measurement.voltage == 12.73
    assert measurement.soc == 58
    assert measurement.state == "normal"


def test_decrypt_payload_reverses_encrypt_payload() -> None:
    plaintext = bytes.fromhex("f54f9048000000000000000000000000")

    encrypted = encrypt_payload(plaintext)

    assert decrypt_payload(encrypted) == plaintext
