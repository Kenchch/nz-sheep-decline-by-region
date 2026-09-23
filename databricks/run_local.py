"""Run the three Databricks notebooks on a local Spark session and check them.

The notebooks are written for Databricks: they read widgets through `dbutils`,
render with `display`, and write Unity Catalog tables. None of that exists
off-platform, so this script supplies the three names the notebooks expect
and executes each file in turn against a local Spark session whose catalog is
`spark_catalog`. Nothing else is injected -- in particular not
`pyspark.sql.functions`, so a notebook that forgets its own import fails here
as it would on Databricks. The notebooks themselves are not modified; the only
substitution is the Volumes path, which is redirected at the pinned extract in
`data-raw/`.

It then checks that silver and the gold tables agree with the CSVs that the
R pipeline committed to `outputs/`. That is the claim the Databricks README
makes -- that this is a port of the same analysis -- checked rather than
asserted. It found the first defects: `array_remove(..., None)` returning a
null array, and `OBS_STATUS IN ('s', 'c')` being null rather than false on
every published cell, which together left the quarantine unreachable and the
coverage table counting null where it should count zero.

Finally it injects failures -- malformed values and years, duplicate and
unmapped cells, unknown flags, suppressed or missing aggregates, missing
years, a changed column set and empty input -- and checks that each one is
quarantined or refused, and that no failed quality gate replaces the last
good silver table.

Usage, from the repository root, with Java 17+ on the PATH:

    pip install --require-hashes -r databricks/requirements.txt
    python databricks/run_local.py

This work is based on Stats NZ's data (Agricultural production statistics,
AGR_AGR_003), licensed by Stats NZ for re-use under the Creative Commons
Attribution 4.0 International licence.
"""

import hashlib
import pathlib
import sys
import tempfile
import types

import numpy as np
import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql import functions as F


def check(condition, message):
    """A check that survives `python -O`, which strips assert statements."""
    if not condition:
        raise SystemExit(f"port check: FAIL -- {message}")


def close(a, b):
    """Equal to within floating-point noise, element-wise, NaN equal to NaN."""
    return np.isclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float),
                      rtol=0, atol=1e-9, equal_nan=True).all()


REPO = pathlib.Path(__file__).resolve().parents[1]
NOTEBOOKS = ["01_ingest_and_pin.py", "02_quality_gate.py", "03_analysis.py"]
CATALOG, SCHEMA = "spark_catalog", "nz_livestock"
FQ = f"{CATALOG}.{SCHEMA}"
RAW_DIR = REPO / "data-raw"


class Widgets:
    """Enough of dbutils.widgets for the three notebooks."""

    def __init__(self, overrides=None):
        self.values = {"catalog": CATALOG, "schema": SCHEMA}
        self.values.update(overrides or {})

    def removeAll(self):
        self.values.clear()

    def text(self, name, default):
        self.values.setdefault(name, default)

    def get(self, name):
        return self.values[name]


class Notebook:
    # dbutils.notebook.exit ends the notebook. Here it only reports, which is
    # equivalent as long as the notebooks call it as their last statement,
    # as 01 does.
    def exit(self, message):
        print("notebook exit:", message)


def make_spark(warehouse):
    return (SparkSession.builder
            .master("local[2]")
            .appName("nz-sheep-decline-port-check")
            .config("spark.ui.enabled", "false")
            .config("spark.ui.showConsoleProgress", "false")
            .config("spark.sql.shuffle.partitions", "4")
            .config("spark.sql.warehouse.dir", str(warehouse))
            # Arrow needs pyarrow, which is not required here; the fallback
            # is fine for a few thousand rows and quieter.
            .config("spark.sql.execution.arrow.pyspark.enabled", "false")
            # The in-memory catalog, not Hive: the three notebooks share one
            # session, so the tables only need to outlive the session, and a
            # Hive metastore would leave a Derby database in the working
            # directory.
            .getOrCreate())


def run_notebook(spark, name, overrides=None, show=True, raw_dir=RAW_DIR):
    # Lakeflow tasks receive their own widget parameters. Model removeAll
    # faithfully so deleting those parameters cannot be hidden by this shim.
    dbutils = types.SimpleNamespace(widgets=Widgets(overrides), notebook=Notebook())
    source = (REPO / "databricks" / name).read_text(encoding="utf-8")
    # The one substitution: read the extract from a local directory instead
    # of a Unity Catalog volume.
    volume_path = 'f"/Volumes/{CATALOG}/{SCHEMA}/raw/{SRC}"'
    check(name != NOTEBOOKS[0] or volume_path in source,
          f"{name} no longer builds the Volumes path this runner redirects")
    source = source.replace(volume_path, repr(str(raw_dir)) + ' + "/" + SRC')
    print(f"\n===== {name}")
    exec(compile(source, name, "exec"),
         {"spark": spark, "dbutils": dbutils,
          "display": (lambda df: df.show(5, truncate=False)) if show else lambda df: None})


