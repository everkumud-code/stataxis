# StatAxis picture and PDF design

`reference.png` is the design reference (owner's, 14 Oct 2026). Every image (posts, picture cards, the comparison chart, the table card) and every PDF uses only this:

| Part | Value |
|---|---|
| Background | near-black `#010509`, faint dot grid, a soft blue glow at the top left, a thin arc with one bright dot at the right edge |
| Headline | white `#fdfdfd`, heavy condensed capitals (Anton / Bebas Neue / Impact) |
| Numbers and accents | electric blue `#0b8ded` (deep `#0b52b1`, light `#5fb4ff`) |
| Body text | `#ccd5dd`; labels `#9ba0a6`; rules `#255073` |
| Line to remember | blue italic serif (Instrument Serif / Georgia) |
| Label | spaced monospace with a blue dot: `FIG. 00 - SYMPTOMS` |
| Logo | blue ring, gold arrow, blue wordmark, gold tagline: `dashboard/assets/stataxis-logo-dark.svg` (a vector redraw of the reference) |
| Footer | `stataxis.org · x.com/stataxis - Stat the View. Axis the Viewpoint.` with the logo at the right |

Code: `dashboard/sxdesign.js` (pictures), `api/report_pdf.py` (PDF pages). Change the look there and nowhere else.
