# Design system (Part 6)

The visual direction is inspired by Elbe Flugzeugwerke (EFW), as requested: a technical,
modern aerospace look with white pages, dark navy navigation, cyan accents and a clean
sans-serif typeface.

**Independence.** The app is an independent educational project. It uses **no EFW logo,
imagery or other brand assets** and does not imply affiliation or sponsorship; the footer
says so on every page.

## Values taken from EFW's public CSS (inspected 2026-10-16)

Values come from `https://www.elbeflugzeugwerke.com/assets/css/efw-website.css`, counted by
frequency of use. The careers portal `jobs.efw.aero` uses SAP SuccessFactors custom fonts
that cannot be identified, so it was not used for tokens.

| Token | Value | Use in EFW CSS | Use here |
|---|---|---|---|
| `--color-navy` | `#001450` | 87 uses; primary coloured areas | Navigation, headings, primary bars |
| `--color-cyan` | `#00A0D1` | 81 uses; secondary coloured areas | Accents, active states, links, highlights |
| `--color-tint` | `#F1F1F5` | 24 uses; tinted sections | Section and table backgrounds |
| `--color-ink` | `#2D2D2C` | 14 uses; text | Body text |
| `--color-warn` | `#FF9800` | 8 uses | Warnings, missing-percentage bars |
| `--color-danger` | `#A80A00` | 7 uses | Errors, inconsistent values |
| `--color-ok` | `#029F80` | 3 uses | Supported, passed |
| Font | "Titillium Web" | 14 declarations | Whole UI, loaded from Google Fonts (SIL Open Font Licence) |
| Skew | `--skew-angle: 28` | Diagonal design element | Diagonal cyan band in page headers (`.skew-band`) |

The tokens are defined in `frontend/src/index.css` (`@theme`, Tailwind CSS 4).

## Components and conventions

- **Badges.** Role (passenger / production freighter / converted freighter), flight-model
  support, source type and verification status.
- **Missing values** are shown as grey italic "unavailable" (with "no verified source in
  the database" in tables), never as 0 or as an empty bar.
- **Inconsistent values** are struck through on a red tint. Open model data use an amber
  badge; published specifications use a navy badge.
- **Glossary terms** have a dotted cyan underline and a book icon; hovering or focusing
  shows the definition.
- **Diagrams** are schematic, labelled SVGs with a caption stating "schematic, not to
  scale" and their basis.
- **Aircraft silhouettes** are generated from body type and engine count and labelled
  "no licensed photograph".
- **Charts** (Recharts) have animations disabled, which keeps rendering reproducible and
  avoids motion. Partial subtotals are always labelled.
- **Accessibility.** Semantic landmarks, `aria-label`/`aria-pressed`/`aria-expanded`,
  keyboard-focusable glossary popovers, and colour never used as the only carrier of meaning.
