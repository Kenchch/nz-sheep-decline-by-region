"""Run the three Databricks notebooks on a local Spark session and check them.

The notebooks are written for Databricks: they read widgets through `dbutils`,
render with `display`, and write Unity Catalog tables. None of that exists
off-platform, so this script supplies the three names the notebooks expect
and executes each file in turn against a local Spark session whose catalog is
`spark_catalog`. The notebooks themselves are not modified; the only
substitution is the Volumes path, which is redirected at the pinned extract in
`data-raw/`.

It then checks that silver and every gold table agree with the CSVs that the
R pipeline committed to `outputs/`. That is the claim the Databricks README
makes -- that this is a port of the same analysis -- checked rather than
asserted. It found the first defects: `array_remove(..., None)` returning a
null array, and `OBS_STATUS IN ('s', 'c')` being null rather than false on
every published cell, which together left the quarantine unreachable and the
coverage table counting null where it should count zero.

Finally it injects bad values, years, missing aggregates and empty inputs
to check quarantine and that failed quality gates preserve the last good silver.

Usage, from the repository root, with Java on the PATH:

    pip install pyspark pandas
    python databricks/run_local.py

Source data: Stats NZ, Agricultural production statistics, licensed by Stats NZ
for re-use under the Creative Commons Attribution 4.0 International licence.
"""

import pathlib
import sys
import tempfile
import types

import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql import functions as F


def check(condition, message):
    """A check that survives `python -O`, which strips assert statements."""
    if not condition:
        raise SystemExit(f"port check: FAIL -- {message}")

REPO = pathlib.Path(__file__).resolve().parents[1]
NOTEBOOKS = ["01_ingest_and_pin.py", "02_quality_gate.py", "03_analysis.py"]
CATALOG, SCHEMA = "spark_catalog", "nz_livestock"


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


def run_notebook(spark, name, overrides=None, show=True):
    # Lakeflow tasks receive their own widget parameters. Model removeAll
    # faithfully so deleting those parameters cannot be hidden by this shim.
    dbutils = types.SimpleNamespace(widgets=Widgets(overrides), notebook=Notebook())
    source = (REPO / "databricks" / name).read_text(encoding="utf-8")
    # The one substitution: read the pinned extract from the repository
    # instead of a Unity Catalog volume.
    volume_path = 'f"/Volumes/{CATALOG}/{SCHEMA}/raw/{SRC}"'
    check(name != NOTEBOOKS[0] or volume_path in source,
          f"{name} no longer builds the Volumes path this runner redirects")
    source = source.replace(volume_path,
                            repr(str(REPO / "data-raw")) + ' + "/" + SRC')
    print(f"\n===== {name}")
    exec(compile(source, name, "exec"),
         {"spark": spark, "dbutils": dbutils,
          "display": (lambda df: df.show(5, truncate=False)) if show else lambda df: None,
          "F": F})


def run_notebooks(spark):
    for name in NOTEBOOKS:
        run_notebook(spark, name)


def table(spark, name):
    return spark.table(f"{CATALOG}.{SCHEMA}.{name}").toPandas()


