# Changelog

## Unreleased

- **The report claimed 10 class-years where all seventeen regions are published;
  there are 22.** Ten of those reconcile to the head, which is what the Exact
  tier counts. Both the report and the README said "the 10 class-years where all
  seventeen regions are published and nothing is withheld" and then, two
  sentences later, "12 further fully-published class-years" — a contradiction
  within the same paragraph. Completeness is checked *before* the residual; it is
  not what distinguishes Exact from the tier below it.
- **`data-raw/SOURCE.md` recorded the island reconciliation as "exact" for the
  one year it is not.** The pre-analysis check used sheep in 2017, the year
  Nelson's cell is withheld, leaving the South Island's eight regional codes
  19,568 head short of the published island total — a figure the report itself
  publishes in its Incomplete tier. The check now uses 2012, a year in which no
  region is withheld, and the 2017 behaviour is described rather than asserted
  away.
- Nelson and the Chathams hold the two smallest *livestock* populations, not the
  two smallest sheep populations: by sheep alone the second smallest is West
  Coast, which is published in 21 of the 24 years.
- The suppression figure's alt text described the `S` flag as running unbroken
  from 2014; there are no `S` cells in 2015 or 2016. The census-year comparison
  was overstated in the same way: 2022 sits below the survey years on either
  side of it, but 2017 sits above 2016, which is itself at zero.
- Three smaller corrections: the top-three share is of the measurable regional
  fall, not "the total fall"; only one fully-published class-year falls strictly
  after 2017, so the sentence now says "in 2017 or later"; and codes 11-18 sum
  to code 19 within the source table's own rounding, not "exactly".
- **The coverage assertion could not fail.** Its identity reduces to
  `17 == 17` for any table `load_livestock()` can return. The check that can
  fail — that the coverage table has a row for every expected year — was
  missing, so a year with no regional cells at all would have been dropped from
  the table that exists to report incompleteness.
- `published` is no longer summed with `na.rm = TRUE`. It is contractually a
  single non-missing cell; with `na.rm` a suppressed national total would have
  become `0` and the class-year would have been reported as a rounding
  discrepancy rather than as a missing total.
- **The reproducibility check could be satisfied by doing nothing.**
  `git diff --exit-code` compares the worktree to the index, so a `checks.R`
  that silently stopped writing left the committed CSVs untouched and passed.
  They are now deleted before the run, and an uncommitted new output fails too.
- `data-raw/** -text` also covered `SOURCE.md`, which needs no such protection
  and was already LF in the index and CRLF in the working tree. Narrowed to
  `data-raw/*.csv`, which is the file the hash gate protects.
- The port's `pyspark`/`pandas` pins move to `databricks/requirements.txt` and
  are watched by Dependabot; they were the only dependencies in the repository
  nothing was watching. `_quarto.yml` names what to render, instead of
  publishing every `.md` in the tree as an orphan page. Pushes to `main` are no
  longer cancelled mid-publish by the next push.

- Validate CSV parsing, year strings, finite head counts and published island
  totals before the R analysis runs. Negative fixtures exercise the ingestion
  contracts, and CI now fails when DESCRIPTION and renv.lock are out of sync.
- Preserve Databricks task parameters and the last good silver table when a
  quality gate fails. Quarantine malformed values and years under ANSI mode,
  and test failure paths as well as the successful R/PySpark comparison.
- Align both PySpark suppression rates and their units with the R coverage
  table; dashboards must format the returned fractions as percentages.
- Correct the report's sensitivity claim (three start years are below 50%),
  distinguish gross regional losses from the net fall, and clarify regional
  versus national denominators and the scope of the imputation statistics.
  Correct the cattle-chart alternative text and select endpoints by year name.

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
