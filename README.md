# Where New Zealand's sheep went: a regional breakdown of the flock decline, 2002–2025

New Zealand's sheep flock fell by 16.32 million head between June 2002 and June 2025, and three regions account for over half of that fall.

**[Read the full release →](https://kenchch.github.io/nz-sheep-decline-by-region/)**

![Contribution of each region to the national fall in sheep numbers, 2002 to 2025](outputs/figures/01-regional-contribution.png)

## Key findings

- Canterbury, Southland and Otago together account for **54 percent** of the fall measured across the 15 regions with both endpoints published. Against the published national fall the same three regions are 53.6 percent; the published fall is 0.77 percent larger than the measurable regional one, because Auckland and Nelson are withheld in 2025.
- Over the same 23 years the national dairy herd grew by only **588 thousand** cattle against a fall of 16.3 million sheep — two different orders of magnitude, which is the arithmetic the "sheep became dairy" story has to survive.
- In **7 of the 13** regions where both series are published, dairy cattle fell *alongside* sheep rather than in place of them. Canterbury has the largest absolute dairy increase by far (795 thousand head, 22 per 100 sheep lost); West Coast has the higher ratio at 39 per 100, but on a base under 40 thousand sheep.

## Data quality checks

Five rules run over the analysis table, and the same five run against a deliberately corrupted copy of it — because an all-green table cannot tell a reader whether the rules are sound or merely too loose to fire.

| Rule | Fails on real data | Fails on corrupted copy |
|---|---:|---:|
| `head_non_negative` | 0 | 1 |
| `value_iff_suppressed` | 0 | 1 |
| `region_label_present` | 0 | 1 |
| `no_duplicate_cells` | 0 | 2 |
| `census_year_reported` | **9** | 10 |

Each corruption moves exactly one rule. `no_duplicate_cells` moves by two because a duplicate makes both members of the pair non-unique; `census_year_reported` moves from 9 to 10 because it already fails nine times on the real data.

`census_year_reported` fires 9 times on the real data, and that is a finding rather than a defect: a census is full coverage with no sampling error, yet census-year cells are still withheld, because withholding is about confidentiality and imputation quality rather than coverage. The rule earns its place by being falsified.

The reconciliation separates into three tiers across the 72 class-years:

| Tier | Class-years | Largest absolute residual |
|---|---:|---:|
| Exact — all 17 regions published, nothing withheld | 10 | 0 head |
| Fully published, off by a few head | 12 | 2 head |
| Incomplete region row | 50 | 558,310 head |

Completeness is the criterion for these tiers, not the residual: 11 class-years reconcile to zero, one more than the Exact tier holds, because one incomplete class-year happens to reconcile exactly anyway.

In the 10 fully-published class-years the regions sum to the published national total **exactly, to the head**. In 12 further fully-published class-years the residual never exceeds two head, on bases of 3.5–31.1 million — which the report does not attribute, because it cannot from published data. Every residual above that (the next smallest is 507 head) belongs to a year with a withheld region or an absent region code.

Those one-head discrepancies are not an artefact of the analysis: adding the two *published* island totals and comparing against the *published* national total — three aggregate cells this analysis never sums — gives a one-head difference in 14 of the 72 class-years. The discrepancy lives in the published table, not in the join.

Suppression is also not one thing. The `OBS_STATUS` column carries two different flags, and separating them turns an apparent anomaly into confirmation of the published method:

- **`C`, confidentiality.** Among the three livestock classes used here it appears only in 2012; across all 44 livestock codes in the extract it appears in 2012–2016 and **never after 2016**. Stats NZ states that `C` was used prior to 2017 and that confidentiality has since been implemented by input perturbation instead, so cells no longer need replacing with `C`. The file stops using the flag in the same year the method changed.
- **`S`, quality suppression** — applied where sampling errors **or** imputation levels are high. Runs from 2014 to 2025 and peaks at 17.6 percent of cells in 2021. Census years sit below the survey years around them but not at zero: a census removes the sampling-error branch, which is why they are lower, while the imputation branch remains, which is why they are not empty. All five census-year `S` cells are Nelson.

The 2012 spike is therefore not a quality problem at all: all four withheld cells that year are `C`, not `S`. Whether the absence of any flag before 2012 means "nothing withheld" or "flag not carried in this export" cannot be determined from the extract, and the report says so.

One of the two dropped regions is explained in the methodology rather than guessed at: sampling error could not be calculated for Nelson because only one responding unit was observed per sampled stratum. Auckland is simply withheld, with no reason published.

![Share of regional cells suppressed, by year](outputs/figures/03-suppression-rate.png)

## Data source and licence

Stats NZ table `AGR_AGR_003`, *Livestock Numbers by Regional Council*, dataflow `STATSNZ:AGR_AGR_003(1.0)`, final vintage, downloaded 2026-09-04 and committed with its SHA-256. Full provenance in [`data-raw/SOURCE.md`](data-raw/SOURCE.md).

> Source data: Stats NZ, Agricultural production statistics, licensed by Stats NZ for re-use under the Creative Commons Attribution 4.0 International licence.

Code in this repository is MIT licensed ([`LICENSE`](LICENSE)); the `data-raw/`
extract stays under CC BY 4.0. Both are set out in
[`DATA-LICENCE.md`](DATA-LICENCE.md).

Every methodological statement in the report was read on its source page before being written down; the [report lists which page each one came from](https://kenchch.github.io/nz-sheep-decline-by-region/#sources-for-the-methodological-statements). Claims that could not be sourced there are not made.

## Method

1. **One table, one vintage** — downloaded once, committed with its hash. A pipeline that re-queries the API on every run would silently change its own answers at the next release.
2. **Codes verified before code was written** — the extract carries numeric codes and no labels. The three livestock codes used were each confirmed against published June 2024 national figures. The codelist holds 44 nested entries; adding all 44 gives 115.7 million animals against a published 33.8 million.
3. **Aggregates separated, not summed** — `AREA` 10, 19 and 20 are island and national totals. They are flagged and excluded from every regional sum.
4. **Suppressed cells stay suppressed** — `NA` plus a flag, never zero, never dropped. Two regions are excluded from the change calculation for missing an endpoint, and are counted in the text.
5. **Reconciliation reported, not asserted** — no fixed tolerance. The residual is computed for every year and published.
6. **Numbers are computed, cited, or explicitly rounded, and the report says which** — figures derived from the data are inline expressions evaluated at render time; figures from Stats NZ's methodology (sample size, response rate, imputation level, the GST threshold) cannot be computed from an aggregate extract and are typed with an attribution; figures in the plain-language layer are rounded, with the exact value further down the page.

## Limitations

- Non-census years are sample estimates. Sampling errors are not recomputed and no weighting is applied here; a movement in a single small region should not be read as real change.
- Imputation is large: Stats NZ reports 30 percent of the 2025 total sheep estimate as imputed, against a 3 percent relative sampling error. Every survey-year regional figure carries that.
- All comparisons are ratios of head counts. They say nothing about stocking rate, feed demand, land use or emissions.
- The target population is GST-registered agricultural businesses, so coverage of the smallest farms is partial and not quantifiable from published data.
- **The two endpoints are different collection designs**: 2002 is a census, 2025 a sample survey, so a full-coverage count is differenced against an estimate carrying sampling error and 30 percent imputation. The design-matched window — 2002 to 2022, census to census — gives a fall of 14.4 million head across 16 measurable regions with the top three at 55.6 percent: the same qualitative answer. The report says why the 2025 endpoint is used anyway.
- **The start year changes *which* regions lead, not *how concentrated* they are.** Recomputed from all 19 available start years, the three largest decliners always account for 48–59 percent of the fall. Which three they are rotates: Manawatū-Whanganui appears in 17 of the 19 windows, Southland in 16, Otago in 14, and Canterbury in only 9. Canterbury leads the window this report uses because its decline is concentrated in the early years — it is not a permanent feature of the data.
- No map is drawn, deliberately: a choropleth encodes land area rather than magnitude, and the three largest contributors are also among the largest regions by area.

## Reproduce

Requirements: R >= 4.1 (for the native pipe), the Quarto CLI, and the R packages `readr`, `dplyr`, `tidyr`, `janitor`, `validate`, `digest`, `ggplot2`, `scales`, `knitr` and `rmarkdown`.

```bash
git clone https://github.com/Kenchch/nz-sheep-decline-by-region.git
cd nz-sheep-decline-by-region
Rscript R/checks.R    # regenerates outputs/*.csv
quarto render         # regenerates the report and outputs/figures/*.png
```

Both sets of outputs are committed. A clean checkout that runs those commands
must reproduce the CSVs exactly; figures are regenerated too, but their binary
bytes can differ with the platform's fonts and graphics device. `R/load.R`
verifies the extract against the SHA-256 in `SOURCE.md` before reading it and
stops if they disagree.

GitHub Actions runs the same regeneration on every push and pull request, fails
if any committed CSV differs, and publishes the report to GitHub Pages from that
same green run — so the live page is always the output of a build that
reproduced its own outputs. It renders the figures too, but does not compare
their bytes, because graphics differ across platforms. Ingestion stops on schema
changes, unknown suppression flags, duplicate cells, missing years, or missing
national totals, so a changed source shape cannot silently produce
plausible-looking results.

The check paid for itself on its first run, by failing: the pinned extract
arrives with CRLF line endings and the recorded SHA-256 is the hash of those
bytes, but Git had normalised them to LF on commit, so the hash gate passed on
Windows and would have stopped every clone on Linux or macOS. Dependencies are
declared once in [`DESCRIPTION`](DESCRIPTION), which the workflow reads.

```
index.qmd                 the published report
R/load.R                  hash gate, read, label, isolate withheld cells
R/checks.R                five rules, the corrupted-copy demo, both reconciliations
data-raw/                 the pinned extract and its provenance
outputs/                  analysis table, validation summaries, reconciliations, figures
```

Region names follow the Statistical standard for geographic areas 2023 (SSGA23); the extract itself publishes numeric codes and no labels.

Figures in this README are transcribed from the report. The report is the source of truth — every number in it is computed at render time.
