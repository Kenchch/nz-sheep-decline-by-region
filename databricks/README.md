# NZ Sheep Decline by Region — Databricks Port

A port of the R + dplyr + Quarto analysis at [github.com/Kenchch/nz-sheep-decline-by-region](https://github.com/Kenchch/nz-sheep-decline-by-region) to **PySpark on Databricks serverless** (Unity Catalog).

This is a **port**, not a re-run. R does not run on Databricks Free Edition (serverless-only, no classic clusters). The analysis was rebuilt in PySpark on Unity Catalog, preserving four design commitments from the original.

## What was preserved

1. **SHA-256 gate on the pinned input** — The extract is hash-verified on every run. If the bytes change (e.g. Stats NZ publishes a new vintage), the pipeline refuses to proceed rather than silently producing different numbers under the same commit.

2. **Quarantine rather than delete** — Failed rows go to a quarantine table with the array of rules each one broke, not into the void. The reject rate gate (1%) blocks publication if too many rows fail.

3. **Suppression preserved as flagged-missing, not zero** — A suppressed cell is a cell we are not allowed to see, not a cell containing no animals. Suppressed values become `NULL` with a flag, never zero, never dropped.

4. **Regional-to-national reconciliation reported per class-year** — Instead of asserting regions sum to the national total within a tolerance, each class-year is reported in tiers: Exact, Fully published (off by a few head), or Incomplete region row.

## Pipeline architecture

```
ingest (01_ingest_and_pin)
  → quality_gate (02_quality_gate)
    → analysis (03_analysis)
```

Three dependent tasks in a Lakeflow Job. A failure names the stage that broke.

## Tables (Unity Catalog: workspace.nz_livestock)

| Layer | Table | Rows | Description |
| --- | --- | --- | --- |
| Bronze | bronze_agr_agr_003 | 19,626 | Raw extract, nothing cast or renamed |
| Bronze | ingest_manifest | 1+ | File, SHA-256, row count, timestamp per run |
| Dim | dim_livestock | 3 | Sheep, Dairy cattle, Beef cattle (verified codes only) |
| Dim | dim_area | 20 | 17 regions + 3 aggregates, SSGA23 names |
| Silver | silver_livestock_regional | 1,397 | Typed, labelled, validated |
| Quarantine | quarantine_livestock | 0 | Failed rows with broken rule names |
| Gold | gold_regional_change | 15 | Sheep change 2002→2025 by region |
| Gold | gold_reconciliation | 72 | Regional vs national, per class-year, in tiers |
| Gold | gold_coverage | 24 | Suppression coverage by year (sheep only) |
| Gold | gold_dairy_windows | 9 | Three windows × three classes |

## Key results

| Metric | Value |
| --- | --- |
| Sheep 2002 → 2025 | 39,571,837 → 23,252,463 (−16,319,374) |
| Dairy cattle change | +588,281 |
| Beef cattle change | −658,613 |
| Regions with both endpoints | 15 (Auckland & Nelson drop out) |
| Top 3 share of fall | 54.0% (Canterbury, Southland, Otago) |
| Reconciliation: Exact | 10 class-years |
| Reconciliation: Off by a few | 12 class-years |
| Reconciliation: Incomplete | 50 class-years |
| Dairy 2002–2014 | +29.8% |
| Dairy 2014–2025 | −14.2% |
| Census-year suppression | 9 cells (kept as a finding, not a failure) |

## Deliberate failure demo

The job includes a run where the SHA-256 hash was intentionally broken. The `ingest` task fails with `ValueError: Pinned extract does not match the recorded hash`, and both downstream tasks show **Upstream failed** — they refuse to run rather than serving yesterday's numbers.

See `screenshots/` for the red (failure) and green (success) run graphs.

## Source data

Source data: Stats NZ, Agricultural production statistics, licensed by Stats NZ for re-use under the Creative Commons Attribution 4.0 International licence.

- Table: AGR_AGR_003 — Livestock Numbers by Regional Council
- Vintage: Final, year to June 2025 release. Downloaded 2026-09-04.
- File: `data-raw/agr_agr_003_2026-09-04.csv` (886,010 bytes, SHA-256 `e9d82621...fbe03a4c`)

## What this does NOT claim

This is Free Edition: serverless-only, no classic clusters, no Spark UI, 0.85 MB of data, single user. It does not exercise partitioning, shuffle tuning, Z-ordering, streaming, or Unity Catalog governance across teams. It demonstrates judgement in data engineering design, not production Databricks engineering at scale.