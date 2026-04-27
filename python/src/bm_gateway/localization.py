"""Locale catalog loading and HTML localization helpers."""

from __future__ import annotations

import html
import json
import re
import warnings
from dataclasses import dataclass
from html.parser import HTMLParser
from importlib import resources
from typing import Final


@dataclass(frozen=True)
class LocaleInfo:
    code: str
    name: str
    native_name: str
    direction: str = "ltr"


SUPPORTED_LOCALES: Final[tuple[LocaleInfo, ...]] = (
    LocaleInfo("en", "English", "English"),
    LocaleInfo("zh-Hans", "Chinese (Simplified)", "简体中文"),
    LocaleInfo("hi", "Hindi", "हिन्दी"),
    LocaleInfo("es", "Spanish", "Español"),
    LocaleInfo("ar", "Arabic", "العربية", "rtl"),
    LocaleInfo("fr", "French", "Français"),
    LocaleInfo("bn", "Bengali", "বাংলা"),
    LocaleInfo("pt", "Portuguese", "Português"),
    LocaleInfo("ru", "Russian", "Русский"),
    LocaleInfo("ur", "Urdu", "اردو", "rtl"),
    LocaleInfo("de", "German", "Deutsch"),
    LocaleInfo("it", "Italian", "Italiano"),
)

AUTO_LOCALE: Final = "auto"
_SUPPORTED_BY_CODE: Final = {locale.code: locale for locale in SUPPORTED_LOCALES}
_LANGUAGE_ALIASES: Final = {
    "zh": "zh-Hans",
    "zh-cn": "zh-Hans",
    "zh-sg": "zh-Hans",
    "pt-br": "pt",
    "pt-pt": "pt",
}
_VOID_TAGS: Final = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_SKIP_TAGS: Final = {"script", "style", "textarea", "code", "pre"}
_TRANSLATABLE_ATTRIBUTES: Final = {
    "aria-label",
    "placeholder",
    "title",
    "alt",
    "onsubmit",
    "data-label",
    "data-range-label",
}
_DYNAMIC_TRANSLATION_PREFIXES: Final = (
    ("Gateway: ", "Gateway"),
    ("Devices online: ", "Devices online"),
    ("MQTT connected: ", "MQTT connected"),
    ("Validation failed: ", "Validation failed"),
    ("History sync completed: ", "History sync completed"),
    ("History sync failed: ", "History sync failed"),
    ("Run failed: ", "Run failed"),
    ("USB OTG frame image export failed: ", "USB OTG frame image export failed"),
    (
        "Home Assistant discovery republish failed: ",
        "Home Assistant discovery republish failed",
    ),
    ("Failed to restart bm-gateway service: ", "Failed to restart bm-gateway service"),
    ("Failed to restart Bluetooth service: ", "Failed to restart Bluetooth service"),
    ("Failed to prepare USB OTG boot mode: ", "Failed to prepare USB OTG boot mode"),
    ("Failed to restore USB host boot mode: ", "Failed to restore USB host boot mode"),
    ("Failed to refresh USB OTG drive: ", "Failed to refresh USB OTG drive"),
    ("Detected adapters: ", "Detected adapters"),
    ("Edit Device ", "Edit Device"),
    ("Serial / MAC: ", "Serial / MAC"),
    ("Open details for ", "Open details for"),
    ("Battery Overview · Latest: ", "Battery Overview · Latest"),
    ("Fleet Trend · ", "Fleet Trend"),
    ("Latest sample ", "Latest sample"),
    ("Use gateway poll interval (", "Use gateway poll interval"),
    ("Temperature ", "Temperature"),
    ("Voltage ", "Voltage"),
)
_IGNORED_TEXT_PATTERNS: Final = (
    re.compile(r"^/[-A-Za-z0-9._:/?=&%#<>]+$"),
    re.compile(r"^[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)+$"),
    re.compile(r"^(?:Etc/)?GMT[+-]\d+$"),
    re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$"),
    re.compile(r"^[A-F0-9:]{8,}$"),
    re.compile(r"^v?\d+(?:[.:]\d+)*(?: .*)?$"),
    re.compile(r"^[A-Za-z0-9._-]+$"),
)
_IGNORED_TRANSLATION_VALUES: Final = {
    "BMGateway",
    "MQTT",
    "Home Assistant",
    "Bluetooth",
    "SoC",
    "BM200",
    "BM6",
    "BM7",
    "BM900",
    "BM900 Pro",
    "BM300",
    "BM300 Pro",
    "bm200",
    "bm6",
    "bm7",
    "bm900",
    "bm900pro",
    "bm300pro",
    "hci0",
    "fake",
    "live",
    "auto",
    "JPEG",
    "PNG",
    "BMP",
    "Auto",
    "Primary",
    "Bench",
    "Spare NLP5",
    "Spare NLP20",
    "NOCO NLP5 12 V 5.0 Ah",
    "NOCO NLP20 12 V 20.0 Ah",
    "NOCO NLP5 12 V 5.0 Ah 2025",
    "NOCO NLP20 12 V 20.0 Ah 2025",
    "bmgw_frame",
    "config.toml",
    "devices.toml",
    "homeassistant",
    "mqtt-user",
    "mqtt.local",
    "normal",
    "timeout",
    "unlimited",
}
_catalog_cache: dict[str, dict[str, str]] = {}
_warned_missing: set[tuple[str, str]] = set()