def run_notebooks(spark):
    for name in NOTEBOOKS:
        run_notebook(spark, name)


def table(spark, name):
    return spark.table(f"{FQ}.{name}").toPandas()


def compare(gold, r_csv, keys, exact, approx=(), label=""):
    """Merge a gold table with an R CSV on keys and compare the named columns."""
    m = gold.merge(r_csv, on=keys, suffixes=("", "_r"), validate="one_to_one")
    check(len(gold) == len(r_csv) == len(m),
          f"{label}: {len(gold)} gold rows, {len(r_csv)} R rows, {len(m)} matched")
    for col in exact:
        same = (m[col] == m[f"{col}_r"]) | (m[col].isna() & m[f"{col}_r"].isna())
        check(same.all(), f"{label}.{col} differs from the R output")
    for col in approx:
        check(close(m[col], m[f"{col}_r"]), f"{label}.{col} differs from the R output")
    print(f"{label} matches the R output: {', '.join(list(exact) + list(approx))}")
    return m


def check_against_r_outputs(spark):
    print("\n===== silver and gold tables against outputs/*.csv")

    silver = table(spark, "silver_livestock_regional")
    r_table = pd.read_csv(REPO / "outputs/livestock_regional.csv",
                          dtype={"area_code": str})
    # Two-valued, never null: this is the flag every rule reads.
    check(silver["suppressed"].notna().all(), "suppressed is null on some rows")
    check(set(silver["suppressed"].unique()) == {False, True},
          "suppressed is not two-valued")
    check(len(silver) == 1397, f"silver has {len(silver)} rows, expected 1397")
    compare(silver, r_table, ["year", "area_code", "livestock_class"],
            ["region", "island", "is_aggregate", "suppressed", "suppression_code",
             "is_census_year", "head"], label="silver")

    quarantine = table(spark, "quarantine_livestock")
    check(len(quarantine) == 0, f"{len(quarantine)} rows in quarantine")
    print("quarantine is empty on the pinned extract")

    # The rules the two pipelines share must fail the same number of times.
    rules = table(spark, "quality_rule_summary")
    r_rules = pd.read_csv(REPO / "outputs/validation-summary.csv")
    m = rules.merge(r_rules, on="rule", how="right", validate="one_to_one")
    check(m["fails_x"].notna().all(),
          f"rules missing from quality_rule_summary: {list(m.loc[m['fails_x'].isna(), 'rule'])}")
    check((m["fails_x"] == m["fails_y"]).all(),
          "quality_rule_summary fails differ from validation-summary.csv")
    extra = rules[~rules["rule"].isin(r_rules["rule"])]
    check((extra["fails"] == 0).all(), "a Spark-only rule fails on the pinned extract")
    print("quality_rule_summary matches validation-summary.csv, "
          f"{int(r_rules.loc[r_rules['rule'] == 'census_year_reported', 'fails'].iloc[0])} "
          "census_year_reported failures")

    r_tiers = pd.read_csv(REPO / "outputs/residual-tiers.csv")
    compare(table(spark, "gold_reconciliation"), r_tiers, ["year", "livestock_class"],
            ["regions_present", "regions_suppressed", "region_sum", "published",
             "residual", "fully_published", "tier"], ["residual_pct"],
            label="gold_reconciliation")

    compare(table(spark, "gold_island_reconciliation"),
            pd.read_csv(REPO / "outputs/island-reconciliation.csv"),
            ["year", "livestock_class"], ["a10", "a19", "a20", "residual"],
            label="gold_island_reconciliation")

    compare(table(spark, "gold_coverage"),
            pd.read_csv(REPO / "outputs/coverage-and-suppression.csv"), ["year"],
            ["regions_present", "regions_with_value", "regions_suppressed",
             "regions_expected", "regions_absent"],
            ["suppression_rate", "suppression_rate_all_regions"], label="gold_coverage")

    compare(table(spark, "gold_dairy_windows"),
            pd.read_csv(REPO / "outputs/dairy-comparison-windows.csv"),
            ["start_year", "end_year", "livestock_class"],
            ["start_head", "end_head", "change_head", "start_design", "end_design"],
            ["change_pct"], label="gold_dairy_windows")

    # No committed CSV holds the national or regional change, so both are
    # recomputed here from the analysis table the R pipeline committed, the
    # same way the report computes them.
    r_nat = (r_table[(r_table["area_code"] == "20") & r_table["year"].isin([2002, 2025])]
             .pivot(index="livestock_class", columns="year", values="head"))
    r_nat = pd.DataFrame({"livestock_class": r_nat.index,
                          "start_head": r_nat[2002].values,
                          "end_head": r_nat[2025].values,
                          "change_head": (r_nat[2025] - r_nat[2002]).values})
    compare(table(spark, "gold_national_change"), r_nat, ["livestock_class"],
            ["start_head", "end_head", "change_head"], label="gold_national_change")

    r_sheep = r_table[(r_table["livestock_class"] == "Sheep") &
                      (~r_table["is_aggregate"]) &
                      (r_table["year"].isin([2002, 2025]))]
    wide = r_sheep.pivot(index="region", columns="year", values="head").dropna()
    r_change = pd.DataFrame({
        "region": wide.index,
        "change": (wide[2025] - wide[2002]).values,
        "share_of_start": (100 * wide[2002] / wide[2002].sum()).values})
    r_change["share_of_fall"] = (100 * r_change["change"] /
                                 r_change.loc[r_change["change"] < 0, "change"].sum())
    check(len(r_change) == 15, f"{len(r_change)} measurable regions in R, expected 15")
    compare(table(spark, "gold_regional_change"), r_change, ["region"], ["change"],
            ["share_of_fall", "share_of_start"], label="gold_regional_change")


