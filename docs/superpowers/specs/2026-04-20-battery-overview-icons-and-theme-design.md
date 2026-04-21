# Battery Overview, Icons, and Theme Design

## Scope

This spec defines the next UI refinement batch for the BMGateway web interface:

- battery overview card layout revision
- icon system redesign for better visibility on light and dark themes
- appearance setting with `Light`, `Dark`, and `System` modes
- history device selector card refinement

This spec does not cover implementation of barcode scanning, multi-device history
comparison, or broader navigation changes outside these surfaces.

## Goals

- Make the battery overview card easier to read on a light theme.
- Remove visual competition between the SoC circle and the device identity.
- Replace weak outline icons with theme-aware, high-contrast icons.
- Introduce a durable appearance model that supports future dark theme work.
- Make history device selection identify the battery clearly with compact cards.

## Non-Goals

- No full visual redesign of the entire application.
- No theme-specific asset pipeline beyond what is needed for icon visibility.
- No change to the main interaction model of `Device Details`.
- No new backend API surface beyond what the settings page and templates require.

## Design Decisions

### 1. Battery Overview Card

The battery overview card keeps the SoC circle as the dominant focal element,
but the icon moves out of the circle.

Required layout:

1. A small visual badge sits in the top-left corner of the card.
2. The SoC circle stays centered and contains only charge-critical data:
   - state of charge percentage
   - battery status text
   - battery voltage
3. Device identity and metadata stay below the circle:
   - device name
   - installation context
   - temperature
   - battery identity summary
4. `Device Details` remains the explicit action button.
5. The icon badge is decorative only and does not navigate anywhere.

Rationale:

- The previous layout overloaded the SoC circle with identity information.
- The icon badge supports recognition without competing with the percentage.
- Keeping the action separate is clearer on mobile.

### 2. Icon System

The current icon treatment is not strong enough on light cards because the icon
uses line art inside a pale badge.

Required icon direction:

1. Replace weak outline icons with filled, higher-contrast glyphs.
2. Light theme icons use dark foregrounds on soft tinted badge backgrounds.
3. Dark theme icons use light foregrounds on darker tinted badge backgrounds.
4. Icons must remain recognizable at small sizes.
5. The same icon family must be used consistently across:
   - battery overview cards
   - history selector cards
   - device pages where small badges are appropriate

Rationale:

- Icons must remain legible without relying on heavy shadows or large sizes.
- A single icon family keeps the UI coherent as theme support expands.

### 3. Appearance Setting

The web UI gains an appearance preference in settings.

Required values:

- `Light`
- `Dark`
- `System`

Required behavior:

1. The setting appears in editable settings.
2. The current saved preference appears in non-edit mode.
3. `System` follows browser or OS preference via `prefers-color-scheme`.
4. The effective mode must be reflected in the document or body state in a way
   that CSS can target reliably.
5. Icon rendering must support both light and dark appearance modes.

Rationale:

- Theme selection is a user preference, not a temporary UI toggle.
- `System` is necessary for mobile and desktop consistency.

### 4. History Device Selector

The history selector should use compact recognition cards instead of
information-heavy cards.

Required content:

1. Small icon badge
2. Device name
3. Battery identity summary

Preferred battery identity summary:

- battery brand and model when present
- battery chemistry or profile when that adds clarity

Example:

- `NOCO NLP5 · lithium`

Installation context such as `Bench / stationary battery` should not be the
primary secondary line in this selector.

Rationale:

- History selection is about choosing the right battery data stream quickly.
- Battery identity is a better disambiguator than installation context.

## UX Rules

- On light theme cards, text and icons must remain readable without relying on
  subtle white-on-white contrast.
- On mobile widths, the icon badge must not overlap the SoC circle.
- The battery card should still read well when the device is offline or has no
  recent sample.
- The selector cards on the history page should remain compact and tappable.

## Settings and Data Model

The settings surface must add an appearance preference under web/display
settings or another clearly justified canonical settings section.

The implementation may extend the existing web configuration model with an
appearance key. The accepted values must match the UI exactly:

- `light`
- `dark`
- `system`

## Technical Direction

- Prefer CSS variables and a clear theme root selector over scattered per-rule
  overrides.
- Avoid duplicating icon assets when a theme-aware SVG or CSS-driven approach
  can serve both light and dark modes cleanly.
- Keep the battery card template focused; do not reintroduce overlapping
  identity content inside the SoC circle.
- Reuse the same compact icon badge component in both overview cards and
  history selector cards.

## Acceptance Criteria

- The battery overview icon is shown as a top-left badge and is not inside the
  SoC circle.
- The SoC circle contains percentage, status, and voltage only.
- The battery overview icon is clearly visible on the light theme.
- The icon system supports both light and dark appearances.
- Settings expose `Light`, `Dark`, and `System`.
- Non-edit settings show the saved appearance preference.
- The history selector shows compact cards with icon, device name, and battery
  identity summary.
- The battery overview remains mobile-safe and does not reintroduce overlap.

## Risks

- Theme work can spread too widely if the change is not scoped to canonical
  variables and shared components.
- Icon redesign can drift into decorative inconsistency if each page uses a
  different visual treatment.
- History selector cards can become noisy again if too much metadata is added.

## Recommended Implementation Order

1. Add appearance preference to config, settings UI, and theme root handling.
2. Redesign the shared icon badge and theme-aware icon treatment.
3. Refactor battery overview cards around the approved layout.
4. Refactor history selector cards to use the compact recognition model.
5. Run full regression checks and deploy to the gateway for live validation.