class LocalizationWarning(UserWarning):
    """Warning raised when a locale catalog is missing visible UI text."""


@dataclass(frozen=True)
class Translation:
    locale: LocaleInfo
    catalog: dict[str, str]

    def gettext(self, text: str) -> str:
        if self.locale.code == "en":
            return text
        return self.catalog.get(text, text)


def supported_locale_codes() -> tuple[str, ...]:
    return tuple(locale.code for locale in SUPPORTED_LOCALES)


def allowed_language_codes() -> tuple[str, ...]:
    return (AUTO_LOCALE, *supported_locale_codes())


def locale_options() -> tuple[tuple[str, str], ...]:
    return ((AUTO_LOCALE, "Browser / system language"),) + tuple(
        (locale.code, f"{locale.native_name} ({locale.name})") for locale in SUPPORTED_LOCALES
    )


def normalize_locale(value: str | None) -> str:
    raw_value = (value or "").strip().replace("_", "-")
    if not raw_value:
        return "en"
    normalized = _LANGUAGE_ALIASES.get(raw_value.lower(), raw_value)
    if normalized in _SUPPORTED_BY_CODE:
        return normalized
    language_part = normalized.split("-", 1)[0].lower()
    if language_part in _SUPPORTED_BY_CODE:
        return _LANGUAGE_ALIASES.get(language_part, language_part)
    return "en"


def is_supported_locale(value: str) -> bool:
    return value in _SUPPORTED_BY_CODE


def is_supported_language_preference(value: str) -> bool:
    return value == AUTO_LOCALE or is_supported_locale(value)


def resolve_locale_preference(configured_language: str, accept_language: str | None) -> str:
    if configured_language != AUTO_LOCALE:
        return normalize_locale(configured_language)
    for language_range in _accept_language_ranges(accept_language):
        locale = normalize_locale(language_range)
        if locale != "en" or language_range.lower().startswith("en"):
            return locale
    return "en"


def is_rtl_locale(value: str) -> bool:
    return _SUPPORTED_BY_CODE[normalize_locale(value)].direction == "rtl"


def translation_for(value: str | None) -> Translation:
    code = normalize_locale(value)
    return Translation(locale=_SUPPORTED_BY_CODE[code], catalog=_load_catalog(code))


def localize_html(document: str, locale: str | None) -> str:
    translation = translation_for(locale)
    if translation.locale.code == "en":
        return _localized_html_root(document, translation)
    _warn_about_missing_translations(document, translation)
    parser = _LocalizingHTMLParser(translation)
    parser.feed(document)
    parser.close()
    return parser.output


def missing_translations_for_html(document: str, locale: str | None) -> tuple[str, ...]:
    translation = translation_for(locale)
    if translation.locale.code == "en":
        return ()
    collector = _SourceTextCollector()
    collector.feed(document)
    collector.close()
    missing = {
        value
        for value in collector.values
        if _is_translation_candidate(value)
        and value not in translation.catalog
        and not _has_translated_dynamic_prefix(value, translation.catalog)
    }
    return tuple(sorted(missing))


