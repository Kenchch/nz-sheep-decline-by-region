# Changelog

## Unreleased

- **The Databricks quality gate now fires.** `array_remove(..., None)` returns
  a null array in Spark rather than an array with the nulls removed, so every
  row's `broken_rules` was null, the rule summary was empty and the quarantine
  could never receive a row. The nulls are now dropped with `filter`, and the
  summary shows the same nine `census_year_reported` failures as the R
  validation table.
- **`suppressed` is a two-valued flag in silver.** `OBS_STATUS IN ('s', 'c')`
  is null when `OBS_STATUS` is null, which it is on every published cell, so
  the flag was `true` or `null` and every rule and assertion that read it
  passed by evaluating to null. It is now coalesced to `false`, and
  `gold_coverage` counts zero suppressed regions for 2002–2016 instead of null.
- Silver is the complement of the rejected rows under the same predicate, not
  `subtract`, which is `EXCEPT DISTINCT` and would also collapse duplicates.
- `databricks/run_local.py` runs the three notebooks on a local Spark session
  and asserts that silver and every gold table agree with the committed
  `outputs/*.csv`. CI runs it alongside the R reproduction on every pull
  request and every push to `main`, and publishing now waits on both.
- The stock-unit paragraph no longer asserts that the dairy growth to 2014 was
  "of the same order" as the sheep decline in feed terms. 0.2.0 introduced
  that sentence while removing the one it could not source, but no
  stock-unit calculation was ever made and none is cited, so the claim had
  nothing behind it.
- The Databricks port is named in `DATA-LICENCE.md` as code under MIT.

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
