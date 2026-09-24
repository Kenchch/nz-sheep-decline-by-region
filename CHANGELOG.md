# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Each release lists corrections to
published findings first, because those are what a reader who cited an earlier
version needs to know.

## [Unreleased]

### Corrections to published findings

- The report said regional rankings closer than the ±0.7 million national
  sampling margin "are not distinguished", which would have left the whole top
  four unranked while the text still ranked them; that margin is national and
  belongs to one endpoint. The sentence now says regional sampling errors are
  not published, that Otago and Manawatū-Whanganui (0.4 percent apart) are not
  ranked against each other, and that the top-three share is 54.0 or 53.9
  percent depending on which of them is counted third.
- Figure 4's alternative text said sheep "falls throughout"; the flock was at or
  above its 2002 level until 2006. The text is now computed.
- Figure 1's title gives the 50.6 percent as a share of the 2002 flock *in the
  measurable regions*, not of the national flock, and its label sits beside the
  three bars it describes.
- `data-raw/SOURCE.md` no longer gives the 2017 South Island shortfall in head,
  which is an approximation of Nelson's withheld cell.

### Fixed

- Warnings raised in the hidden setup code or in inline expressions never
  reached the page, so the CI check for R warnings could not see them. The
  render now turns every warning into an error.
- The port's local check had no scenario for `value_iff_suppressed`; a flagged
  published value and an unflagged blank are now both quarantined.

## [0.3.0] - 2026-09-23

### Corrections to published findings

- **The headline had no base.** "Three regions account for over half of the
  fall" left out that the same three regions held 50.6 percent of the 2002
  flock across the measurable regions. They account for 54 percent of the
  fall, 3.4 points more than their size alone would give, and only Canterbury
  and Southland fell by more than their share. The README, the report and
  figure 1 now state both numbers, and each region's share of the fall is
  tabled against its share of the flock.
- **Otago is third by 15,971 head.** Manawatū-Whanganui is fourth, a difference
  of 0.4 percent of Otago's 2025 flock, and replaces Otago in the
  census-to-census window. The README had said that window gave "the same
  qualitative answer" without saying the list of three changed. The share is
  robust; the list is not, and both documents now say so.
- **"Nothing is withheld from 2002 to 2011" was wrong.** Before 2012 the export
  omits cells instead of flagging them. In 21 of the 22 class-years with a
  region missing and no flag, the published regions fall short of the national
  total, and every one of the 51 regional `C` cells of 2012 had been absent in
  at least one earlier year. The suppression chart now shows absent cells as a
  third category, and the report no longer reads the change of export format in
  2012 as a change in withholding. `census_year_reported` sees flagged cells
  only, so its 9 failures are a lower bound.
- **The README still described the `S` flag as running from 2014 and census
  years as sitting below the survey years around them**, after the report had
  corrected both (see below). The README is now checked
  against the report by CI (see Added).
- The 2002–2014 window is no longer called "the years of the steepest sheep
  decline": it had the larger absolute fall, but the annual rates of the two
  periods are almost the same (2.33 and 2.23 percent a year). 2014 is now
  described as the in-sample dairy peak it is, chosen after looking at the
  series.
- The census-year pattern in the `S` flag is described as "consistent with" the
  published rule rather than explained by it: it rests on 2 and 3 cells in two
  census years.
- The one-head residuals are no longer said to be possibly input perturbation:
  all of them are in 2008–2016, before perturbation was introduced. The
  unsourced claim that perturbation is "small relative to the effects discussed
  here" is removed.
- "Suppression now runs above ten percent of cells" is replaced by the computed
  "has exceeded ten percent in 2 of the last 4 years".
- "Adding all 44 codes gives 115.7 million against a published 33.8 million"
  compared a computed total with an unsourced one. Both totals are now computed
  from the extract (115.7 and 33.1 million).
- Figure 2's title, "Where sheep left, cattle mostly did not arrive in
  comparable numbers", led the reader to settle a question the report says
  head counts cannot settle; it is now descriptive, and the section opens with a
  direct answer. Its alternative text no longer says the cattle markers sit
  close to zero and then gives a 795 thousand dairy gain.
