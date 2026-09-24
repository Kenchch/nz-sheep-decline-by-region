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
unmapped cells, unknown flags and dataflows, suppressed or missing aggregates,
missing years, a changed column set and empty input -- and checks that each one
is quarantined or refused, with ANSI mode on and off, and that no failed
quality gate replaces the last good silver table.

Usage, from the repository root, with Java 17+ on the PATH:

    pip install --require-hashes -r databricks/requirements.txt
    python databricks/run_local.py

This work is based on Stats NZ's data (Agricultural production statistics,
AGR_AGR_003), licensed by Stats NZ for re-use under the Creative Commons
Attribution 4.0 International licence.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile
import types
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F


def check(condition: bool, message: str) -> None:
    """A check that survives `python -O`, which strips assert statements."""
    if not condition:
        raise SystemExit(f"port check: FAIL -- {message}")


def close(a, b) -> bool:
    """Equal to within floating-point noise, element-wise, NaN equal to NaN."""
    return bool(np.isclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float),
                           rtol=0, atol=1e-9, equal_nan=True).all())


REPO = pathlib.Path(__file__).resolve().parents[1]
NOTEBOOKS = ["01_ingest_and_pin.py", "02_quality_gate.py", "03_analysis.py"]
CATALOG, SCHEMA = "spark_catalog", "nz_livestock"
FQ = f"{CATALOG}.{SCHEMA}"
RAW_DIR = REPO / "data-raw"
EXTRACT = "agr_agr_003_2026-09-04.csv"

# The R pipeline's analysis table: the reference every comparison is against,
# and the source of the window and row counts, so none is typed here.
R_TABLE = pd.read_csv(REPO / "outputs/livestock_regional.csv", dtype={"area_code": str})
START_YEAR, END_YEAR = int(R_TABLE["year"].min()), int(R_TABLE["year"].max())
N_REGIONS = int(R_TABLE.loc[~R_TABLE["is_aggregate"], "area_code"].nunique())


class Widgets:
    """Enough of dbutils.widgets for the three notebooks."""

    def __init__(self, overrides: dict | None = None):
        self.values = {"catalog": CATALOG, "schema": SCHEMA}
        self.values.update(overrides or {})

    def removeAll(self) -> None:
        self.values.clear()

    def text(self, name: str, default: str) -> None:
        self.values.setdefault(name, default)

    def get(self, name: str) -> str:
        return self.values[name]


class Notebook:
    # dbutils.notebook.exit ends the notebook. Here it only reports, which is
    # equivalent as long as the notebooks call it as their last statement,
    # as 01 does.
    def exit(self, message: str) -> None:
        print("notebook exit:", message)


def make_spark(warehouse: pathlib.Path) -> SparkSession:
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


def run_notebook(spark: SparkSession, name: str, overrides: dict | None = None,
                 show: bool = True, raw_dir: pathlib.Path = RAW_DIR) -> dict:
    """Execute one notebook and return its globals, for checks on its state."""
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
    scope = {"spark": spark, "dbutils": dbutils,
             "display": (lambda df: df.show(5, truncate=False)) if show else lambda df: None}
    exec(compile(source, name, "exec"), scope)
    return scope


def run_notebooks(spark: SparkSession) -> None:
    for name in NOTEBOOKS:
        run_notebook(spark, name)


def table(spark: SparkSession, name: str) -> pd.DataFrame:
    return spark.table(f"{FQ}.{name}").toPandas()


def expect_failure(spark: SparkSession, name: str, message: str,
                   overrides: dict | None = None, raw_dir: pathlib.Path = RAW_DIR) -> None:
    try:
        run_notebook(spark, name, overrides=overrides, show=False, raw_dir=raw_dir)
    except ValueError as exc:
        check(message in str(exc), f"{name}: unexpected failure: {exc}")
    else:
        check(False, f"{name} accepted input that should fail with: {message}")


# --- comparison with the R outputs ------------------------------------------

def compare(gold: pd.DataFrame, r_csv: pd.DataFrame, keys: list[str], exact: list[str],
            approx: tuple[str, ...] | list[str] = (), label: str = "") -> pd.DataFrame:
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


def check_rule_summary(spark: SparkSession) -> None:
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
    print("quality_rule_summary matches validation-summary.csv")


