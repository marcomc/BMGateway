from __future__ import annotations

import warnings
from dataclasses import replace
from pathlib import Path

import pytest
from bm_gateway.config import load_config, validate_config, write_config
from bm_gateway.localization import (
    SUPPORTED_LOCALES,
    LocalizationWarning,
    is_rtl_locale,
    localize_html,
    missing_translations_for_html,
    normalize_locale,
    resolve_locale_preference,
    translation_for,
)
from bm_gateway.web import render_home_html, render_settings_html, update_web_preferences
from bm_gateway.web_pages import (
    render_add_device_html,
    render_device_html,
    render_devices_html,
    render_diagnostics_html,
    render_edit_device_html,
    render_frame_battery_overview_html,
    render_frame_fleet_trend_html,
    render_history_html,
    render_reboot_pending_html,
    render_shutdown_pending_html,
    render_usb_otg_export_pending_html,
)
from bm_gateway.web_ui import chart_script


def test_supported_locales_cover_common_interface_languages() -> None:
    codes = {locale.code for locale in SUPPORTED_LOCALES}

    assert len(codes) >= 10
    assert {
        "en",
        "fr",
        "it",
        "pt",
        "de",
        "es",
        "zh-Hans",
        "hi",
        "ar",
        "bn",
        "ru",
        "ur",
    }.issubset(codes)


def test_locale_normalization_and_direction() -> None:
    assert normalize_locale("fr-FR") == "fr"
    assert normalize_locale("pt_BR") == "pt"
    assert normalize_locale("zh-CN") == "zh-Hans"
    assert normalize_locale("unknown") == "en"
    assert is_rtl_locale("ar") is True
    assert is_rtl_locale("ur") is True
    assert is_rtl_locale("it") is False


def test_auto_locale_resolves_browser_language_preferences() -> None:
    assert resolve_locale_preference("auto", "fr-CA,fr;q=0.9,en;q=0.7") == "fr"
    assert resolve_locale_preference("auto", "ja,pt-BR;q=0.8,it;q=0.7") == "pt"
    assert resolve_locale_preference("auto", "de;q=0,es;q=0.4") == "es"
    assert resolve_locale_preference("auto", "unsupported") == "en"
    assert resolve_locale_preference("it", "fr-FR,fr;q=0.9") == "it"


def test_catalog_translates_known_labels_and_falls_back_to_english() -> None:
    italian = translation_for("it")

    assert italian.gettext("Battery Overview") == "Panoramica batteria"
    assert italian.gettext("Settings") == "Impostazioni"
    assert italian.gettext("Voltage") == "Voltaggio"
    assert italian.gettext("Battery voltage") == "Voltaggio batteria"
    assert italian.gettext("Average voltage") == "Voltaggio medio"
    assert italian.gettext("BMGateway") == "BMGateway"


def test_voltage_ui_terms_are_translated_in_all_supported_locales() -> None:
    message_keys = (
        "Average voltage",
        "Battery voltage",
        "Pick whether charts should open on Voltage, State of Charge, or Temperature.",
        "Select nominal voltage",
        "Voltage",
        "Voltage corresponding to power",
        "Latest:",
    )

    for locale in SUPPORTED_LOCALES:
        if locale.code == "en":
            continue
        translation = translation_for(locale.code)
        missing = [key for key in message_keys if translation.gettext(key) == key]
        assert missing == [], f"{locale.code} missing voltage UI translations: {missing}"


def test_localize_html_sets_lang_dir_and_translates_text_nodes() -> None:
    localized = localize_html(
        '<!doctype html><html lang="en"><body><h1>Settings</h1>'
        '<a aria-label="Open details for House Battery">Battery Overview</a>'
        '<span translate="no">BMGateway</span></body></html>',
        "ar",
    )

    assert '<html lang="ar" dir="rtl">' in localized
    assert ">الإعدادات<" in localized
    assert ">نظرة عامة على البطارية<" in localized
    assert 'aria-label="افتح التفاصيل لـ House Battery"' in localized
    assert ">BMGateway<" in localized


