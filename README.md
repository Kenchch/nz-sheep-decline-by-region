# Where New Zealand's sheep went: a regional breakdown of the flock decline, 2002–2025

New Zealand's sheep flock fell by about 16.3 million head (41 percent) between June 2002 and June 2025, and the fall was spread across the regions roughly in proportion to where the sheep were.

**[Read the full report →](https://kenchch.github.io/nz-sheep-decline-by-region/)**

![Horizontal bar chart of the 15 regions with both endpoints published, ordered by sheep lost between 2002 and 2025. Canterbury lost 3.57 million head, Southland 2.91 million and Otago 2.27 million, drawn darker; together 54 percent of the fall across these regions, against 50.6 percent of their 2002 flock. Manawatū-Whanganui is fourth at 2.25 million. A tick on each bar marks the fall at the 41.3 percent average rate.](outputs/figures/01-regional-contribution.png)

## Key findings

- **The flock fell by about 16.3 million head (41 percent).** The 2025 figure is a sample-survey estimate; at Stats NZ's 3 percent relative sampling error, the end point alone is uncertain by about ±0.7 million head.
- **The fall tracks where the sheep were.** Across the 15 regions measurable at both ends (published in 2002 and in 2025), Canterbury, Southland and Otago held 50.6 percent of the 2002 flock and account for **54 percent** of the fall. Only Canterbury and Southland fell by more than their share. Otago and Manawatū-Whanganui are all but tied for third, 15,971 head apart, so the share is robust and the list of three is not.
- **Dairy rose, then fell.** The national dairy herd changed by +1.54 million (29.8 percent) to a 2014 peak and by −0.95 million since: +0.59 million net. Dairy fell alongside sheep in only **4 of 15** regions over 2002–2014 and in **12 of 14** over 2014–2025 (7 of 13 over the whole period). Each count is out of the regions with both sheep and dairy published at both ends of its own window, so the denominators differ; the 14 includes the Chatham Islands, which had no dairy cattle at either end. Head counts cannot say whether dairy replaced sheep in feed or land terms.

## Caveats

- **Head counts only.** A dairy cow and a sheep are not exchangeable units; nothing here is a stock-unit, land-use or emissions comparison.
- **Census against survey.** 2002 is a census; 2025 is a sample survey with 30 percent of the sheep estimate imputed. The census-to-census window, 2002–2022, gives a fall of 14.4 million head with the top three at 55.6 percent, but Manawatū-Whanganui replaces Otago in the three.
- **Withheld and absent cells.** Auckland and Nelson are withheld in 2025, so the regional shares use the measurable regional fall; the published national fall is 0.77 percent larger, and the same three regions account for 53.6 percent against the published national fall. Before 2012 the export leaves cells out instead of flagging them. The data come as 72 class-years (3 classes × 24 years); in 21 of the 22 with a region missing and no flag, the regions fall short of the national total, so an absent row is not a zero.

Across start years from 2002 to 2020 the three largest declines take 48–59 percent of the gross regional fall, below half for 2008, 2009 and 2010 starts. The report sets out the start- and end-year sensitivity in full.

## Data and licence

Stats NZ table `AGR_AGR_003`, *Livestock Numbers by Regional Council*, dataflow `STATSNZ:AGR_AGR_003(1.0)`, final vintage, downloaded 2026-09-04 and committed with its SHA-256. Full provenance in [`data-raw/SOURCE.md`](data-raw/SOURCE.md).

> This work is based on Stats NZ's data (*Agricultural production statistics*, `AGR_AGR_003`), licensed by Stats NZ for re-use under the [Creative Commons Attribution 4.0 International licence](https://creativecommons.org/licenses/by/4.0/). The tables and figures in `outputs/` and the report are aggregated and reshaped from that data.

Code is MIT licensed ([`LICENSE`](LICENSE)). The `data-raw/` extract, the derived files in `outputs/` and the report's text and figures are CC BY 4.0. Details in [`DATA-LICENCE.md`](DATA-LICENCE.md).

Region names follow the Statistical standard for geographic areas 2023 (SSGA23); the numeric area codes are this table's own, not SSGA23 codes, and the extract carries no labels.

## How the numbers are checked

- **Pinned input.** `R/load.R` refuses the extract unless its bytes match the SHA-256 recorded in `data-raw/SOURCE.md`, and stops on any change of shape: unexpected columns, an unknown flag, a head count that is not a whole number, a duplicate or unmapped cell, a missing year or a missing national or island total. [`tests/test-r-contracts.R`](tests/test-r-contracts.R) feeds it broken copies to show each check fires.
- **Rules that can fail.** Five validation rules run on the analysis table and on a deliberately corrupted copy; each corruption moves exactly one rule. `census_year_reported` fires 9 times on the real data, which is a finding: census years still withhold cells.
- **Reconciliation, reported not asserted.** The regions are summed against the published national total for every class-year: 10 exact, 12 off by at most 2 head, 50 incomplete because a region is withheld or absent.
- **Reproduced by CI.** GitHub Actions regenerates every CSV from a clean checkout on every pull request, every push to `main` and weekly, and fails if any differs from the committed copy. The site deployed to GitHub Pages is the one that build rendered.
- **README figures checked against the report.** The report's numbers, captions and figure alt text are computed at render time. The headline figures in this README, including those in the image description, are checked against [`outputs/key-figures.csv`](outputs/key-figures.csv), which the render writes: [`tests/test-readme-figures.R`](tests/test-readme-figures.R) fails if a phrase is missing or quoted a different number of times.

## Reproduce

Requirements: R 4.6.1 (the version in [`renv.lock`](renv.lock), which CI uses) and Quarto 1.10.18. The R packages are declared in [`DESCRIPTION`](DESCRIPTION) and pinned to exact versions in [`renv.lock`](renv.lock). Run from the repository root:

```bash
git clone https://github.com/Kenchch/nz-sheep-decline-by-region.git
cd nz-sheep-decline-by-region
Rscript -e 'renv::restore()'                                 # the pinned package versions
Rscript -e 'stopifnot(isTRUE(renv::status()$synchronized))'
Rscript tests/test-r-contracts.R                             # malformed extracts are rejected
Rscript tests/test-r-analysis.R                              # the report's helper functions
Rscript tests/test-r-tables.R                                # the derived tables refuse gaps
Rscript R/checks.R                                           # regenerates outputs/*.csv
quarto render                                                # the report, figures and key-figures.csv
Rscript tests/test-readme-figures.R                          # this README against the report
```

A clean checkout must reproduce the committed CSVs byte for byte. The figures are regenerated too, but their bytes differ with the platform's fonts and graphics device, so CI checks that each exists rather than comparing it.

## Repository layout

```
index.qmd                    the published report
R/load.R                     hash gate, read, label, isolate withheld cells
R/checks.R                   five rules, the corrupted-copy demo, both reconciliations
R/analysis.R                 pure helpers the report uses
R/tables.R                   the derived tables, each asserting its own completeness
tests/                       ingestion contracts, helper and table tests, README check
data-raw/                    the pinned extract and its provenance
outputs/                     analysis table, validation summaries, reconciliations, key figures, figures
databricks/                  the same pipeline as three PySpark notebooks
```

## Databricks port

[`databricks/`](databricks/README.md) rebuilds the pipeline in PySpark for Databricks serverless, with the same hash gate, the same rules and the same reconciliation tiers. The quality gate refuses to publish if any row breaks a blocking rule, as the R loader does. [`databricks/run_local.py`](databricks/run_local.py) runs the three notebooks on a local Spark session in CI and compares silver and the gold tables with the committed `outputs/*.csv`; the [port's README](databricks/README.md) says exactly which columns are compared.

## How this was built

I set the problem, the data contracts and the quality rules, ran the checks and reviewed every diff. Claude Code and OpenAI Codex drafted code, refactored and scaffolded tests. Commits made before 6 September 2026 had their `Co-Authored-By` trailers removed when the history was rewritten; some later commits carry them. Each pull request records its own AI involvement in its description.