def check_against_r_outputs(spark: SparkSession) -> None:
    print("\n===== silver and gold tables against outputs/*.csv")

    silver = table(spark, "silver_livestock_regional")
    # Two-valued, never null: this is the flag every rule reads.
    check(silver["suppressed"].notna().all(), "suppressed is null on some rows")
    check(set(silver["suppressed"].unique()) == {False, True},
          "suppressed is not two-valued")
    compare(silver, R_TABLE, ["year", "area_code", "livestock_class"],
            ["region", "island", "is_aggregate", "suppressed", "suppression_code",
             "is_census_year", "head"], label="silver")

    quarantine = table(spark, "quarantine_livestock")
    check(len(quarantine) == 0, f"{len(quarantine)} rows in quarantine")
    print("quarantine is empty on the pinned extract")
    check_rule_summary(spark)

    compare(table(spark, "gold_reconciliation"),
            pd.read_csv(REPO / "outputs/residual-tiers.csv"), ["year", "livestock_class"],
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
            pd.read_csv(REPO / "outputs/class-comparison-windows.csv"),
            ["start_year", "end_year", "livestock_class"],
            ["start_head", "end_head", "change_head", "start_design", "end_design"],
            ["change_pct"], label="gold_dairy_windows")

    # No committed CSV holds the national or regional change, so both are
    # recomputed here from the analysis table the R pipeline committed, the
    # same way the report computes them.
    ends = [START_YEAR, END_YEAR]
    r_nat = (R_TABLE[(R_TABLE["area_code"] == "20") & R_TABLE["year"].isin(ends)]
             .pivot(index="livestock_class", columns="year", values="head"))
    r_nat = pd.DataFrame({"livestock_class": r_nat.index,
                          "start_head": r_nat[START_YEAR].values,
                          "end_head": r_nat[END_YEAR].values,
                          "change_head": (r_nat[END_YEAR] - r_nat[START_YEAR]).values})
    compare(table(spark, "gold_national_change"), r_nat, ["livestock_class"],
            ["start_head", "end_head", "change_head"], label="gold_national_change")

    r_sheep = R_TABLE[(R_TABLE["livestock_class"] == "Sheep") &
                      (~R_TABLE["is_aggregate"]) & (R_TABLE["year"].isin(ends))]
    wide = r_sheep.pivot(index="region", columns="year", values="head").dropna()
    r_change = pd.DataFrame({
        "region": wide.index,
        "change": (wide[END_YEAR] - wide[START_YEAR]).values,
        "share_of_start": (100 * wide[START_YEAR] / wide[START_YEAR].sum()).values})
    r_change["share_of_fall"] = (100 * r_change["change"] /
                                 r_change.loc[r_change["change"] < 0, "change"].sum())
    compare(table(spark, "gold_regional_change"), r_change, ["region"], ["change"],
            ["share_of_fall", "share_of_start"], label="gold_regional_change")

    # Lineage: every gold table names the run and the extract it came from.
    pinned = spark.table(f"{FQ}.ingest_manifest").orderBy(F.desc("ingested_at")).first()
    for name in ["gold_national_change", "gold_regional_change", "gold_reconciliation",
                 "gold_island_reconciliation", "gold_coverage", "gold_dairy_windows"]:
        lineage = spark.table(f"{FQ}.{name}").select("_run_id", "_source_sha256").distinct().collect()
        check(len(lineage) == 1 and lineage[0]["_source_sha256"] == pinned["sha256"],
              f"{name} does not carry the run and extract that produced it: {lineage}")
    print("every gold table carries its run id and source hash")


