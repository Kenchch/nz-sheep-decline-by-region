"""Run the three Databricks notebooks on a local Spark session and check them.

The notebooks are written for Databricks: they read widgets through `dbutils`,
render with `display`, and write Unity Catalog tables. None of that exists
off-platform, so this script supplies the three names the notebooks expect
and executes each file in turn against a local Spark session whose catalog is
`spark_catalog`. The notebooks themselves are not modified; the only
substitution is the Volumes path, which is redirected at the pinned extract in
`data-raw/`.

It then asserts that silver and every gold table agree with the CSVs that the
R pipeline committed to `outputs/`. That is the claim the Databricks README
makes -- that this is a port of the same analysis -- checked rather than
asserted. It found the first defects: `array_remove(..., None)` returning a
null array, and `OBS_STATUS IN ('s', 'c')` being null rather than false on
every published cell, which together left the quarantine unreachable and the
coverage table counting null where it should count zero.

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

    def __init__(self):
        self.values = {"catalog": CATALOG, "schema": SCHEMA}

    def removeAll(self):
        pass

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
            .config("spark.sql.warehouse.dir", str(warehouse))
            # Arrow needs pyarrow, which is not required here; the fallback
            # is fine for a few thousand rows and quieter.
            .config("spark.sql.execution.arrow.pyspark.enabled", "false")
            # The in-memory catalog, not Hive: the three notebooks share one
            # session, so the tables only need to outlive the session, and a
            # Hive metastore would leave a Derby database in the working
            # directory.
            .getOrCreate())


def run_notebooks(spark):
    dbutils = types.SimpleNamespace(widgets=Widgets(), notebook=Notebook())
    for name in NOTEBOOKS:
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
              "display": lambda df: df.show(5, truncate=False), "F": F})


def table(spark, name):
    return spark.table(f"{CATALOG}.{SCHEMA}.{name}").toPandas()


def check_against_r_outputs(spark):
    print("\n===== gold tables against outputs/*.csv")

    # Spark rounds its percentages to one decimal; the R columns are exact
    # fractions. Compare at the same precision instead of with a tolerance
    # that sits on the rounding boundary.
    def same_rounded_pct(spark_col, r_fraction):
        return (spark_col == (100 * r_fraction).round(1)).all()

    silver = table(spark, "silver_livestock_regional")
    r_table = pd.read_csv(REPO / "outputs/livestock_regional.csv",
                          dtype={"area_code": str})
    keys = ["year", "area_code", "livestock_class"]
    m = silver.merge(r_table, on=keys, suffixes=("", "_r"))
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
    m = recon.merge(r_tiers, on=["year", "livestock_class"], suffixes=("", "_r"))
    check(len(m) == 72, f"{len(m)} class-years matched, expected 72")
    for col in ["regions_present", "regions_suppressed", "region_sum",
                "published", "residual", "fully_published", "tier"]:
        check((m[col] == m[f"{col}_r"]).all(),
              f"gold_reconciliation.{col} differs from residual-tiers.csv")
    print("gold_reconciliation matches residual-tiers.csv")

    coverage = table(spark, "gold_coverage")
    r_cov = pd.read_csv(REPO / "outputs/coverage-and-suppression.csv")
    m = coverage.merge(r_cov, on="year", suffixes=("", "_r"))
    check(len(m) == 24, f"{len(m)} years matched, expected 24")
    for col in ["regions_present", "regions_suppressed", "regions_expected",
                "regions_absent"]:
        check((m[col] == m[f"{col}_r"]).all(),
              f"gold_coverage.{col} differs from coverage-and-suppression.csv")
    # The gold rate is over the 17 expected regions.
    check(same_rounded_pct(m["suppression_rate"], m["suppression_rate_all_regions"]),
          "gold_coverage.suppression_rate differs from the R rate over 17 regions")
    print("gold_coverage matches coverage-and-suppression.csv")

    windows = table(spark, "gold_dairy_windows")
    r_win = pd.read_csv(REPO / "outputs/dairy-comparison-windows.csv")
    m = windows.merge(r_win, on=["start_year", "end_year", "livestock_class"],
                      suffixes=("", "_r"))
    check(len(m) == 9, f"{len(m)} windows matched, expected 9")
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


def main():
    with tempfile.TemporaryDirectory(prefix="nz-sheep-spark-") as tmp:
        spark = make_spark(pathlib.Path(tmp) / "warehouse")
        spark.sparkContext.setLogLevel("ERROR")
        try:
            run_notebooks(spark)
            check_against_r_outputs(spark)
        finally:
            spark.stop()
    print("\nport check: PASS")


if __name__ == "__main__":
    sys.exit(main())
