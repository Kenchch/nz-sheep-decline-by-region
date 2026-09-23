# NZ Sheep Decline by Region — Databricks Port

A port of the R + dplyr + Quarto analysis at [github.com/Kenchch/nz-sheep-decline-by-region](https://github.com/Kenchch/nz-sheep-decline-by-region) to **PySpark on Databricks serverless** (Unity Catalog).

This is a **port**, not a re-run. R does not run on Databricks Free Edition (serverless-only, no classic clusters). The analysis was rebuilt in PySpark on Unity Catalog, preserving four design commitments from the original.

## What was preserved

1. **SHA-256 gate on the pinned input** — The extract is hash-verified on every run, and hashed again after Spark has read it. If the bytes change (e.g. Stats NZ publishes a new vintage), the pipeline refuses to proceed rather than silently producing different numbers under the same commit. Overriding the pinned hash through the `expected_sha256` parameter is allowed for a deliberate new vintage, but it is printed and recorded in `ingest_manifest.hash_overridden`.

2. **Quarantine, and refuse to publish** — Failed rows go to a quarantine table with the array of rules each one broke, not into the void. Any row that breaks a blocking rule stops silver from being replaced, as the R loader stops on the same input. There is deliberately no tolerance: publishing without a rejected row would change the analysis silently — losing one Canterbury sheep cell would drop Canterbury from the regional table and replace the headline's top three.

3. **Suppression preserved as flagged-missing, not zero** — A suppressed cell is a cell we are not allowed to see, not a cell containing no animals. Suppressed values become `NULL` with a flag, never zero, never dropped.

4. **Regional-to-national reconciliation reported per class-year** — Instead of asserting regions sum to the national total within a tolerance, each class-year is reported in tiers: Exact, Fully published (off by a few head), or Incomplete region row.

## Pipeline architecture

```
ingest (01_ingest_and_pin)
  → quality_gate (02_quality_gate)
    → analysis (03_analysis)
```

Three dependent tasks in a Lakeflow Job. A failure names the stage that broke.

Before running, create a Unity Catalog schema and a managed volume named `raw`
inside it, then upload the pinned CSV from `data-raw/` into that volume. Pass the
same `catalog` and `schema` task parameters to all three notebooks (defaults:
`workspace` and `nz_livestock`); both must be plain identifiers. The ingest task
also accepts `source_file`, which must be a bare file name inside the volume,
and `expected_sha256`. Existing widget values and Lakeflow task parameters are
kept; the notebooks' defaults apply only when no value was supplied.

Ingestion stops on a changed column set or an unknown suppression flag. The
quality gate quarantines malformed years, head counts that are not
non-negative whole numbers, unknown suppression flags, duplicate cells and
unmapped areas, and any quarantined row stops publication. The census-year
suppression rule remains informational. Empty input, missing years, and missing
or suppressed national or island totals also fail **before** silver is
overwritten, preserving the last successful table. The analysis notebook
refuses to write a coverage, reconciliation or window table with a year or
class-year missing.

## Tables (Unity Catalog: workspace.nz_livestock)

| Layer | Table | Rows | Description |
| --- | --- | --- | --- |
| Bronze | bronze_agr_agr_003 | 19,626 | Raw extract, nothing cast or renamed |
| Bronze | ingest_manifest | 1+ | File, SHA-256, row count, hash override flag, timestamp per run |
| Dim | dim_livestock | 3 | Sheep, Dairy cattle, Beef cattle (verified codes only) |
| Dim | dim_area | 20 | 17 regions + 3 aggregates; SSGA23 names on the table's own codes |
| Silver | silver_livestock_regional | 1,397 | Typed, labelled, validated; carries `_source_sha256` and `_ingested_at` |
| Quarantine | quarantine_livestock | 0 | Failed rows of the latest run, with broken rule names and `_checked_at` |
| Quality | quality_rule_summary | 8 | Failures per rule, including rules that never fail |
| Gold | gold_national_change | 3 | National change 2002→2025 by class |
| Gold | gold_regional_change | 15 | Sheep change 2002→2025 by region, with share of the fall and of the 2002 flock |
| Gold | gold_reconciliation | 72 | Regional vs national, per class-year, in tiers |
| Gold | gold_island_reconciliation | 72 | Published island totals vs the published national total |
| Gold | gold_coverage | 24 | Suppression coverage by year (sheep only) |
| Gold | gold_dairy_windows | 9 | Three windows × three classes |

Gold values are unrounded; format them where they are displayed. `gold_coverage`
matches the R CSV's units and column definitions: `suppression_rate` is the
fraction of present regions suppressed; `suppression_rate_all_regions` uses all
17 expected regions. Dashboards must format these fractions as percentages.

## Local verification

With Java 17+ and Python 3.12, run from the repository root:

```bash
pip install --require-hashes -r databricks/requirements.txt
python databricks/run_local.py
```

`requirements.txt` pins and hashes every transitive dependency; it is compiled
from `requirements.in`. CI runs the same two commands.

The runner compares, cell for cell:

| Spark table | R output | Columns compared |
| --- | --- | --- |
| silver_livestock_regional | `outputs/livestock_regional.csv` | every analysis column |
| quality_rule_summary | `outputs/validation-summary.csv` | `fails`, for the five shared rules |
| gold_reconciliation | `outputs/residual-tiers.csv` | every column, `residual_pct` to 1e-9 |
| gold_island_reconciliation | `outputs/island-reconciliation.csv` | every column |
| gold_coverage | `outputs/coverage-and-suppression.csv` | every column, rates to 1e-9 |
| gold_dairy_windows | `outputs/dairy-comparison-windows.csv` | every column, `change_pct` to 1e-9 |
| gold_national_change | recomputed from `outputs/livestock_regional.csv` | heads and change |
| gold_regional_change | recomputed from `outputs/livestock_regional.csv` | change and both shares, to 1e-9 |

The R pipeline's corrupted-copy demonstration has no Spark counterpart. Instead
the runner injects failures and checks each is quarantined or refused: a bad
hash, unsafe parameters, a dropped or extra column, malformed values (including
`4192693.5`, `1e3` and `-5`) and years, an unknown flag, a single duplicate or
unmapped cell, missing or suppressed national and island totals, a missing
year, empty input, and a year with no regional rows. Every refused run must
leave the previous silver table in place.

## Key results

| Metric | Value |
| --- | --- |
| Sheep 2002 → 2025 | 39,571,837 → 23,252,463 (−16,319,374) |
| Dairy cattle change | +588,281 |
| Beef cattle change | −658,613 |
| Regions with both endpoints | 15 (Auckland & Nelson drop out) |
| Top 3 share of measurable regional fall | 54.0% (Canterbury, Southland, Otago), against 50.6% of the 2002 flock |
| Reconciliation: Exact | 10 class-years |
| Reconciliation: Off by a few | 12 class-years |
| Reconciliation: Incomplete | 50 class-years |
| Dairy 2002–2014 | +29.8% |
| Dairy 2014–2025 | −14.2% |
| Census-year suppression | 9 cells (kept as a finding, not a failure) |

The first three rows are `gold_national_change`; the rest are in the gold tables
listed above.

## Deliberate failure demo

The job includes a run where the SHA-256 hash was intentionally broken. The `ingest` task fails with `ValueError: Pinned extract does not match the recorded hash`, and both downstream tasks show **Upstream failed** — they refuse to run rather than serving yesterday's numbers.

See `screenshots/` for the red (failure) and green (success) run graphs.

### The screenshots are out of date

The screenshots were taken on 2026-09-20, before the fixes in 0.3.0, and show
output that is now known to be wrong: the dashboard's suppression line starts
at 2017 because of the null-flag bug fixed since, its rates are percentages
where `gold_coverage` now returns fractions, and its regional bars are sorted
alphabetically rather than by decline. Nothing in this repository shows the
current notebooks running on serverless. The run graphs (red and green) still
illustrate the hash-gate behaviour, which has not changed. They will be
replaced by screenshots of the current notebooks.

## Source data

This work is based on Stats NZ's data (Agricultural production statistics, AGR_AGR_003), licensed by Stats NZ for re-use under the [Creative Commons Attribution 4.0 International licence](https://creativecommons.org/licenses/by/4.0/).

- Table: AGR_AGR_003 — Livestock Numbers by Regional Council
- Vintage: Final, year to June 2025 release. Downloaded 2026-09-04.
- File: `data-raw/agr_agr_003_2026-09-04.csv` (886,010 bytes, SHA-256 `e9d82621...fbe03a4c`)

## What this does NOT claim

This is Free Edition: serverless-only, no classic clusters, no Spark UI, 0.85 MB of data, single user. It does not exercise partitioning, shuffle tuning, Z-ordering, streaming, or Unity Catalog governance across teams. The local check runs classic PySpark, not the Spark Connect client serverless uses; the two are not known to differ for anything these notebooks do, but that is not tested here. It demonstrates judgement in data engineering design, not production Databricks engineering at scale.
