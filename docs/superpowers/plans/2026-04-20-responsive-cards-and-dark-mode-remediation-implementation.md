# Responsive Cards and Dark Mode Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the battery card hierarchy, fix shared one-card layout behavior, and make dark mode coherent across Battery, History, Devices, and Settings.

**Architecture:** Keep the current server-rendered structure and fix the problem at the shared template and CSS-token layer. Add regression tests for the HTML and CSS contracts first, then adjust `web.py` markup and `web_ui.py` sizing/tokens so the same shared components render well at desktop and mobile breakpoints.

**Tech Stack:** Python, pytest, server-rendered HTML helpers, shared CSS in `python/src/bm_gateway/web_ui.py`

---

## File Map

- Modify: `python/src/bm_gateway/web.py`
  - tighten battery card markup and one-card layout hooks
  - reduce history selector card verbosity where needed
- Modify: `python/src/bm_gateway/web_ui.py`
  - dark-mode tokens, card sizing, mobile battery-card sizing, shared grid behavior, control contrast
- Modify: `python/tests/test_web_management.py`
  - add regression coverage for new CSS/HTML contracts
- Modify: `CHANGELOG.md`
  - record the remediation batch
- Modify: `web/README.md`
  - keep the web component docs aligned with the shared card/theme behavior

### Task 1: Lock the Regressions With Failing Tests

**Files:**

- Modify: `python/tests/test_web_management.py`
- Verify against: `python/src/bm_gateway/web.py`, `python/src/bm_gateway/web_ui.py`

- [ ] **Step 1: Write failing tests for the battery-card and dark-mode contracts**

Add tests that assert:

- the battery card exposes a single-card layout hook
- the mobile CSS reduces badge size while increasing gauge emphasis
- dark mode defines distinct elevated surfaces instead of light-mode white cards
- the history selector and devices layouts expose compact/single-card hooks

Use tests in the style already present near the battery/history CSS assertions.

- [ ] **Step 2: Run the focused test slice to verify it fails**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k "single_card or mobile_badge or dark_surface or history_layout"
```

Expected:

- at least one failure tied to missing CSS/HTML hooks or outdated token values

- [ ] **Step 3: Do not touch production code until the failures are confirmed**

The failures from Step 2 are the proof that the tests cover the regression.

### Task 2: Fix Shared Layout Hooks in the HTML

**Files:**

- Modify: `python/src/bm_gateway/web.py`
- Test: `python/tests/test_web_management.py`

- [ ] **Step 1: Add explicit one-card and compact-layout hooks**

Update rendering so Battery, History, and Devices expose stable classes for:

- one-card battery overview state
- one-card history selector state
- one-card devices grid state, if needed

Keep changes minimal and markup-focused.

- [ ] **Step 2: Run the focused HTML test slice**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k "single_card or history_layout"
```

Expected:

- the new layout-hook tests pass
- existing battery/history render tests remain green

### Task 3: Rebuild Shared CSS for Card Sizing and Mobile Battery Hierarchy

**Files:**

- Modify: `python/src/bm_gateway/web_ui.py`
- Test: `python/tests/test_web_management.py`

- [ ] **Step 1: Adjust the single-card and small-fleet layout rules**

Implement CSS that:

- centers or constrains one-card states intentionally
- avoids stretched empty desktop layouts
- keeps the Add Device tile subordinate to real battery cards

- [ ] **Step 2: Fix the battery card hierarchy at desktop and mobile breakpoints**

Implement CSS that:

- enlarges the gauge
- shrinks the badge on narrow screens
- keeps the badge away from the gauge
- tightens the card copy spacing without crowding the button

- [ ] **Step 3: Run the focused battery CSS test slice**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k "battery_html or battery_badge or mobile_badge or single_card"
```

Expected:

- battery layout and CSS-contract tests pass

### Task 4: Rebuild Dark Mode and Shared Control Contrast

**Files:**

- Modify: `python/src/bm_gateway/web_ui.py`
- Test: `python/tests/test_web_management.py`

- [ ] **Step 1: Replace the dark-mode surface tokens**

Implement a coherent dark palette with separate:

- page background
- header surface
- section/card surface
- chart/control surface

- [ ] **Step 2: Raise contrast for controls and supporting text**

Adjust:

- segmented controls
- legend text
- chart meta text
- helper copy
- buttons and badges

- [ ] **Step 3: Run the dark-mode focused test slice**

Run:

```bash
uv run pytest -q python/tests/test_web_management.py -k "theme_preference or dark_surface or badge_treatment or appearance"
```

Expected:

- dark-mode token tests and theme-threading tests pass

### Task 5: Refresh Docs and Run Full Verification

**Files:**

- Modify: `CHANGELOG.md`
- Modify: `web/README.md`

- [ ] **Step 1: Update docs for the remediation batch**

Record:

- responsive battery-card cleanup
- one-card layout cleanup
- improved dark-mode surface hierarchy and contrast

- [ ] **Step 2: Run markdown lint on changed Markdown**

Run:

```bash
markdownlint --config .markdownlint.json CHANGELOG.md web/README.md docs/superpowers/specs/2026-04-20-responsive-cards-and-dark-mode-remediation-design.md docs/superpowers/plans/2026-04-20-responsive-cards-and-dark-mode-remediation-implementation.md
```

Expected:

- no markdownlint findings

- [ ] **Step 3: Run the full maintainer gate**

Run:

```bash
make check
```

Expected:

- full success, including pytest, Ruff, mypy, markdownlint, and shellcheck

- [ ] **Step 4: Deploy and live-verify**

Run:

```bash
make dev-deploy TARGET=admin@host
ssh admin@host 'systemctl is-active bm-gateway.service bm-gateway-web.service'
```

Then capture fresh desktop and mobile screenshots of:

- `/`
- `/history`
- `/devices`
- `/settings?edit=1`

Expected:

- services active
- visual regressions reduced in both light and dark appearances