def check_coverage_denominators(spark):
    # In the pinned data every year with absent regions has zero suppressed
    # cells, so the two denominators happen to yield the same fraction. Add
    # one suppressed row in such a year to distinguish the definitions.
    original = spark.table(f"{FQ}.gold_coverage").localCheckpoint(eager=True)
    s = spark.table(f"{FQ}.silver_livestock_regional")
    target = ((F.col("year") == 2003) & (F.col("area_code") == "1") &
              (F.col("livestock_class") == "Sheep"))
    check(s.filter(target & ~F.col("suppressed")).count() == 1,
          "coverage regression requires one published Northland sheep row in 2003")
    s = (s.withColumn("head", F.when(target, F.lit(None).cast("bigint")).otherwise(F.col("head")))
          .withColumn("suppressed", F.when(target, True).otherwise(F.col("suppressed")))
          .withColumn("suppression_code", F.when(target, "s").otherwise(F.col("suppression_code"))))
    source = (REPO / "databricks" / NOTEBOOKS[2]).read_text(encoding="utf-8")
    marker = "# DBTITLE 1,Coverage"
    check(source.count(marker) == 1, "coverage cell could not be identified")
    coverage_cell = source.split(marker, 1)[1].split("# COMMAND ----------", 1)[0]
    try:
        exec(compile(coverage_cell, NOTEBOOKS[2] + ":coverage", "exec"),
             {"s": s, "F": F, "FQ": FQ, "EXPECTED_REGIONS": 17,
              "YEARS": list(range(2002, 2026)), "display": lambda df: None})
        row = spark.table(f"{FQ}.gold_coverage").filter(F.col("year") == 2003).first()
        check(row.regions_present < 17 and row.regions_suppressed == 1,
              "coverage regression did not retain absent and suppressed regions")
        check(abs(row.suppression_rate - 1 / row.regions_present) < 1e-12 and
              abs(row.suppression_rate_all_regions - 1 / 17) < 1e-12,
              "coverage rates do not use their respective denominators and fraction units")
        check(row.regions_with_value == row.regions_present - 1,
              "coverage counts a suppressed cell as a published value")
        print("coverage distinguishes absent regions from suppressed regions")
    finally:
        original.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
            f"{FQ}.gold_coverage")
        original.unpersist()


def expect_failure(spark, name, message, overrides=None, raw_dir=RAW_DIR):
    try:
        run_notebook(spark, name, overrides=overrides, show=False, raw_dir=raw_dir)
    except ValueError as exc:
        check(message in str(exc), f"{name}: unexpected failure: {exc}")
    else:
        check(False, f"{name} accepted input that should fail with: {message}")


