# Changelog

## 0.2.0 — 2026-09-08

- **The dairy comparison is reported per window, not at the endpoints alone.**
  0.1.0 said dairy and sheep moved in different directions on a scale that made
  the point on its own. Measured across the series that is misleading: the
  national dairy herd rose 1.54 million to a 2014 peak and has fallen 0.95
  million since, so the net 588 thousand is the difference between two larger
  opposite movements. Dairy fell alongside sheep in 7 of 13 regions over
  2002–2025, in only 4 of 15 over 2002–2014 — the years of the steepest sheep
  decline — and in 12 of 14 over 2014–2025. The direction depends on the
  window, so all three are reported. Every count is computed at render time
  from the same table, so none can drift from the data.
- **The stock-unit paragraph says what could be checked.** Codes 6721/7187/7699
  are in the extract, but the extract carries no labels, so their meaning could
  not be confirmed and no conversion coefficients are asserted. A sentence
  attributing a conversion practice to Stats NZ was removed: it could not be
  found on the page it cited.
- Absent regions are separated from suppressed ones in the coverage output.

## 0.1.0 — 2026-09-07

- First public version: the regional reconciliation, five validation rules run
  against a deliberately corrupted copy, the three-tier reconciliation, and the
  Quarto report published by CI from a run that reproduced its own outputs.