- Denominators are explained where they change: 15 regions for sheep, 13 for
  sheep and dairy together, and a 2014–2025 count of 14 that includes the
  Chatham Islands, which had no dairy cattle at either end.

From pull requests #15 to #17, merged before this release was cut:

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
- The top-three share is of the measurable regional fall, not "the total
  fall"; only one fully-published class-year falls strictly after 2017, so the
  sentence now says "in 2017 or later"; and codes 11-18 sum to code 19 within
  the source table's own rounding, not "exactly".
- The sensitivity claim is corrected (three start years are below 50%), gross
  regional losses are distinguished from the net fall, and regional versus
  national denominators and the scope of the imputation statistics are
  clarified. The cattle-chart alternative text is corrected and endpoints are
  selected by year name.
- The stock-unit paragraph no longer asserts that the dairy growth to 2014 was
  "of the same order" as the sheep decline in feed terms. 0.2.0 introduced
  that sentence while removing the one it could not source, but no
  stock-unit calculation was ever made and none is cited.

### Added

- A national index chart (2002 = 100) for sheep, dairy and beef cattle, so the
  three-window argument has a figure behind it.
- An end-year sensitivity table alongside the start-year one, and regional
  dairy counts for all three windows, including on the 13 regions measurable
  in all three. The table the key findings linked to had shown national totals
  for a different set of windows.
- `outputs/key-figures.csv`, written by the render, and
  `tests/test-readme-figures.R`, which fails if the README stops quoting any
  of those figures as rendered.
- `R/analysis.R` with the report's helpers as pure functions, and
  `tests/test-r-analysis.R`.
- Captions on every table, a glossary, and figure alternative text generated
  from the data.
- CI: checks that the extract, `SOURCE.md` and the Databricks default agree on
  the hash; that `DESCRIPTION`, `CITATION.cff` and this file agree on the
  version; that the page renders without R warnings and every figure exists;
  and a weekly scheduled run.
- The Databricks port now writes `quality_rule_summary`,
  `gold_national_change` and `gold_island_reconciliation`, and the local check
  compares them with the R outputs.

From pull requests #15 to #17, merged before this release was cut:

- `databricks/run_local.py` runs the three notebooks on a local Spark session
  and compares them with the committed `outputs/*.csv`; CI runs it and
  publishing waits on it.
- The port's `pyspark`/`pandas` pins move to `databricks/requirements.txt` and
  are watched by Dependabot. `_quarto.yml` names what to render. Pushes to
  `main` are no longer cancelled mid-publish.
- The Databricks port is named in `DATA-LICENCE.md` as code under MIT.

### Changed

- The README is restructured: findings, caveats, licence, how the numbers are
  checked, reproduction, layout, the port, and how it was built.
- The AI-use note is in the README itself. It had linked to a profile section
  that no longer exists, and it said the `Co-Authored-By` trailers had been
  removed from the history, which is true only of commits made before
  6 September 2026.
- **The Databricks quality gate has no reject-rate tolerance.** Any row breaking
  a blocking rule stops silver from being published, matching the R loader. With
  the old 1 percent tolerance a single quarantined Canterbury cell passed the
  gate and silently changed the headline's top three.
- Gold tables in the port store unrounded values, and the local check compares
  with a tolerance rather than by equality of rounded floats.
- Years, the region count and the comparison windows are named constants
  (`START_YEAR`, `END_YEAR`, `N_REGIONS`) instead of literals scattered through
  the R code, the report and the notebooks.
- The site is deployed from the artifact the verified build rendered, by a job
  that holds only Pages permissions and runs none of the project's code. It was
  previously re-rendered by a job holding a repository write token.
- Quarto and the runner image are pinned, and the port's Python dependencies
  are compiled with hashes and installed with `--require-hashes`. Dependabot
  waits seven days before proposing an update and does not propose pandas 3.
- CC BY 4.0 attribution links to the licence and says the data were adapted.
  Derived outputs and the report's text and figures are CC BY 4.0; the code
  stays MIT. `CITATION.cff` cites the Stats NZ data.

### Fixed