def test_localize_html_keeps_nested_translate_no_content_literal() -> None:
    source_html = (
        '<!doctype html><html lang="en"><body>'
        '<select translate="no"><option>Battery Overview</option>'
        "<option>Fleet Trend</option></select>"
        "<p>Battery Overview</p></body></html>"
    )

    localized = localize_html(source_html, "it")

    assert "<option>Battery Overview</option>" in localized
    assert "<option>Fleet Trend</option>" in localized
    assert "<p>Panoramica batteria</p>" in localized


def test_localize_html_warns_when_catalog_is_missing_translatable_text() -> None:
    source_html = (
        '<!doctype html><html lang="en"><body><h1>Settings</h1><p>New Label</p></body></html>'
    )

    with pytest.warns(LocalizationWarning, match="missing 1 Spanish translation"):
        localized = localize_html(source_html, "es")

    assert ">Ajustes<" in localized
    assert ">New Label<" in localized


def test_missing_translations_for_html_reports_untranslated_catalog_entries() -> None:
    source_html = (
        '<!doctype html><html lang="en"><body><h1>Settings</h1><p>New Label</p></body></html>'
    )

    assert missing_translations_for_html(source_html, "es") == ("New Label",)


def test_dynamic_prefixes_do_not_require_device_value_specific_catalog_entries() -> None:
    source_html = (
        '<!doctype html><html lang="en"><body>'
        '<a aria-label="Open details for Spare NLP5">Serial / MAC: AA:BB:CC:DD:EE:01</a>'
        "</body></html>"
    )

    localized = localize_html(source_html, "it")

    assert "Apri dettagli per Spare NLP5" in localized
    assert "Seriale / MAC: AA:BB:CC:DD:EE:01" in localized
    assert missing_translations_for_html(source_html, "it") == ()


def test_dynamic_error_messages_localize_stable_prefixes() -> None:
    source_html = (
        '<!doctype html><html lang="en"><body>'
        '<div class="banner-strip warning">'
        "USB OTG frame image export failed: sudo: unable to change to root gid"
        "</div></body></html>"
    )

    localized = localize_html(source_html, "it")

    assert "Esportazione immagini cornice USB OTG non riuscita" in localized
    assert "sudo: unable to change to root gid" in localized
    assert "USB OTG frame image export failed" not in localized
    assert missing_translations_for_html(source_html, "it") == ()


def test_common_web_action_messages_are_translated_in_all_supported_locales() -> None:
    message_keys = (
        "Validation failed",
        "Validation failed: USB OTG settings values must be numeric",
        "Run completed",
        "Run failed",
        "Home Assistant discovery republished",
        "Home Assistant discovery republish failed",
        "bm-gateway service restarted",
        "Failed to restart bm-gateway service",
        "Bluetooth service restarted",
        "Failed to restart Bluetooth service",
        "USB OTG boot mode prepared; reboot required",
        "Failed to prepare USB OTG boot mode",
        "USB host boot mode restored; reboot required",
        "Failed to restore USB host boot mode",
        "USB OTG drive refreshed",
        "Failed to refresh USB OTG drive",
        "Bluetooth adapter recovery triggered",
        "History pruned",
        "Settings saved",
        "USB OTG frame image export started",
        "Settings saved; USB OTG frame image export started",
        "USB OTG frame images exported",
        "USB OTG frame image export failed",
        "Preparing USB OTG frame image export",
        "Rendered frame image",
        "Writing images to USB OTG drive",
    )

    for locale in SUPPORTED_LOCALES:
        if locale.code == "en":
            continue
        translation = translation_for(locale.code)
        missing = [key for key in message_keys if translation.gettext(key) == key]
        assert missing == [], f"{locale.code} missing action message translations: {missing}"