def check_against_r_outputs(spark):
    print("\n===== gold tables against outputs/*.csv")

    silver = table(spark, "silver_livestock_regional")
    r_table = pd.read_csv(REPO / "outputs/livestock_regional.csv",
                          dtype={"area_code": str})
    keys = ["year", "area_code", "livestock_class"]
    m = silver.merge(r_table, on=keys, suffixes=("", "_r"), validate="one_to_one")
    check(len(silver) == len(r_table) == len(m) == 1397,
          f"silver has {len(silver)} rows, R has {len(r_table)}, {len(m)} match")
    # Two-valued, never null: this is the flag every rule reads.
    check(silver["suppressed"].notna().all(), "suppressed is null on some rows")
    check(set(silver["suppressed"].unique()) == {False, True},
          "suppressed is not two-valued")
    for col in ["region", "island", "is_aggregate", "suppressed",
                "suppression_code", "is_census_year", "head"]:
        same = (m[col] == m[f"{col}_r"]) | (m[col].isna() & m[f"{col}_r"].isna())
        check(same.all(), f"silver.{col} differs from the R table")
    print("silver matches the R analysis table, every column, cell for cell")

    quarantine = table(spark, "quarantine_livestock")
    check(len(quarantine) == 0, f"{len(quarantine)} rows in quarantine")
    print("quarantine is empty on the pinned extract")

    recon = table(spark, "gold_reconciliation")
    r_tiers = pd.read_csv(REPO / "outputs/residual-tiers.csv")
    m = recon.merge(r_tiers, on=["year", "livestock_class"], suffixes=("", "_r"),
                    validate="one_to_one")
    check(len(recon) == len(r_tiers) == len(m) == 72,
          f"{len(recon)} gold rows, {len(m)} class-years matched, expected 72")
    for col in ["regions_present", "regions_suppressed", "region_sum",
                "published", "residual", "fully_published", "tier"]:
        check((m[col] == m[f"{col}_r"]).all(),
              f"gold_reconciliation.{col} differs from residual-tiers.csv")
    print("gold_reconciliation matches residual-tiers.csv")

    coverage = table(spark, "gold_coverage")
    r_cov = pd.read_csv(REPO / "outputs/coverage-and-suppression.csv")
    m = coverage.merge(r_cov, on="year", suffixes=("", "_r"), validate="one_to_one")
    check(len(coverage) == len(r_cov) == len(m) == 24,
          f"{len(coverage)} gold rows, {len(m)} years matched, expected 24")
    for col in ["regions_present", "regions_with_value", "regions_suppressed",
                "regions_expected", "regions_absent"]:
        check((m[col] == m[f"{col}_r"]).all(),
              f"gold_coverage.{col} differs from coverage-and-suppression.csv")
    for col in ["suppression_rate", "suppression_rate_all_regions"]:
        check(((m[col] - m[f"{col}_r"]).abs() < 1e-12).all(),
              f"gold_coverage.{col} differs from the R fraction")
    print("gold_coverage matches coverage-and-suppression.csv")

    windows = table(spark, "gold_dairy_windows")
    r_win = pd.read_csv(REPO / "outputs/dairy-comparison-windows.csv")
    m = windows.merge(r_win, on=["start_year", "end_year", "livestock_class"],
                      suffixes=("", "_r"), validate="one_to_one")
    check(len(windows) == len(r_win) == len(m) == 9,
          f"{len(windows)} gold rows, {len(m)} windows matched, expected 9")
    check((m["change_head"] == m["change_head_r"]).all(),
          "gold_dairy_windows.change_head differs")
    check((m["change_pct"] == m["change_pct_r"].round(1)).all(),
          "gold_dairy_windows.change_pct differs")
    print("gold_dairy_windows matches dairy-comparison-windows.csv")

    # No committed CSV holds the regional change, so it is recomputed here
    # from the analysis table the R pipeline committed, the same way the
    # report computes it: both endpoints published, else excluded.
    change = table(spark, "gold_regional_change").set_index("region")
    r_sheep = r_table[(r_table["livestock_class"] == "Sheep") &
                      (~r_table["is_aggregate"]) &
                      (r_table["year"].isin([2002, 2025]))]
    wide = r_sheep.pivot(index="region", columns="year", values="head").dropna()
    r_change = wide[2025] - wide[2002]
    r_share = (100 * r_change / r_change[r_change < 0].sum()).round(1)
    check(len(change) == len(r_change) == 15,
          f"{len(change)} regions in gold, {len(r_change)} measurable in R")
    check((change["change"].sort_index() == r_change.sort_index()).all(),
          "gold_regional_change.change differs from the R analysis table")
    check((change["share_of_fall"].sort_index() == r_share.sort_index()).all(),
          "gold_regional_change.share_of_fall differs")
    print("gold_regional_change matches the sheep change recomputed from the "
          "R analysis table, 15 regions")


def check_coverage_denominators(spark):
    # In the pinned data every year with absent regions has zero suppressed
    # cells, so the two denominators happen to yield the same fraction. Add
    # one suppressed row in such a year to distinguish the definitions.
    fq = f"{CATALOG}.{SCHEMA}"
    original = spark.table(f"{fq}.gold_coverage").localCheckpoint(eager=True)
    s = spark.table(f"{fq}.silver_livestock_regional")
    target = ((F.col("year") == 2003) & (F.col("area_code") == "1") &
              (F.col("livestock_class") == "Sheep"))
    check(s.filter(target & ~F.col("suppressed")).count() == 1,
          "coverage regression requires one published Northland sheep row in 2003")
    s = (s.withColumn("head", F.when(target, F.lit(None).cast("double")).otherwise(F.col("head")))
          .withColumn("suppressed", F.when(target, True).otherwise(F.col("suppressed")))
          .withColumn("suppression_code", F.when(target, "s").otherwise(F.col("suppression_code"))))
    source = (REPO / "databricks" / NOTEBOOKS[2]).read_text(encoding="utf-8")
    marker = "# DBTITLE 1,Coverage"
    check(source.count(marker) == 1, "coverage cell could not be identified")
    coverage_cell = source.split(marker, 1)[1].split("# COMMAND ----------", 1)[0]
    try:
        exec(compile(coverage_cell, NOTEBOOKS[2] + ":coverage", "exec"),
             {"s": s, "F": F, "FQ": fq, "EXPECTED_REGIONS": 17, "display": lambda df: None})
        row = spark.table(f"{fq}.gold_coverage").filter(F.col("year") == 2003).first()
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
            f"{fq}.gold_coverage")
        original.unpersist()


