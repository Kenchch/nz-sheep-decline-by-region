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
        assert name != NOTEBOOKS[0] or volume_path in source, \
            f"{name} no longer builds the Volumes path this runner redirects"
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

    silver = table(spark, "silver_livestock_regional")
    r_table = pd.read_csv(REPO / "outputs/livestock_regional.csv",
                          dtype={"area_code": str})
    keys = ["year", "area_code", "livestock_class"]
    m = silver.merge(r_table, on=keys, suffixes=("", "_r"))
    assert len(silver) == len(r_table) == len(m) == 1397, \
        (len(silver), len(r_table), len(m))
    # Two-valued, never null: this is the flag every rule reads.
    assert set(silver["suppressed"].dropna().unique()) == {False, True}
    assert silver["suppressed"].notna().all()
    assert (m["suppressed"] == m["suppressed_r"]).all()
    same_head = (m["head"] == m["head_r"]) | (m["head"].isna() & m["head_r"].isna())
    assert same_head.all()
    print("silver matches the R analysis table, cell for cell")

    quarantine = table(spark, "quarantine_livestock")
    assert len(quarantine) == 0, quarantine
    print("quarantine is empty on the pinned extract")

    recon = table(spark, "gold_reconciliation")
    r_tiers = pd.read_csv(REPO / "outputs/residual-tiers.csv")
    m = recon.merge(r_tiers, on=["year", "livestock_class"], suffixes=("", "_r"))
    assert len(m) == 72
    for col in ["regions_present", "regions_suppressed", "region_sum",
                "published", "residual", "fully_published", "tier"]:
        assert (m[col] == m[f"{col}_r"]).all(), col
    print("gold_reconciliation matches residual-tiers.csv")

    coverage = table(spark, "gold_coverage")
    r_cov = pd.read_csv(REPO / "outputs/coverage-and-suppression.csv")
    m = coverage.merge(r_cov, on="year", suffixes=("", "_r"))
    assert len(m) == 24
    for col in ["regions_present", "regions_suppressed", "regions_expected",
                "regions_absent"]:
        assert (m[col] == m[f"{col}_r"]).all(), col
    # The gold rate is over the 17 expected regions, rounded to one decimal.
    assert ((m["suppression_rate"] -
             100 * m["suppression_rate_all_regions"]).abs() <= 0.05).all()
    print("gold_coverage matches coverage-and-suppression.csv")

    windows = table(spark, "gold_dairy_windows")
    r_win = pd.read_csv(REPO / "outputs/dairy-comparison-windows.csv")
    m = windows.merge(r_win, on=["start_year", "end_year", "livestock_class"],
                      suffixes=("", "_r"))
    assert len(m) == 9
    assert (m["change_head"] == m["change_head_r"]).all()
    assert ((m["change_pct"] - m["change_pct_r"]).abs() <= 0.05).all()
    print("gold_dairy_windows matches dairy-comparison-windows.csv")

    change = table(spark, "gold_regional_change")
    r_sheep = r_table[(r_table["livestock_class"] == "Sheep") &
                      (~r_table["is_aggregate"]) &
                      (r_table["year"].isin([2002, 2025]))]
    r_change = (r_sheep.pivot(index="region", columns="year", values="head")
                .dropna().eval("`2025` - `2002`"))
    assert len(change) == len(r_change) == 15
    m = change.set_index("region")["change"]
    assert (m.sort_index() == r_change.sort_index()).all()
    print("gold_regional_change matches the R sheep change for 15 regions")


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