def _load_catalog(code: str) -> dict[str, str]:
    if code == "en":
        return {}
    cached = _catalog_cache.get(code)
    if cached is not None:
        return cached
    catalog_path = resources.files("bm_gateway.locales").joinpath(f"{code}.json")
    with catalog_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Locale catalog {catalog_path} must contain a JSON object.")
    catalog = {str(key): str(value) for key, value in data.items()}
    _catalog_cache[code] = catalog
    return catalog


def _warn_about_missing_translations(document: str, translation: Translation) -> None:
    missing = [
        value
        for value in missing_translations_for_html(document, translation.locale.code)
        if (translation.locale.code, value) not in _warned_missing
    ]
    if not missing:
        return
    for value in missing:
        _warned_missing.add((translation.locale.code, value))
    preview = "; ".join(missing[:8])
    suffix = "" if len(missing) <= 8 else f"; and {len(missing) - 8} more"
    warnings.warn(
        (
            f"missing {len(missing)} {translation.locale.name} translation"
            f"{'' if len(missing) == 1 else 's'}: {preview}{suffix}"
        ),
        LocalizationWarning,
        stacklevel=3,
    )


def _is_translation_candidate(value: str) -> bool:
    text = value.strip()
    if not text or text in _IGNORED_TRANSLATION_VALUES:
        return False
    if not re.search(r"[A-Za-z]{3,}", text):
        return False
    if any(pattern.fullmatch(text) for pattern in _IGNORED_TEXT_PATTERNS):
        return False
    if "NOCO" in text or text.startswith("Spare "):
        return False
    if any(marker in text for marker in ("/home/", "/var/", "://")):
        return False
    return True


def _has_translated_dynamic_prefix(value: str, catalog: dict[str, str]) -> bool:
    return any(
        value.startswith(prefix) and key in catalog for prefix, key in _DYNAMIC_TRANSLATION_PREFIXES
    )


class _SourceTextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []
        self._skip_depth = 0
        self._translate_disabled_depth = 0
        self._translate_disabled_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if _LocalizingHTMLParser._has_translate_no(attrs):
            self._translate_disabled_depth += 1
            self._translate_disabled_tags.append(tag)
        for name, value in attrs:
            if value is not None and name in _TRANSLATABLE_ATTRIBUTES:
                confirm_message = _confirm_message_from_attribute(name, value)
                self._add(confirm_message if confirm_message is not None else value)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if self._translate_disabled_tags and self._translate_disabled_tags[-1] == tag:
            self._translate_disabled_tags.pop()
            self._translate_disabled_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and not self._translate_disabled_depth:
            self._add(data)

    def _add(self, value: str) -> None:
        text = " ".join(value.split())
        if text:
            self.values.append(text)


def _accept_language_ranges(value: str | None) -> tuple[str, ...]:
    ranges: list[tuple[float, int, str]] = []
    for index, part in enumerate((value or "").split(",")):
        language_range = part.strip()
        if not language_range:
            continue
        language, quality = _parse_accept_language_part(language_range)
        if language != "*" and quality > 0:
            ranges.append((quality, -index, language))
    ranges.sort(reverse=True)
    return tuple(language for _quality, _index, language in ranges)


def _parse_accept_language_part(value: str) -> tuple[str, float]:
    pieces = [piece.strip() for piece in value.split(";") if piece.strip()]
    language = pieces[0]
    quality = 1.0
    for piece in pieces[1:]:
        if not piece.startswith("q="):
            continue
        try:
            quality = float(piece.removeprefix("q="))
        except ValueError:
            quality = 0.0
    return language, max(0.0, min(1.0, quality))


def _localized_html_root(document: str, translation: Translation) -> str:
    direction = translation.locale.direction
    return document.replace(
        '<html lang="en">',
        f'<html lang="{translation.locale.code}" dir="{direction}">',
        1,
    )