- `load_livestock()` accepted `0x1A`, `1.5`, `-5` and `1e3` as head counts; a
  head count must now be a non-negative whole number. The port applies the same
  rule.
- The loader's error messages name the offending values, years or keys, and it
  rejects an unexpected column, a different dataflow or a missing livestock
  code with a message saying so.
- `R/load.R` said it checked the hash recorded in `SOURCE.md` but compared a
  hard-coded copy. It now reads `SOURCE.md`, and hashes and parses the same
  bytes in one read.
- A suppressed national total had no test, and deleting that half of the guard
  passed every test. It is tested, and `R/checks.R` asserts one published
  total per class-year instead of summing.
- `residual_tiers` would have silently lost a class-year with no regional rows;
  it is now asserted to cover all 72. validate errors, warnings and NA results
  are refused rather than printed as passes.
- The island assignment is keyed by area code, not by position.
- The report's number formatting kept trailing zeros inconsistently and could
  print `-0.000`; empty selections no longer render as `-Inf`, and warnings are
  shown rather than suppressed.
- The port's notebooks validate their parameters, quote identifiers, re-hash
  the extract after reading it, and check that every gold table is complete.
  The local runner no longer injects `pyspark.sql.functions`, which had hidden
  a missing import.

From pull requests #15 to #17, merged before this release was cut:

- **The coverage assertion could not fail.** Its identity reduces to
  `17 == 17` for any table `load_livestock()` can return. The check that can
  fail — that the coverage table has a row for every expected year — was
  missing.
- `published` is no longer summed with `na.rm = TRUE`; a suppressed national
  total would have become `0`.
- **The reproducibility check could be satisfied by doing nothing.** The
  committed CSVs are now deleted before the run, and an uncommitted new output
  fails too.
- `data-raw/** -text` also covered `SOURCE.md`; narrowed to `data-raw/*.csv`.
- CSV parsing, year strings, finite head counts and published island totals are
  validated before the R analysis runs, with negative fixtures; CI fails when
  DESCRIPTION and renv.lock are out of sync.
- **The Databricks quality gate now fires.** `array_remove(..., None)` returned
  a null array, so every row's `broken_rules` was null and the quarantine was
  unreachable.
- **`suppressed` is a two-valued flag in silver.** `OBS_STATUS IN ('s', 'c')`
  was null on every published cell.
- Silver is the complement of the rejected rows under the same predicate, not
  `subtract`, which would also collapse duplicates.
- Databricks task parameters and the last good silver table are preserved when a
  quality gate fails; both PySpark suppression rates and their units match the
  R coverage table.

### Security

- Personal email addresses are removed from `.mailmap`; no commit on `main`
  uses them.

## [0.2.0] - 2026-09-08

- **The dairy comparison is reported per window, not at the endpoints alone.**
  0.1.0 said dairy and sheep moved in different directions on a scale that made
  the point on its own. Measured across the series that is misleading: the
  national dairy herd rose 1.54 million to a 2014 peak and has fallen 0.95
  million since, so the net 588 thousand is the difference between two larger
  opposite movements. Dairy fell alongside sheep in 7 of 13 regions over
  2002–2025, in only 4 of 15 over 2002–2014 and in 12 of 14 over 2014–2025.
- **The stock-unit paragraph says what could be checked.** Codes 6721/7187/7699
  are in the extract, but the extract carries no labels, so their meaning could
  not be confirmed and no conversion coefficients are asserted. A sentence
  attributing a conversion practice to Stats NZ was removed: it could not be
  found on the page it cited.
- Absent regions are separated from suppressed ones in the coverage output.

## [0.1.0] - 2026-09-07

- First public version: the regional reconciliation, five validation rules run
  against a deliberately corrupted copy, the three-tier reconciliation, and the
  Quarto report published by CI from a run that reproduced its own outputs.

[Unreleased]: https://github.com/Kenchch/nz-sheep-decline-by-region/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Kenchch/nz-sheep-decline-by-region/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Kenchch/nz-sheep-decline-by-region/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Kenchch/nz-sheep-decline-by-region/releases/tag/v0.1.0
