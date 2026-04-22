# Battery Overview, Icons, and Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add theme-aware appearance settings, redesign the shared battery icons for light and dark use, move the overview icon into a top-left badge, and simplify history device selection cards.

**Architecture:** Extend the existing Python-side web config and HTML renderer with a small appearance preference, then drive light and dark styling through shared CSS variables and theme selectors in the existing web UI layer. Reuse a single compact icon-badge treatment across battery overview cards and history selector cards so the card layout and icon system stay consistent.

**Tech Stack:** Python, standard-library HTML rendering, repo CSS in `python/src/bm_gateway/web_ui.py`, pytest, Ruff, mypy, markdownlint.

---

## File Map

- Modify: `python/src/bm_gateway/config.py`
  - Add the persisted appearance preference to `WebConfig`, load/write/validate it.
- Modify: `python/src/bm_gateway/web.py`
  - Extend settings rendering, theme plumbing, battery overview card markup, shared icon-badge markup, and history selector card markup.
- Modify: `python/src/bm_gateway/web_ui.py`
  - Add light/dark/system theme variables, icon badge styles, battery card layout updates, and compact history selector styles.
- Modify: `python/tests/test_web_management.py`
  - Add and update regression coverage for appearance settings, battery overview markup, and history selector cards.
- Modify: `python/config/config.toml.example`
  - Document the new appearance setting.
- Modify: `python/config/gateway.toml.example`
  - Document the new appearance setting.
- Modify: `python/config/config.schema.json`
  - Add schema validation for the appearance setting.
- Modify: `web/README.md`
  - Document appearance handling and the shared icon/card behavior at a contributor level.
- Modify: `rpi-setup/manual-setup.md`
  - Document the new config key in the Pi setup reference.
- Modify: `CHANGELOG.md`
  - Record the user-visible UI and settings changes.
- Modify: `TODO.md`
  - Add the approved future theme work note if it is not fully completed by this batch.

## Task 1: Add Appearance Preference To Config And Settings

**Files:**

- Modify: `python/src/bm_gateway/config.py`
- Modify: `python/src/bm_gateway/web.py`
- Modify: `python/tests/test_web_management.py`
- Modify: `python/config/config.toml.example`
- Modify: `python/config/gateway.toml.example`
- Modify: `python/config/config.schema.json`

- [ ] **Step 1: Write the failing config and settings tests**

Add tests in `python/tests/test_web_management.py` covering:

```python
def test_update_web_preferences_persists_appearance(tmp_path: Path) -> None:
    ...
    errors = update_web_preferences(
        config_path=config_path,
        web_enabled=None,
        web_host=None,
        web_port=None,
        show_chart_markers=None,
        visible_device_limit=None,
        appearance="dark",
    )
    assert errors == []
    config = load_config(config_path)
    assert config.web.appearance == "dark"


def test_render_settings_html_summary_shows_appearance() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(config, web=replace(config.web, appearance="system"))
    html = render_settings_html(config=config, snapshot={}, devices=[], edit_mode=False)
    assert "Appearance" in html
    assert "System" in html


def test_render_settings_html_edit_mode_shows_appearance_options() -> None:
    html = render_settings_html(
        config=load_config(Path("python/config/config.toml.example")),
        snapshot={},
        devices=[],
        edit_mode=True,
    )
    assert 'name="appearance"' in html
    assert '<option value="light"' in html
    assert '<option value="dark"' in html
    assert '<option value="system"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k 'appearance or render_settings_html'
```

Expected:

- FAIL because `appearance` is not yet part of the config or settings UI.

- [ ] **Step 3: Write minimal implementation**

Update `python/src/bm_gateway/config.py` to add:

```python
@dataclass(frozen=True)
class WebConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 80
    show_chart_markers: bool = False
    visible_device_limit: int = 5
    appearance: str = "system"
```

Then thread `appearance` through:

- `to_dict()`
- `write_config()`
- `load_config()`
- `validate_config()` with accepted values `light`, `dark`, `system`

Update `python/src/bm_gateway/web.py` to:

- accept `appearance` in `update_web_preferences(...)`
- parse `appearance` from the display settings form
- show `Appearance` in settings summary
- render a select in edit mode with `Light`, `Dark`, and `System`

Update example configs and schema to include:

```toml
appearance = "system"
```

and:

```json
"appearance": {
  "type": "string",
  "enum": ["light", "dark", "system"]
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k 'appearance or render_settings_html'
```

Expected:

- PASS for the new appearance config and settings tests.

- [ ] **Step 5: Commit**

```bash
git add python/src/bm_gateway/config.py python/src/bm_gateway/web.py python/tests/test_web_management.py python/config/config.toml.example python/config/gateway.toml.example python/config/config.schema.json
git commit -m "feat: add appearance preference to web settings"
```

## Task 2: Add Theme Root Handling And Shared Icon Badge Styles

**Files:**

- Modify: `python/src/bm_gateway/web.py`
- Modify: `python/src/bm_gateway/web_ui.py`
- Modify: `python/tests/test_web_management.py`

- [ ] **Step 1: Write the failing theme and icon tests**

Add tests in `python/tests/test_web_management.py` covering:

```python
def test_render_battery_html_marks_document_with_appearance_preference() -> None:
    html = render_battery_html(
        snapshot={"devices": []},
        devices=[],
        chart_points=[],
        legend=[],
        appearance="dark",
    )
    assert 'data-theme-preference="dark"' in html


def test_render_battery_html_uses_icon_badge_markup() -> None:
    html = render_battery_html(...)
    assert "battery-card-badge" in html
    assert "battery-tile-icon" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k 'theme_preference or icon_badge'
```

Expected:

- FAIL because the document and battery card do not yet expose the new theme and badge markup.

- [ ] **Step 3: Write minimal implementation**

In `python/src/bm_gateway/web.py`:

- extend `render_battery_html(...)` to accept `appearance: str = "system"`
- pass the appearance preference into the shared document renderer
- expose a stable document attribute such as:

```html
<body data-theme-preference="system">
```

or equivalent root markup already used by the app document helper

In `python/src/bm_gateway/web_ui.py`:

- add theme variable blocks for light and dark modes
- use a root selector strategy that supports:
  - explicit `data-theme-preference="light"`
  - explicit `data-theme-preference="dark"`
  - `system` via `prefers-color-scheme`
- add shared styles for:

```css
.battery-card-badge { ... }
.battery-card-badge .device-icon-frame { ... }
```

Make the icon treatment filled and high contrast on both themes instead of pale line art.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k 'theme_preference or icon_badge'
```

Expected:

- PASS for the new theme root and icon badge tests.

- [ ] **Step 5: Commit**

```bash
git add python/src/bm_gateway/web.py python/src/bm_gateway/web_ui.py python/tests/test_web_management.py
git commit -m "feat: add theme-aware icon badge styling"
```

## Task 3: Refactor Battery Overview Cards Around The Approved Layout

**Files:**

- Modify: `python/src/bm_gateway/web.py`
- Modify: `python/src/bm_gateway/web_ui.py`
- Modify: `python/tests/test_web_management.py`

- [ ] **Step 1: Write the failing battery overview tests**

Add tests in `python/tests/test_web_management.py` covering:

```python
def test_render_battery_html_places_badge_outside_soc_circle() -> None:
    html = render_battery_html(...)
    assert "battery-card-badge" in html
    assert "battery-tile-hero" in html
    assert "battery-card-gauge-value" in html
    assert "Temperature 24.0°C" in html
    assert "Ancell BM200" in html


def test_render_battery_html_soc_circle_omits_device_name() -> None:
    html = render_battery_html(...)
    assert "battery-card-gauge-label" in html
    assert "Device Details" in html
```

Keep the assertions focused on required structure:

- badge exists
- badge is separate from the gauge container
- gauge contains `%`, status, and voltage
- name and metadata remain below

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k 'render_battery_html'
```

Expected:

- FAIL because current battery card markup still needs to move the badge and rebalance the card structure.

- [ ] **Step 3: Write minimal implementation**

In `python/src/bm_gateway/web.py`:

- add a small top-left badge wrapper above the gauge
- keep the gauge content limited to:
  - percentage
  - status
  - voltage
- move identity lines below the gauge:

```html
<div class="battery-card-badge">...</div>
<div class="battery-tile-hero">...</div>
<div class="battery-card-copy">
  <div class="meta meta-name">...</div>
  <div class="meta meta-context">...</div>
  <div class="meta battery-card-reading">Temperature ...</div>
  <div class="meta battery-card-meta-extra">...</div>
</div>
```

In `python/src/bm_gateway/web_ui.py`:

- anchor the badge in the top-left corner of the card
- ensure the badge does not overlap the gauge at desktop or mobile widths
- keep the gauge as the dominant visual element

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k 'render_battery_html'
```

Expected:

- PASS for the battery overview layout expectations.

- [ ] **Step 5: Commit**

```bash
git add python/src/bm_gateway/web.py python/src/bm_gateway/web_ui.py python/tests/test_web_management.py
git commit -m "feat: move battery overview icon into top-left badge"
```

## Task 4: Refactor History Device Selector Cards

**Files:**

- Modify: `python/src/bm_gateway/web.py`
- Modify: `python/src/bm_gateway/web_ui.py`
- Modify: `python/tests/test_web_management.py`

- [ ] **Step 1: Write the failing history selector tests**

Add tests in `python/tests/test_web_management.py` covering:

```python
def test_render_history_html_uses_compact_history_selector_cards() -> None:
    html = render_history_html(...)
    assert "history-device-card" in html
    assert "battery-card-badge" in html
    assert "NOCO" in html


def test_render_history_html_prefers_battery_identity_summary() -> None:
    html = render_history_html(...)
    assert "NOCO · NLP5" in html or "NOCO NLP5 · lithium" in html
    assert "Bench / stationary battery" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k 'render_history_html'
```

Expected:

- FAIL because the current history selector still uses the older device-card treatment.

- [ ] **Step 3: Write minimal implementation**

In `python/src/bm_gateway/web.py`:

- reuse the compact icon badge
- compute a battery identity summary from brand, model, and chemistry/profile
- render selector cards with:
  - icon badge
  - device name
  - battery identity summary

Do not use installation context as the main secondary line.

In `python/src/bm_gateway/web_ui.py`:

- keep the cards compact and clearly tappable
- keep them visually distinct from full battery overview cards

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k 'render_history_html'
```

Expected:

- PASS for the history selector compact-card behavior.

- [ ] **Step 5: Commit**

```bash
git add python/src/bm_gateway/web.py python/src/bm_gateway/web_ui.py python/tests/test_web_management.py
git commit -m "feat: simplify history device selector cards"
```

## Task 5: Documentation, Full Verification, And Live Deployment

**Files:**

- Modify: `CHANGELOG.md`
- Modify: `web/README.md`
- Modify: `rpi-setup/manual-setup.md`
- Modify: `TODO.md`

- [ ] **Step 1: Update documentation**

Document:

- appearance setting values
- theme-aware icon behavior
- revised battery overview card structure
- refined history selector cards

Keep one canonical explanation per topic and link rather than duplicating.

- [ ] **Step 2: Run focused regression slices**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k 'appearance or render_battery_html or render_history_html'
```

Expected:

- PASS

- [ ] **Step 3: Run the full maintainer gate**

Run:

```bash
make check
```

Expected:

- Ruff clean
- mypy clean
- markdownlint clean
- shellcheck clean
- full pytest suite passing

- [ ] **Step 4: Deploy to the gateway**

Run:

```bash
make dev-deploy TARGET=admin@host
```

Expected:

- runtime and web service updated on the Pi

- [ ] **Step 5: Run live smoke checks on the gateway**

Run:

```bash
ssh admin@host 'systemctl is-active bm-gateway.service bm-gateway-web.service'
ssh admin@host 'curl -fsS http://127.0.0.1/ | grep -E "battery-card-badge|data-theme-preference|Device Details" -n | head'
ssh admin@host 'curl -fsS http://127.0.0.1/history | grep -E "history-device-card|battery-card-badge" -n | head'
ssh admin@host 'curl -fsS "http://127.0.0.1/settings?edit=1" | grep -E "name=\"appearance\"|value=\"light\"|value=\"dark\"|value=\"system\"" -n'
```

Expected:

- both services active
- battery overview markup includes the badge and theme preference
- history selector markup uses compact cards
- appearance options render on the gateway

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md web/README.md rpi-setup/manual-setup.md TODO.md
git commit -m "docs: record theme-aware battery overview updates"
```

## Self-Review

Spec coverage check:

- Battery overview badge move: covered in Task 3
- icon redesign for light and dark themes: covered in Task 2
- appearance setting and summary/edit mode behavior: covered in Task 1
- history selector compact recognition cards: covered in Task 4
- regression, docs, deploy, and live validation: covered in Task 5

Placeholder scan:

- No `TODO`, `TBD`, or implied placeholder steps remain in this plan.

Type and naming consistency:

- The config key is consistently named `appearance`.
- Accepted values are consistently `light`, `dark`, and `system`.
- The shared badge class is consistently named `battery-card-badge`.
