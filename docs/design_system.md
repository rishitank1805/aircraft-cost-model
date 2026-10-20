# Design system (Part 6)

A technical, modern look: white pages, dark navy navigation, cyan accents and a clean
sans-serif typeface.

**Independence.** The explorer is an independent educational project. It is not
affiliated with, sponsored or endorsed by any company, and uses no third-party logos,
imagery or brand assets. External links go only to official public-agency sources (FAA,
NASA, BTS, BLS, EU institutions). Company sources of data values are shown as plain-text
source names, without links or URLs. The full provenance stays in the database.

## Tokens (`frontend/src/index.css`, Tailwind CSS 4 `@theme`)

| Token | Value | Use |
|---|---|---|
| `--color-navy` | `#001450` | Navigation, headings, primary bars |
| `--color-cyan` | `#00A0D1` | Accents, active states, links, highlights |
| `--color-tint` | `#F1F1F5` | Section and table backgrounds |
| `--color-ink` | `#2D2D2C` | Body text |
| `--color-warn` | `#FF9800` | Warnings |
| `--color-danger` | `#A80A00` | Errors, inconsistent values |
| `--color-ok` | `#029F80` | Supported, passed |
| Font | Titillium Web | Whole UI, loaded from Google Fonts (SIL Open Font Licence) |
| Diagonal band | `.skew-band` | Page headers |

## Components and conventions

- **Badges.** Role (passenger / production freighter / converted freighter), flight-model
  support, source type and verification status.
- **Missing values** are shown as grey italic "unavailable" (in tables, "no verified
  source in the database"), never as 0 or as an empty bar.
- **Inconsistent values** are struck through on a red tint. Open model data use an amber
  badge; published specifications use a navy badge.
- **Glossary terms** have a dotted cyan underline and a book icon; hovering or focusing
  shows the definition.
- **Diagrams** are schematic, labelled SVGs with a "schematic, not to scale" caption.
  Aircraft silhouettes are generated from body type and engine count; no photographs.
- **Charts** (Recharts) have animations disabled. Partial subtotals are always labelled.
- **Accessibility.** Semantic landmarks, `aria-label`/`aria-pressed`/`aria-expanded`,
  keyboard-focusable glossary popovers, and colour never used as the only carrier of meaning.