def test_chart_script_uses_selected_language_for_generated_summary_text() -> None:
    script = chart_script("history-chart", language="it")

    assert '"Window":"Finestra"' in script
    assert '"Visible devices":"Dispositivi visibili"' in script
    assert '"Average":"Media"' in script
    assert '"Range":"Intervallo"' in script
    assert "Window:" not in script
    assert "Visible devices:" not in script
    assert '"Showing all available history":"Mostra tutta la cronologia disponibile"' in script
    assert '"All retained history":"Tutta la cronologia conservata"' in script
    assert '"Recent raw":"Grezzi recenti"' in script
    assert '"Selected range":"Intervallo selezionato"' in script


def test_mqtt_anonymous_placeholders_are_translated_to_italian() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(config, mqtt=replace(config.mqtt, username="", password=""))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[],
        edit_mode=False,
        theme_preference="light",
        language="it",
        detected_bluetooth_adapters=[],
        usb_otg_device_controller_detected=False,
        usb_otg_boot_mode_prepared=False,
        usb_otg_support_installed=False,
    )

    assert "Anonimo / non impostato" in html
    assert "Vuoto / anonimo" in html
    assert "Anonymous / not set" not in html
    assert "Empty / anonymous" not in html


def test_device_status_explainer_uses_selected_language() -> None:
    html = render_device_html(
        device_id="spare_nlp5",
        raw_history=[
            {
                "ts": "2026-04-24T12:23:40+02:00",
                "voltage": 13.29,
                "soc": 85,
                "temperature": 24.0,
                "state": "normal",
                "error_code": None,
            },
            {
                "ts": "2026-04-24T11:26:14+02:00",
                "voltage": 0.0,
                "soc": 0,
                "temperature": None,
                "state": "offline",
                "error_code": "device_not_found",
            },
        ],
        daily_history=[],
        monthly_history=[],
        yearly_history=[],
        analytics={"windows": []},
        device_summary={
            "name": "Spare NLP5",
            "soc": 85,
            "voltage": 13.29,
            "temperature": 24.0,
            "state": "normal",
            "error_code": None,
            "last_seen": "2026-04-24T12:23:40+02:00",
            "connected": True,
            "battery": {
                "brand": "NOCO",
                "model": "NLP5",
                "nominal_voltage": 12,
                "capacity_ah": 5.0,
                "production_year": 2025,
            },
            "vehicle": {"installed": True, "type": "bench"},
            "installed_in_vehicle": True,
            "vehicle_type": "bench",
        },
        language="it",
    )

    assert "Banco" in html
    assert "Nessuno" in html
    assert "normale" in html
    assert "non in linea" in html
    assert "dispositivo_non_trovato" in html
    assert "Normale" in html
    assert "La condizione della batteria e stabile" in html
    assert "Battery condition is stable" not in html
    assert 'data-label="Normal"' not in html
    assert ">offline<" not in html
    assert "Bench" not in html


def test_confirmation_prompts_are_translated_and_audited() -> None:
    source_html = (
        '<!doctype html><html lang="en"><body>'
        "<form onsubmit=\"return confirm('Reboot the Raspberry Pi now?')\">"
        "<button>Reboot Raspberry Pi</button></form>"
        "</body></html>"
    )

    localized = localize_html(source_html, "it")

    assert "return confirm(&#x27;Riavviare il Raspberry Pi ora?&#x27;)" in localized
    assert "Riavvia Raspberry Pi" in localized
    assert missing_translations_for_html(source_html, "it") == ()