def check_coverage_denominators(spark: SparkSession) -> None:
    # In the pinned data every year with absent regions has zero suppressed
    # cells, so the two denominators happen to yield the same fraction. Add
    # one suppressed row in such a year to distinguish the definitions.
    original = spark.table(f"{FQ}.gold_coverage").localCheckpoint(eager=True)
    s = spark.table(f"{FQ}.silver_livestock_regional")
    year = int(R_TABLE.loc[R_TABLE["year"] > START_YEAR, "year"].min())
    target = ((F.col("year") == year) & (F.col("area_code") == "1") &
              (F.col("livestock_class") == "Sheep"))
    check(s.filter(target & ~F.col("suppressed")).count() == 1,
          f"coverage regression requires one published Northland sheep row in {year}")
    s = (s.withColumn("head", F.when(target, F.lit(None).cast("bigint")).otherwise(F.col("head")))
          .withColumn("suppressed", F.when(target, True).otherwise(F.col("suppressed")))
          .withColumn("suppression_code", F.when(target, "s").otherwise(F.col("suppression_code"))))
    source = (REPO / "databricks" / NOTEBOOKS[2]).read_text(encoding="utf-8")
    marker = "# DBTITLE 1,Coverage"
    check(source.count(marker) == 1, "coverage cell could not be identified")
    coverage_cell = source.split(marker, 1)[1].split("# COMMAND ----------", 1)[0]

    def save(df: DataFrame, name: str) -> None:
        df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{FQ}.{name}")

    try:
        exec(compile(coverage_cell, NOTEBOOKS[2] + ":coverage", "exec"),
             {"s": s, "F": F, "FQ": FQ, "EXPECTED_REGIONS": N_REGIONS, "save": save,
              "YEARS": list(range(START_YEAR, END_YEAR + 1)), "display": lambda df: None})
        row = spark.table(f"{FQ}.gold_coverage").filter(F.col("year") == year).first()
        check(row.regions_present < N_REGIONS and row.regions_suppressed == 1,
              "coverage regression did not retain absent and suppressed regions")
        check(abs(row.suppression_rate - 1 / row.regions_present) < 1e-12 and
              abs(row.suppression_rate_all_regions - 1 / N_REGIONS) < 1e-12,
              "coverage rates do not use their respective denominators and fraction units")
        check(row.regions_with_value == row.regions_present - 1,
              "coverage counts a suppressed cell as a published value")
        print("coverage distinguishes absent regions from suppressed regions")
    finally:
        save(original, "gold_coverage")
        original.unpersist()


# --- ingestion ---------------------------------------------------------------

def rewrite_extract(tmp: pathlib.Path, label: str,
                    edit: Callable[[list[bytes]], list[bytes]]) -> dict:
    """Write an edited copy of the extract and return the widgets to ingest it.

    The copy's own hash is supplied as a parameter, which gets it past the
    hash gate to whatever check the edit is meant to reach.
    """
    lines = (RAW_DIR / EXTRACT).read_bytes().split(b"\r\n")
    data = b"\r\n".join(edit(lines))
    path = tmp / f"{label}.csv"
    path.write_bytes(data)
    return {"source_file": path.name, "expected_sha256": hashlib.sha256(data).hexdigest()}


def check_ingest_failures(spark: SparkSession, tmp: pathlib.Path) -> None:
    print("\n===== ingestion")
    # This also verifies that a supplied widget overrides the default hash.
    expect_failure(spark, NOTEBOOKS[0], "Pinned extract does not match",
                   {"expected_sha256": "0" * 64})
    expect_failure(spark, NOTEBOOKS[0], "bare file name",
                   {"source_file": "../" + EXTRACT})
    expect_failure(spark, NOTEBOOKS[0], "invalid schema", {"schema": "nz-livestock"})
    expect_failure(spark, NOTEBOOKS[0], "invalid run_id", {"run_id": "a b"})

    def header(new: bytes):
        return lambda lines: [new] + lines[1:]

    def with_extra_field(lines):
        return [lines[0] + b",UNIT"] + [line + b"," if line else line for line in lines[1:]]

    def on_first_row(old: bytes, new: bytes):
        return lambda lines: [lines[0], lines[1].replace(old, new, 1)] + lines[2:]

    first_row = (RAW_DIR / EXTRACT).read_bytes().split(b"\r\n")[1]
    first_status = first_row.rsplit(b",", 1)
    for label, edit, message in [
            ("dropped", header(b"DATAFLOW,LIVESTOCK_AGR_AGR_003,AREA_AGR_AGR_003,"
                               b"YEAR_AGR_AGR_003,OBS_VALUE,OBS_FLAG"), "missing required column"),
            ("extra", with_extra_field, "unexpected column"),
            ("dataflow", on_first_row(b"STATSNZ:AGR_AGR_003(1.0)", b"STATSNZ:OTHER(2.0)"),
             "DATAFLOW other than"),
            ("status", lambda lines: [lines[0], first_status[0] + b",x"] + lines[2:],
             "Unknown OBS_STATUS")]:
        tmp_dir = pathlib.Path(tmp)
        expect_failure(spark, NOTEBOOKS[0], message, rewrite_extract(tmp_dir, label, edit),
                       raw_dir=tmp_dir)
    print("bad hash, unsafe parameters, changed columns, another dataflow and an "
          "unknown flag stop ingestion")

    # A deliberate override is accepted, and recorded as one. A trailing blank
    # line changes the hash without changing the data.
    tmp_dir = pathlib.Path(tmp)
    run_notebook(spark, NOTEBOOKS[0], show=False, raw_dir=tmp_dir,
                 overrides=rewrite_extract(tmp_dir, "override", lambda lines: lines + [b""]))
    latest = spark.table(f"{FQ}.ingest_manifest").orderBy(F.desc("ingested_at")).first()
    check(latest["hash_overridden"] is True, "a hash override was not recorded in the manifest")

    # The pinned run: not an override, and bronze is materialised before the
    # second hash, so nothing downstream reads the file again.
    scope = run_notebook(spark, NOTEBOOKS[0], show=False)
    latest = spark.table(f"{FQ}.ingest_manifest").orderBy(F.desc("ingested_at")).first()
    check(latest["hash_overridden"] is False, "the pinned hash was recorded as an override")
    plan = scope["bronze"]._jdf.queryExecution().executedPlan().toString()
    check("FileScan" not in plan,
          "bronze still reads the file lazily after the second hash:\n" + plan)
    print("a hash override is recorded; bronze is read once, before the second hash")


