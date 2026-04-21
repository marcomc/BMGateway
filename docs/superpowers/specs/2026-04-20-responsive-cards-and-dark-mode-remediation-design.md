# Responsive Cards and Dark Mode Remediation Design

## Scope

This spec defines the remediation batch for the visual regressions introduced by
the recent battery-card and theme work.

It covers:

- responsive battery-card layout on desktop and mobile
- shared single-card and small-fleet layout behavior across Battery, History,
  and Devices
- proper dark-mode surface, text, and control contrast
- shared controls and settings density adjustments where the regressions are now
  visible

It does not cover:

- barcode scanning
- new navigation flows
- new settings fields beyond the existing `Appearance` preference

## Goals

- Restore the state-of-charge gauge as the primary visual element of the battery
  card.
- Keep the icon badge visible without shrinking the card's main status content.
- Make one-card and two-card states look intentional instead of sparse or
  stretched.
- Bring dark mode in line with Apple's guidance for adaptive appearance,
  contrast, and surface hierarchy.
- Remove the latest shared visual regressions from Battery, History, Devices,
  and Settings in one batch.

## Non-Goals

- No brand-new visual language for the whole product.
- No separate template system for light and dark mode.
- No new product features or route changes.
- No attempt to make the Raspberry Pi web UI mimic native iOS components
  literally; the target is web UI with Apple-quality dark-mode discipline.

## Design Decisions

### 1. Battery Card Layout

The battery card must return to a gauge-first hierarchy.

Required behavior:

1. The SoC gauge becomes materially larger than it is now.
2. The icon badge remains in the top-left corner but scales down on narrow
   screens.
3. The badge must not force the gauge to shrink.
4. The gauge contains only:
   - percentage
   - battery status
   - voltage
5. Device name and metadata remain outside the gauge.
6. The card layout must adapt by breakpoint instead of relying on one static
   composition for every width.

Desktop direction:

- centered large gauge
- small corner badge
- identity and metadata stacked below

Mobile direction:

- badge reduced in size
- larger gauge relative to card width
- tighter copy spacing
- action button remains easy to tap without dominating the card

### 2. Shared Card Width Behavior

The current single-card layouts leave too much dead space on desktop and stretch
 content unnaturally on some pages.

Required behavior:

1. Battery overview single-page states should size to the real number of cards
   while still feeling centered and intentional.
2. History and Devices should not render one small content block inside an
   oversized full-width card area.
3. Shared grid logic must distinguish:
   - one-card state
   - two-card state
   - multi-card state
4. The `Add Device` tile must stay visually subordinate to real device status
   cards.

### 3. Dark Mode

Dark mode must be treated as a first-class appearance, not a token inversion.

Required behavior:

1. Use distinct base and elevated surfaces instead of bright white cards on a
   dark background.
2. Increase foreground contrast for titles, body copy, legends, helper text,
   and segmented controls.
3. Keep the same semantic structure in both themes:
   - page background
   - header surface
   - section surface
   - chart/control surface
4. Icons, pills, and buttons must use dark-mode-specific tokens rather than
   relying on the light palette.
5. `System` appearance must still resolve correctly from browser or OS
   preference.

Guidance basis:

- Apple Human Interface Guidelines for Dark Mode, Color, and Layout
- adaptive colors
- clear surface hierarchy
- sufficient text and control contrast

### 4. Shared Controls and Settings Density

The latest changes made several controls too faint or too fragmented.

Required behavior:

1. Range pills, metric pills, legend text, and helper copy must remain readable
   in dark mode.
2. Settings sections should keep the current structure but reduce the
   spreadsheet-like feeling where possible through spacing, contrast, and
   grouping improvements.
3. Save actions should remain explicit, but section density should feel lighter
   and more coherent.

## UX Rules

- Battery cards must remain legible at phone width around `390px`.
- The badge may never overlap the gauge.
- The gauge must remain the first thing the eye reads on the battery card.
- One-device states must not look unfinished.
- Dark mode must feel intentionally designed, not like a light page with the
  body darkened.
- Add-action cards must not compete with real device status.

## Acceptance Criteria

- On mobile, the battery-card badge is visibly smaller than on desktop.
- On mobile and desktop, the gauge is larger than the current implementation.
- The battery card reads cleanly in both light and dark appearance.
- The Battery page no longer leaves a large empty right-side void for the
  current one-device state.
- History and Devices no longer show tiny information clusters inside oversized
  stretched cards.
- Dark mode uses coherent surface colors and readable control/text contrast
  across Battery, History, Devices, and Settings.
- The `Add Device` card is visually subordinate to the real battery card.

## Risks

- Shared layout fixes can accidentally change more pages than intended if the
  grid primitives are not carefully bounded.
- Dark-mode improvements can regress light mode if tokens are not clearly
  separated.
- Increasing gauge size can crowd card metadata unless spacing is rebalanced at
  the same time.

## Recommended Implementation Order

1. Rework shared dark-mode tokens and surface hierarchy.
2. Refactor shared card/grid sizing for one-card and two-card states.
3. Rebuild the battery card at desktop and mobile breakpoints.
4. Apply the same layout cleanup to History and Devices.
5. Retune chart controls and settings density under the new tokens.
6. Run full checks, deploy, and verify with fresh desktop and mobile
   screenshots.