def check_failure_paths(spark):
    print("\n===== injected failures and publication protection")
    fq = f"{CATALOG}.{SCHEMA}"

    def expect_failure(name, message, overrides=None):
        try:
            run_notebook(spark, name, overrides=overrides, show=False)
        except ValueError as exc:
            check(message in str(exc), f"unexpected failure: {exc}")
        else:
            check(False, f"{name} accepted {message}")

    # This also verifies that a supplied widget overrides the default hash.
    expect_failure(NOTEBOOKS[0], "Pinned extract does not match",
                   {"expected_sha256": "0" * 64})

    # Detach the snapshot from the table before overwriting it in scenarios.
    bronze = spark.table(f"{fq}.bronze_agr_agr_003").localCheckpoint(eager=True)
    silver_before = set(spark.table(f"{fq}.silver_livestock_regional").collect())

    def write_bronze(frame):
        frame.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
            f"{fq}.bronze_agr_agr_003")

    def unchanged():
        check(set(spark.table(f"{fq}.silver_livestock_regional").collect()) == silver_before,
              "failed quality gate overwrote the previous silver table")

    try:
        spark.conf.set("spark.sql.ansi.enabled", "true")
        sheep_2002 = ((F.col("LIVESTOCK_AGR_AGR_003") == "6731") &
                      (F.col("YEAR_AGR_AGR_003") == "2002"))
        bad = (bronze
            .withColumn("OBS_VALUE",
                F.when(sheep_2002 & (F.col("AREA_AGR_AGR_003") == "1"), "not-a-number")
                 .when(sheep_2002 & (F.col("AREA_AGR_AGR_003") == "2"), "NaN")
                 .when(sheep_2002 & (F.col("AREA_AGR_AGR_003") == "3"), "Infinity")
                 .otherwise(F.col("OBS_VALUE")))
            .withColumn("OBS_STATUS",
                F.when(sheep_2002 & (F.col("AREA_AGR_AGR_003") == "4"), "unknown")
                 .otherwise(F.col("OBS_STATUS")))
            .withColumn("YEAR_AGR_AGR_003",
                F.when(sheep_2002 & (F.col("AREA_AGR_AGR_003") == "5"), "not-a-year")
                 .otherwise(F.col("YEAR_AGR_AGR_003"))))
        write_bronze(bad)
        run_notebook(spark, NOTEBOOKS[1], show=False)
        rejected = spark.table(f"{fq}.quarantine_livestock").collect()
        check(len(rejected) == 5, f"expected 5 malformed rows in quarantine, got {len(rejected)}")
        expected = {"1": "value_iff_suppressed", "2": "head_non_negative",
                    "3": "head_non_negative", "4": "status_known", "5": "year_in_range"}
        check(all(expected[r.area_code] in r.broken_rules for r in rejected),
              "malformed rows were not assigned the expected quarantine rules")
        check(spark.table(f"{fq}.silver_livestock_regional").count() == 1392,
              "malformed rows survived in silver")
        print("malformed values, years, NaN, infinity and unknown statuses are quarantined")

        # Restore the baseline before checking failures that must not publish.
        write_bronze(bronze)
        run_notebook(spark, NOTEBOOKS[1], show=False)
        unchanged()

        write_bronze(bronze.withColumn("OBS_VALUE", F.lit("-1")))
        expect_failure(NOTEBOOKS[1], "Reject rate")
        check(spark.table(f"{fq}.quarantine_livestock").count() == 1397,
              "blocking failure did not preserve rejected rows in quarantine")
        unchanged()

        missing_national = bronze.filter(~(sheep_2002 & (F.col("AREA_AGR_AGR_003") == "20")))
        write_bronze(missing_national)
        expect_failure(NOTEBOOKS[1], "national total is required")
        unchanged()

        island_cell = sheep_2002 & (F.col("AREA_AGR_AGR_003") == "10")
        write_bronze(bronze.filter(~island_cell))
        expect_failure(NOTEBOOKS[1], "island total is required")
        unchanged()

        suppressed_island = (bronze
            .withColumn("OBS_VALUE", F.when(island_cell, F.lit(None).cast("string"))
                        .otherwise(F.col("OBS_VALUE")))
            .withColumn("OBS_STATUS", F.when(island_cell, "s")
                        .otherwise(F.col("OBS_STATUS"))))
        write_bronze(suppressed_island)
        expect_failure(NOTEBOOKS[1], "island total is required")
        unchanged()

        write_bronze(bronze.filter(F.col("YEAR_AGR_AGR_003") != "2002"))
        expect_failure(NOTEBOOKS[1], "Year coverage changed")
        unchanged()

        write_bronze(bronze.limit(0))
        expect_failure(NOTEBOOKS[1], "No candidate livestock rows")
        unchanged()
        print("reject-rate, aggregate coverage, year coverage and empty-input failures preserve silver")
    finally:
        write_bronze(bronze)
        bronze.unpersist()


def main():
    with tempfile.TemporaryDirectory(prefix="nz-sheep-spark-") as tmp:
        spark = make_spark(pathlib.Path(tmp) / "warehouse")
        spark.sparkContext.setLogLevel("ERROR")
        try:
            run_notebooks(spark)
            check_against_r_outputs(spark)
            check_coverage_denominators(spark)
            check_failure_paths(spark)
        finally:
            spark.stop()
    print("\nport check: PASS")


if __name__ == "__main__":
    sys.exit(main())