class _LocalizingHTMLParser(HTMLParser):
    def __init__(self, translation: Translation) -> None:
        super().__init__(convert_charrefs=False)
        self._translation = translation
        self._pieces: list[str] = []
        self._skip_depth = 0
        self._translate_disabled_depth = 0
        self._translate_disabled_tags: list[str] = []

    @property
    def output(self) -> str:
        return "".join(self._pieces)

    def handle_decl(self, decl: str) -> None:
        self._pieces.append(f"<!{decl}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if self._has_translate_no(attrs):
            self._translate_disabled_depth += 1
            self._translate_disabled_tags.append(tag)
        self._pieces.append(self._start_tag(tag, attrs, closed=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._pieces.append(self._start_tag(tag, attrs, closed=True))

    def handle_endtag(self, tag: str) -> None:
        self._pieces.append(f"</{tag}>")
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if self._translate_disabled_tags and self._translate_disabled_tags[-1] == tag:
            self._translate_disabled_tags.pop()
            self._translate_disabled_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._translate_disabled_depth:
            self._pieces.append(data)
            return
        self._pieces.append(self._translate_preserving_outer_space(data))

    def handle_entityref(self, name: str) -> None:
        self._pieces.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._pieces.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._pieces.append(f"<!--{data}-->")

    def _start_tag(self, tag: str, attrs: list[tuple[str, str | None]], *, closed: bool) -> str:
        rendered_attrs: list[str] = []
        for name, value in attrs:
            if tag == "html" and name == "lang":
                value = self._translation.locale.code
            elif tag == "html" and name == "dir":
                value = self._translation.locale.direction
            elif value is not None and name in _TRANSLATABLE_ATTRIBUTES:
                value = self._translate_attribute(value)
            if value is None:
                rendered_attrs.append(name)
            else:
                rendered_attrs.append(f'{name}="{html.escape(value, quote=True)}"')
        if tag == "html" and not any(name == "dir" for name, _value in attrs):
            rendered_attrs.append(f'dir="{self._translation.locale.direction}"')
        suffix = " /" if closed and tag not in _VOID_TAGS else ""
        attrs_text = (" " + " ".join(rendered_attrs)) if rendered_attrs else ""
        return f"<{tag}{attrs_text}{suffix}>"

    def _translate_attribute(self, value: str) -> str:
        confirm_message = _confirm_message_from_attribute("onsubmit", value)
        if confirm_message is not None:
            translated = self._translation.gettext(confirm_message)
            if translated == confirm_message:
                translated = self._translate_dynamic_text(confirm_message)
            return f"return confirm('{translated}')"
        translated = self._translation.gettext(value)
        if translated == value:
            translated = self._translate_dynamic_text(value)
        return translated

    def _translate_preserving_outer_space(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            return value
        translated = self._translation.gettext(stripped)
        if translated == stripped:
            translated = self._translate_dynamic_text(stripped)
        prefix_length = len(value) - len(value.lstrip())
        suffix_length = len(value) - len(value.rstrip())
        return f"{value[:prefix_length]}{translated}{value[len(value) - suffix_length :]}"

    def _translate_dynamic_text(self, value: str) -> str:
        for prefix, catalog_key in _DYNAMIC_TRANSLATION_PREFIXES:
            if value.startswith(prefix):
                translated_prefix = self._translation.gettext(catalog_key)
                if prefix.endswith(": "):
                    return f"{translated_prefix}: {value[len(prefix) :]}"
                if prefix.endswith(" · "):
                    return f"{translated_prefix} · {value[len(prefix) :]}"
                if prefix.endswith("("):
                    return f"{translated_prefix} ({value[len(prefix) :]}"
                return translated_prefix + " " + value[len(prefix) :]
        return value

    @staticmethod
    def _has_translate_no(attrs: list[tuple[str, str | None]]) -> bool:
        return any(name == "translate" and value == "no" for name, value in attrs)


def _confirm_message_from_attribute(name: str, value: str) -> str | None:
    prefix = "return confirm('"
    suffix = "')"
    if name != "onsubmit" or not value.startswith(prefix) or not value.endswith(suffix):
        return None
    return value[len(prefix) : -len(suffix)]