def test_config_defaults_to_auto_and_validates_supported_languages(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text("", encoding="utf-8")
    config_path.write_text(
        Path("python/config/config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert config.web.language == "auto"

    write_config(config_path, replace(config, web=replace(config.web, language="it")))
    assert load_config(config_path).web.language == "it"

    invalid = replace(config, web=replace(config.web, language="xx"))
    assert "web.language must be one of:" in "\n".join(validate_config(invalid))


def test_update_web_preferences_persists_language(tmp_path: Path) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        Path("python/config/config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    errors = update_web_preferences(
        config_path=config_path,
        web_enabled=None,
        web_host=None,
        web_port=None,
        show_chart_markers=None,
        visible_device_limit=None,
        appearance=None,
        default_chart_range=None,
        default_chart_metric=None,
        language="pt",
    )

    assert errors == []
    assert load_config(config_path).web.language == "pt"


def test_render_settings_html_includes_automatic_language_option() -> None:
    settings_html = render_settings_html(
        config=load_config(Path("python/config/config.toml.example")),
        snapshot={},
        devices=[],
        edit_mode=True,
        theme_preference="light",
        detected_bluetooth_adapters=[],
        usb_otg_device_controller_detected=False,
        usb_otg_boot_mode_prepared=False,
        usb_otg_support_installed=False,
    )

    assert 'value="auto" selected' in settings_html
    assert "Browser / system language" in settings_html


def test_rendered_pages_use_selected_language() -> None:
    home_html = render_home_html(
        snapshot={"devices": []},
        devices=[],
        chart_points=[],
        legend=[],
        language="fr",
    )
    settings_html = render_settings_html(
        config=load_config(Path("python/config/config.toml.example")),
        snapshot={},
        devices=[],
        edit_mode=True,
        theme_preference="light",
        language="it",
        detected_bluetooth_adapters=[],
        usb_otg_device_controller_detected=False,
        usb_otg_boot_mode_prepared=False,
        usb_otg_support_installed=False,
    )

    assert '<html lang="fr" dir="ltr">' in home_html
    assert "Vue d’ensemble de la batterie" in home_html
    assert '<html lang="it" dir="ltr">' in settings_html
    assert "Impostazioni" in settings_html
    assert "Lingua" in settings_html


def test_supported_locale_catalogs_warn_for_missing_rendered_page_text() -> None:
    pages = _representative_english_pages()
    for locale in SUPPORTED_LOCALES:
        if locale.code == "en":
            continue
        missing = sorted(
            {text for page in pages for text in missing_translations_for_html(page, locale.code)}
        )
        if missing:
            warnings.warn(
                (
                    f"{locale.code} catalog is missing {len(missing)} rendered UI "
                    f"translation{'s' if len(missing) != 1 else ''}: " + "; ".join(missing[:20])
                ),
                LocalizationWarning,
                stacklevel=1,
            )


def _representative_english_pages() -> list[str]:
    config = load_config(Path("python/config/config.toml.example"))
    device = {
        "id": "spare_nlp5",
        "type": "bm200",
        "name": "Spare NLP5",
        "mac": "AA:BB:CC:DD:EE:01",
        "connected": False,
        "voltage": 12.6,
        "soc": 86,
        "temperature": 22.3,
        "last_seen": "2026-04-24T11:26:14+02:00",
        "error_code": "timeout",
        "error_detail": "No BLE advertisement seen during the scan window.",
        "battery": {
            "family": "lithium",
            "profile": "lithium",
            "brand": "NOCO",
            "model": "NLP5",
            "nominal_voltage": 12,
            "capacity_ah": 5.0,
            "production_year": 2025,
        },
        "vehicle": {"installed": True, "type": "bench"},
        "installed_in_vehicle": True,
        "vehicle_type": "bench",
        "color_key": "green",
    }
    snapshot = {
        "generated_at": "2026-04-24T11:26:14+02:00",
        "gateway_name": "BMGateway",
        "mqtt_connected": True,
        "devices_online": 0,
        "devices_total": 1,
        "devices": [device],
    }
    raw_history = [
        {
            "ts": "2026-04-24T11:26:14+02:00",
            "voltage": 12.6,
            "soc": 86,
            "temperature": 22.3,
            "state": "normal",
            "error_code": None,
        }
    ]
    daily_history = [
        {
            "day": "2026-04-24",
            "samples": 1,
            "min_voltage": 12.6,
            "max_voltage": 12.6,
            "avg_voltage": 12.6,
            "avg_soc": 86,
            "avg_temperature": 22.3,
            "error_count": 0,
            "last_seen": "2026-04-24T11:26:14+02:00",
        }
    ]
    monthly_history = [
        {
            "month": "2026-04",
            "samples": 1,
            "min_voltage": 12.6,
            "max_voltage": 12.6,
            "avg_voltage": 12.6,
            "avg_soc": 86,
            "avg_temperature": 22.3,
            "error_count": 0,
        }
    ]
    yearly_history = [
        {"year": "2026", "samples": 1, "avg_voltage": 12.6, "avg_soc": 86, "error_count": 0}
    ]
    analytics: dict[str, object] = {
        "windows": [
            {
                "days": 7,
                "current_avg_voltage": 12.6,
                "previous_avg_voltage": 12.5,
                "delta_avg_voltage": 0.1,
                "current_avg_soc": 86,
                "previous_avg_soc": 82,
                "delta_avg_soc": 4,
            }
        ]
    }
    chart_points = [
        {
            "ts": "2026-04-24T11:26:14+02:00",
            "series": "Spare NLP5",
            "voltage": 12.6,
            "soc": 86,
            "temperature": 22.3,
        }
    ]
    legend = [("Spare NLP5", "#17c45a")]
    storage_summary: dict[str, object] = {
        "counts": {"gateway_snapshots": 1, "device_readings": 1, "device_daily_rollups": 1},
        "devices": [],
    }
    contract: dict[str, object] = {
        "gateway": {
            "state_topic": "bm_gateway/gateway/state",
            "discovery_topic": "homeassistant/device/bm_gateway/config",
        },
        "devices": [{"id": "spare_nlp5"}],
    }
    return [
        render_home_html(
            snapshot=snapshot,
            devices=[device],
            chart_points=chart_points,
            legend=legend,
        ),
        render_devices_html(snapshot=snapshot, devices=[device]),
        render_add_device_html(),
        render_edit_device_html(device=device),
        render_settings_html(
            config=config,
            snapshot=snapshot,
            devices=[device],
            edit_mode=False,
            storage_summary=storage_summary,
            contract=contract,
            detected_bluetooth_adapters=[{"name": "hci0"}],
            usb_otg_device_controller_detected=True,
            usb_otg_boot_mode_prepared=True,
            usb_otg_support_installed=True,
        ),
        render_settings_html(
            config=config,
            snapshot=snapshot,
            devices=[device],
            edit_mode=True,
            storage_summary=storage_summary,
            contract=contract,
            detected_bluetooth_adapters=[{"name": "hci0"}],
            usb_otg_device_controller_detected=True,
            usb_otg_boot_mode_prepared=True,
            usb_otg_support_installed=True,
        ),
        render_history_html(
            device_id="spare_nlp5",
            configured_devices=[device],
            raw_history=raw_history,
            daily_history=daily_history,
            monthly_history=monthly_history,
        ),
        render_device_html(
            device_id="spare_nlp5",
            raw_history=raw_history,
            daily_history=daily_history,
            monthly_history=monthly_history,
            yearly_history=yearly_history,
            analytics=analytics,
            device_summary=device,
        ),
        render_diagnostics_html(),
        render_frame_fleet_trend_html(
            chart_points=chart_points,
            legend=legend,
            show_chart_markers=False,
            appearance="light",
            default_chart_range="7",
            default_chart_metric="soc",
            width=480,
            height=234,
        ),
        render_frame_battery_overview_html(
            snapshot=snapshot,
            devices=[device],
            page=1,
            devices_per_page=5,
            appearance="light",
            width=480,
            height=234,
        ),
        render_reboot_pending_html(),
        render_shutdown_pending_html(),
        render_usb_otg_export_pending_html(),
    ]