def check_ingest_failures(spark, tmp):
    print("\n===== ingestion failures")
    # This also verifies that a supplied widget overrides the default hash.
    expect_failure(spark, NOTEBOOKS[0], "Pinned extract does not match",
                   {"expected_sha256": "0" * 64})
    expect_failure(spark, NOTEBOOKS[0], "bare file name",
                   {"source_file": "../agr_agr_003_2026-09-04.csv"})
    expect_failure(spark, NOTEBOOKS[0], "invalid schema", {"schema": "nz-livestock"})

    # A changed column set. The file is rewritten, so its hash is supplied
    # as a parameter to get past the gate to the shape check.
    original = (RAW_DIR / "agr_agr_003_2026-09-04.csv").read_bytes()
    for label, header, message in [
            ("dropped", b"DATAFLOW,LIVESTOCK_AGR_AGR_003,AREA_AGR_AGR_003,YEAR_AGR_AGR_003,OBS_VALUE,OBS_FLAG",
             "missing required column"),
            ("renamed", b"DATAFLOW,LIVESTOCK_AGR_AGR_003,AREA_AGR_AGR_003,YEAR_AGR_AGR_003,OBS_VALUE,OBS_STATUS,UNIT",
             "unexpected column")]:
        body = original.split(b"\r\n", 1)[1]
        if label == "renamed":
            body = b"\r\n".join(line + b"," if line else line for line in body.split(b"\r\n"))
        data = header + b"\r\n" + body
        path = pathlib.Path(tmp) / f"{label}.csv"
        path.write_bytes(data)
        expect_failure(spark, NOTEBOOKS[0], message,
                       {"source_file": path.name,
                        "expected_sha256": hashlib.sha256(data).hexdigest()},
                       raw_dir=pathlib.Path(tmp))
    # Restore bronze from the pinned extract for the checks that follow.
    run_notebook(spark, NOTEBOOKS[0], show=False)
    print("bad hash, unsafe parameters and changed columns stop ingestion")