# --- quality gate --------------------------------------------------------------

@dataclass
class Gate:
    """The pinned bronze table and the silver it produced, for failure scenarios."""
    spark: SparkSession
    bronze: DataFrame
    silver_before: set

    def write_bronze(self, frame: DataFrame) -> None:
        frame.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
            f"{FQ}.bronze_agr_agr_003")

    def unchanged(self) -> None:
        check(set(self.spark.table(f"{FQ}.silver_livestock_regional").collect()) ==
              self.silver_before, "failed quality gate overwrote the previous silver table")

    def refused(self, frame: DataFrame, message: str = "failed blocking rules") -> None:
        self.write_bronze(frame)
        expect_failure(self.spark, NOTEBOOKS[1], message)
        self.unchanged()

    def quarantined(self, expected: dict[tuple[str, str], str]) -> list:
        rows = self.spark.table(f"{FQ}.quarantine_livestock").collect()
        got: dict[tuple[str, str], list[set]] = {}
        for r in rows:
            got.setdefault((r.area_code, r.YEAR_AGR_AGR_003), []).append(set(r.broken_rules))
        for key, rule in expected.items():
            check(key in got and all(rule in rules for rules in got[key]),
                  f"row {key} was not quarantined for {rule}: {got.get(key)}")
        return rows


SHEEP = F.col("LIVESTOCK_AGR_AGR_003") == "6731"
START = str(START_YEAR)
SHEEP_START = SHEEP & (F.col("YEAR_AGR_AGR_003") == START)
CANTERBURY_END = SHEEP & (F.col("YEAR_AGR_AGR_003") == str(END_YEAR)) & \
    (F.col("AREA_AGR_AGR_003") == "15")


def with_value(frame: DataFrame, cell: Column, value, column: str = "OBS_VALUE") -> DataFrame:
    return frame.withColumn(column, F.when(cell, value).otherwise(F.col(column)))


def withheld(frame: DataFrame, cell: Column) -> DataFrame:
    return with_value(with_value(frame, cell, F.lit(None).cast("string")), cell, "s", "OBS_STATUS")


def check_malformed_rows(gate: Gate) -> None:
    # Row-level failures, one per rule, all in a single run, with ANSI mode on
    # and off: casts that raise under one mode return null under the other,
    # and either way the row must reach quarantine rather than silver.
    area = lambda code: SHEEP_START & (F.col("AREA_AGR_AGR_003") == code)
    bad = gate.bronze
    for code, value in [("1", "not-a-number"), ("2", "NaN"), ("3", "Infinity"),
                        ("6", "4192693.5"), ("7", "1e3"), ("8", "-5"),
                        ("9", "9" * 20)]:
        bad = with_value(bad, area(code), value)
    bad = with_value(bad, area("4"), "unknown", "OBS_STATUS")
    years = {"5": "not-a-year", "11": " " + START, "12": "+" + START, "13": "0" + START}
    for code, year in years.items():
        bad = with_value(bad, area(code), year, "YEAR_AGR_AGR_003")
    expected = {(c, START): "value_is_count" for c in ["1", "2", "3", "6", "7", "9"]}
    expected.update({("8", START): "head_non_negative", ("4", START): "status_known"})
    expected.update({(c, y): "year_in_range" for c, y in years.items()})
    for ansi in ["true", "false"]:
        gate.spark.conf.set("spark.sql.ansi.enabled", ansi)
        gate.refused(bad)
        rows = gate.quarantined(expected)
        check(len(rows) == len(expected),
              f"ANSI {ansi}: expected {len(expected)} rows in quarantine, got {len(rows)}")
    gate.spark.conf.set("spark.sql.ansi.enabled", "true")
    print("malformed values (including a 20-digit count), padded or signed years and "
          "unknown statuses are quarantined, with ANSI on and off")