def check_failure_paths(spark):
    print("\n===== injected failures and publication protection")

    # Detach the snapshot from the table before overwriting it in scenarios.
    bronze = spark.table(f"{FQ}.bronze_agr_agr_003").localCheckpoint(eager=True)
    silver_before = set(spark.table(f"{FQ}.silver_livestock_regional").collect())

    def write_bronze(frame):
        frame.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
            f"{FQ}.bronze_agr_agr_003")

    def unchanged():
        check(set(spark.table(f"{FQ}.silver_livestock_regional").collect()) == silver_before,
              "failed quality gate overwrote the previous silver table")

    def quarantined(expected):
        rows = spark.table(f"{FQ}.quarantine_livestock").collect()
        got = {}
        for r in rows:
            got.setdefault((r.area_code, r.YEAR_AGR_AGR_003), []).append(set(r.broken_rules))
        for key, rule in expected.items():
            check(key in got and all(rule in rules for rules in got[key]),
                  f"row {key} was not quarantined for {rule}: {got.get(key)}")
        return rows

    sheep = F.col("LIVESTOCK_AGR_AGR_003") == "6731"
    sheep_2002 = sheep & (F.col("YEAR_AGR_AGR_003") == "2002")
    canterbury_2025 = sheep & (F.col("YEAR_AGR_AGR_003") == "2025") & \
        (F.col("AREA_AGR_AGR_003") == "15")

    def with_value(frame, cell, value, column="OBS_VALUE"):
        return frame.withColumn(column, F.when(cell, value).otherwise(F.col(column)))

    try:
        spark.conf.set("spark.sql.ansi.enabled", "true")

        # Row-level failures, one per rule, all in a single run. Any one of
        # them stops publication: silver is not replaced by a table missing
        # the row.
        area = lambda code: sheep_2002 & (F.col("AREA_AGR_AGR_003") == code)
        bad = bronze
        for code, value in [("1", "not-a-number"), ("2", "NaN"), ("3", "Infinity"),
                            ("6", "4192693.5"), ("7", "1e3"), ("8", "-5")]:
            bad = with_value(bad, area(code), value)
        bad = with_value(bad, area("4"), "unknown", "OBS_STATUS")
        bad = with_value(bad, area("5"), "not-a-year", "YEAR_AGR_AGR_003")
        write_bronze(bad)
        expect_failure(spark, NOTEBOOKS[1], "failed blocking rules")
        rows = quarantined({("1", "2002"): "value_is_count", ("2", "2002"): "value_is_count",
                            ("3", "2002"): "value_is_count", ("6", "2002"): "value_is_count",
                            ("7", "2002"): "value_is_count", ("8", "2002"): "head_non_negative",
                            ("4", "2002"): "status_known", ("5", "not-a-year"): "year_in_range"})
        check(len(rows) == 8, f"expected 8 malformed rows in quarantine, got {len(rows)}")
        unchanged()
        print("malformed values, years and statuses are quarantined and stop publication")

        # A single bad cell is enough. Before, a reject-rate tolerance let
        # this one through and silently replaced Canterbury in the top three.
        for label, frame, key, rule in [
                ("duplicate", bronze.unionByName(bronze.filter(canterbury_2025)),
                 ("15", "2025"), "no_duplicate_cells"),
                ("unmapped area", with_value(bronze, canterbury_2025, "999", "AREA_AGR_AGR_003"),
                 ("999", "2025"), "region_label_present"),
                ("fractional count", with_value(bronze, canterbury_2025, "4192693.5"),
                 ("15", "2025"), "value_is_count")]:
            write_bronze(frame)
            expect_failure(spark, NOTEBOOKS[1], "failed blocking rules")
            quarantined({key: rule})
            unchanged()
            print(f"one {label} cell stops publication")

        write_bronze(bronze.withColumn("OBS_VALUE", F.lit("-1")))
        expect_failure(spark, NOTEBOOKS[1], "failed blocking rules")
        check(spark.table(f"{FQ}.quarantine_livestock").count() == 1397,
              "blocking failure did not preserve rejected rows in quarantine")
        unchanged()

        national_cell = sheep_2002 & (F.col("AREA_AGR_AGR_003") == "20")
        write_bronze(bronze.filter(~national_cell))
        expect_failure(spark, NOTEBOOKS[1], "national total is required")
        unchanged()

        suppressed = lambda cell: with_value(
            with_value(bronze, cell, F.lit(None).cast("string")), cell, "s", "OBS_STATUS")
        write_bronze(suppressed(national_cell))
        expect_failure(spark, NOTEBOOKS[1], "national total is required")
        unchanged()

        island_cell = sheep_2002 & (F.col("AREA_AGR_AGR_003") == "10")
        write_bronze(bronze.filter(~island_cell))
        expect_failure(spark, NOTEBOOKS[1], "island total is required")
        unchanged()

        write_bronze(suppressed(island_cell))
        expect_failure(spark, NOTEBOOKS[1], "island total is required")
        unchanged()

        write_bronze(bronze.filter(F.col("YEAR_AGR_AGR_003") != "2002"))
        expect_failure(spark, NOTEBOOKS[1], "Year coverage changed")
        unchanged()

        write_bronze(bronze.limit(0))
        expect_failure(spark, NOTEBOOKS[1], "No candidate livestock rows")
        unchanged()
        print("aggregate coverage, year coverage and empty-input failures preserve silver")

        # 03's own output contract: a year with no regional sheep rows passes
        # 02 (the aggregates are still there) but must not vanish from
        # gold_coverage.
        write_bronze(bronze.filter(~(sheep & (F.col("YEAR_AGR_AGR_003") == "2010") &
                                     ~F.col("AREA_AGR_AGR_003").isin("10", "19", "20"))))
        run_notebook(spark, NOTEBOOKS[1], show=False)
        expect_failure(spark, NOTEBOOKS[2], "gold_coverage is missing years: [2010]")
        print("a year with no regional rows stops the analysis")
    finally:
        spark.conf.unset("spark.sql.ansi.enabled")
        write_bronze(bronze)
        bronze.unpersist()
        # Leave the pipeline as the pinned extract produces it.
        run_notebook(spark, NOTEBOOKS[1], show=False)
        run_notebook(spark, NOTEBOOKS[2], show=False)


def main():
    with tempfile.TemporaryDirectory(prefix="nz-sheep-spark-") as tmp:
        spark = make_spark(pathlib.Path(tmp) / "warehouse")
        spark.sparkContext.setLogLevel("ERROR")
        try:
            run_notebooks(spark)
            check_against_r_outputs(spark)
            check_coverage_denominators(spark)
            check_ingest_failures(spark, tmp)
            check_failure_paths(spark)
            check_against_r_outputs(spark)
        finally:
            spark.stop()
    print("\nport check: PASS")


if __name__ == "__main__":
    sys.exit(main())