def check_single_cells(gate: Gate) -> None:
    # A single bad cell is enough. Before, a reject-rate tolerance let one
    # through and silently replaced Canterbury in the top three.
    b = gate.bronze
    end = str(END_YEAR)
    for label, frame, key, rule in [
            ("duplicate", b.unionByName(b.filter(CANTERBURY_END)), ("15", end), "no_duplicate_cells"),
            ("unmapped area", with_value(b, CANTERBURY_END, "999", "AREA_AGR_AGR_003"),
             ("999", end), "region_label_present"),
            ("fractional count", with_value(b, CANTERBURY_END, "4192693.5"),
             ("15", end), "value_is_count"),
            # value_iff_suppressed in both directions: without these, a rule
            # replaced by F.lit(True) still passed every scenario.
            ("flagged published value", with_value(b, CANTERBURY_END, "s", "OBS_STATUS"),
             ("15", end), "value_iff_suppressed"),
            ("unflagged blank", with_value(b, CANTERBURY_END, F.lit(None).cast("string")),
             ("15", end), "value_iff_suppressed")]:
        gate.refused(frame)
        gate.quarantined({key: rule})
        print(f"one {label} cell stops publication")

    gate.refused(b.withColumn("OBS_VALUE", F.lit("-1")))
    check(gate.spark.table(f"{FQ}.quarantine_livestock").count() == len(R_TABLE),
          "blocking failure did not preserve rejected rows in quarantine")


def check_table_contracts(gate: Gate) -> None:
    b = gate.bronze
    national = SHEEP_START & (F.col("AREA_AGR_AGR_003") == "20")
    island = SHEEP_START & (F.col("AREA_AGR_AGR_003") == "10")
    gate.refused(b.filter(~national), "national total is required")
    gate.refused(withheld(b, national), "national total is required")
    gate.refused(b.filter(~island), "island total is required")
    gate.refused(withheld(b, island), "island total is required")
    gate.refused(b.filter(F.col("YEAR_AGR_AGR_003") != START), "Year coverage changed")
    gate.refused(b.limit(0), "No candidate livestock rows")
    print("aggregate coverage, year coverage and empty-input failures preserve silver")

    # 03's own output contract: a year with no regional sheep rows passes 02
    # (the aggregates are still there) but must not vanish from gold_coverage.
    year = START_YEAR + 8
    gate.write_bronze(b.filter(~(SHEEP & (F.col("YEAR_AGR_AGR_003") == str(year)) &
                                 ~F.col("AREA_AGR_AGR_003").isin("10", "19", "20"))))
    run_notebook(gate.spark, NOTEBOOKS[1], show=False)
    expect_failure(gate.spark, NOTEBOOKS[2], f"gold_coverage is missing years: [{year}]")
    print("a year with no regional rows stops the analysis")


def check_failure_paths(spark: SparkSession) -> None:
    print("\n===== injected failures and publication protection")
    # Detach the snapshot from the table before overwriting it in scenarios.
    gate = Gate(spark,
                spark.table(f"{FQ}.bronze_agr_agr_003").localCheckpoint(eager=True),
                set(spark.table(f"{FQ}.silver_livestock_regional").collect()))
    try:
        spark.conf.set("spark.sql.ansi.enabled", "true")
        check_malformed_rows(gate)
        check_single_cells(gate)
        check_table_contracts(gate)
    finally:
        spark.conf.unset("spark.sql.ansi.enabled")
        gate.write_bronze(gate.bronze)
        gate.bronze.unpersist()
        # Leave the pipeline as the pinned extract produces it.
        run_notebook(spark, NOTEBOOKS[1], show=False)
        run_notebook(spark, NOTEBOOKS[2], show=False)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="nz-sheep-spark-") as tmp:
        spark = make_spark(pathlib.Path(tmp) / "warehouse")
        spark.sparkContext.setLogLevel("ERROR")
        try:
            run_notebooks(spark)
            check_against_r_outputs(spark)
            check_coverage_denominators(spark)
            check_ingest_failures(spark, pathlib.Path(tmp))
            check_failure_paths(spark)
            check_against_r_outputs(spark)
        finally:
            spark.stop()
    print("\nport check: PASS")


if __name__ == "__main__":
    sys.exit(main())
