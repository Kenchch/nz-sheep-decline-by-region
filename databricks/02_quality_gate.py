# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,02 - Quality gate and quarantine
# MAGIC %md
# MAGIC # 02 - Quality gate and quarantine
# MAGIC
# MAGIC Reads bronze, joins to dimensions, validates data contracts, and writes
# MAGIC silver. Failed rows go to quarantine, and any failed row stops silver from
# MAGIC being published, as the R loader stops.
# MAGIC
# MAGIC This work is based on Stats NZ's data (Agricultural production statistics,
# MAGIC AGR_AGR_003), licensed by Stats NZ for re-use under the Creative Commons
# MAGIC Attribution 4.0 International licence (https://creativecommons.org/licenses/by/4.0/).

# COMMAND ----------

# DBTITLE 1,Parameters
import re

# Keep existing values: Lakeflow task parameters override these defaults.
dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nz_livestock")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
for key, value in {"catalog": CATALOG, "schema": SCHEMA}.items():
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"invalid {key}: {value!r}")

FQ = f"`{CATALOG}`.`{SCHEMA}`"
print(FQ)

# COMMAND ----------

# DBTITLE 1,Build candidate table
from pyspark.sql import functions as F

# The window and the census years, as in R/load.R. 03 derives what it needs
# from silver rather than repeating these.
START_YEAR, END_YEAR = 2002, 2025
CENSUS_YEARS = [2002, 2007, 2012, 2017, 2022]
EXPECTED_YEARS = list(range(START_YEAR, END_YEAR + 1))

bronze = spark.table(f"{FQ}.bronze_agr_agr_003")
dim_l = spark.table(f"{FQ}.dim_livestock")
dim_a = spark.table(f"{FQ}.dim_area")

cand = (bronze
    .withColumnRenamed("LIVESTOCK_AGR_AGR_003", "livestock_code")
    .withColumnRenamed("AREA_AGR_AGR_003", "area_code")
    .withColumn("year", F.expr("try_cast(YEAR_AGR_AGR_003 AS INT)"))
    # 1994 sits before the 2002 population change. Dropped explicitly here
    # rather than silently, so the exclusion is visible in the code.
    # Keep unparseable years so they reach quarantine instead of disappearing.
    .filter(F.col("year").isNull() | (F.col("year") >= START_YEAR))
    .join(F.broadcast(dim_l), "livestock_code", "inner")  # inner: admits only the 3 verified codes
    .join(F.broadcast(dim_a), "area_code", "left")
    # A suppressed cell is a cell we are not allowed to see. That is a
    # different thing from a cell containing no animals, so it becomes null
    # and is flagged - never zero, never dropped.
    #
    # OBS_STATUS is null on every published cell, and in Spark `null IN (...)`
    # is null, not false. Without the coalesce this flag is three-valued:
    # true, or null. Every rule and assertion below that reads it would then
    # evaluate to null on the published rows and silently pass, and the
    # coverage table would carry null where it should count zero suppressed
    # regions.
    .withColumn("suppressed",
        F.coalesce(F.col("OBS_STATUS").isin("s", "c"), F.lit(False)))
    .withColumn("suppression_code",
        F.when(F.col("suppressed"), F.col("OBS_STATUS")))
    .withColumn("_value_missing",
        F.length(F.trim(F.coalesce(F.col("OBS_VALUE"), F.lit("")))) == 0)
    # ANSI mode must not raise before the bad row can be quarantined.
    .withColumn("head", F.expr("try_cast(OBS_VALUE AS DOUBLE)"))
    .withColumn("is_census_year", F.col("year").isin(CENSUS_YEARS))
    .select("year", "area_code", "region", "island", "is_aggregate",
            "livestock_class", "head", "suppressed", "suppression_code",
            "is_census_year", "_value_missing", "OBS_STATUS", "OBS_VALUE",
            "YEAR_AGR_AGR_003", "_source_sha256", "_ingested_at"))

print("candidate rows:", cand.count())  # expect 1397

# COMMAND ----------

# DBTITLE 1,Rules and quarantine
RULES = {
    "head_non_negative": F.col("head").isNull() | (
        (F.col("head") >= 0) & ~F.isnan("head") & (F.col("head") != float("inf"))),
    # A head count is a non-negative whole number. try_cast to DOUBLE accepts
    # "4192693.5", "1e3" and "-5", so the original string is checked, as in
    # R/load.R.
    "value_is_count": F.col("_value_missing") | F.col("OBS_VALUE").rlike("^[0-9]+$"),
    "value_iff_suppressed": (
        (F.col("head").isNull() == F.col("suppressed")) &
        (F.col("_value_missing") == F.col("suppressed"))),
    "region_label_present": F.col("region").isNotNull(),
    "year_in_range": F.col("year").isin(EXPECTED_YEARS),
    "status_known": F.coalesce(F.col("OBS_STATUS"), F.lit("")).isin("", "s", "c"),
    # census_year_reported encodes an assumption that turns out to be FALSE.
    # Written as an implication: is_census_year <= !suppressed. It fails 9
    # times on this vintage and is kept, because the falsification is the
    # finding - withholding is keyed to confidentiality and imputation level,
    # not to coverage.
    "census_year_reported": ~F.col("is_census_year") | ~F.col("suppressed"),
}

# Each rule contributes its name when it fails and null when it holds; the
# nulls are then dropped. Not array_remove(..., None): array_remove is
# null-intolerant, so removing a null element returns a null array, which
# made every row's broken_rules null, the rule summary empty, and the
# quarantine unreachable.
broken = F.filter(F.array(*[
    F.when(~F.coalesce(cond, F.lit(False)), F.lit(name))
    for name, cond in RULES.items()]),
    lambda v: v.isNotNull())

# Duplicates need a window, not a row predicate.
from pyspark.sql import Window
w = Window.partitionBy("year", "area_code", "livestock_class")
checked = (cand
    .withColumn("_n_in_cell", F.count("*").over(w))
    .withColumn("broken_rules",
        F.when(F.col("_n_in_cell") > 1,
            F.array_union(broken, F.array(F.lit("no_duplicate_cells"))))
         .otherwise(broken))
    .withColumn("n_broken", F.size("broken_rules"))
    .drop("_n_in_cell"))

# One row per rule, including the rules that never fail, so the table can be
# compared with outputs/validation-summary.csv rather than only displayed.
RULE_NAMES = list(RULES) + ["no_duplicate_cells"]
fails = {r["rule"]: r["count"] for r in
         checked.select(F.explode("broken_rules").alias("rule"))
                .groupBy("rule").count().collect()}
summary = spark.createDataFrame(
    [(name, int(fails.get(name, 0))) for name in RULE_NAMES],
    "rule string, fails long")
summary.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{FQ}.quality_rule_summary")
display(summary)
# expect census_year_reported = 9 and every other rule 0

# COMMAND ----------

# DBTITLE 1,Publish silver or refuse
BLOCKING = ["head_non_negative", "value_is_count", "value_iff_suppressed",
            "region_label_present", "no_duplicate_cells", "year_in_range",
            "status_known"]

is_rejected = F.coalesce(
    F.arrays_overlap("broken_rules", F.array(*[F.lit(b) for b in BLOCKING])),
    F.lit(False))
rejected = checked.filter(is_rejected).withColumn("_checked_at", F.current_timestamp())
# The complement of the same predicate, not `subtract`: subtract is EXCEPT
# DISTINCT, so it would also collapse any duplicate rows it did not reject.
clean = (checked.filter(~is_rejected)
    .drop("broken_rules", "n_broken", "_value_missing", "OBS_STATUS", "OBS_VALUE",
          "YEAR_AGR_AGR_003")
    # Validated above as a whole number, so the cast is exact.
    .withColumn("head", F.col("head").cast("bigint")))

n_all, n_bad = checked.count(), rejected.count()
print(f"rows={n_all} rejected={n_bad}")

# Written on every run, including one that fails below: the quarantine shows
# the rows of the latest attempt, and _checked_at says when that was.
(rejected.write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(f"{FQ}.quarantine_livestock"))

if not n_all:
    raise ValueError("No candidate livestock rows. Previous silver left in place.")

# No tolerance. Publishing without a rejected row is a silent change to the
# analysis, not a cleaner version of it: losing one Canterbury sheep cell
# would drop Canterbury from the regional table and replace the headline's
# top three, and the coverage table would count the cell as never published.
# The R loader stops on the same input, and so does this.
if n_bad:
    raise ValueError(
        f"{n_bad} row(s) failed blocking rules; see {FQ}.quarantine_livestock. "
        "Previous silver left in place.")

# COMMAND ----------

# DBTITLE 1,Validate before publishing
# Validate clean candidates before overwrite: failed coverage checks must not
# replace the last good silver table. Explicit raises also survive python -O.
# Row-level contracts (values, flags, labels, duplicates) cannot fail here any
# more, because any row breaking one has already stopped the notebook above;
# these are the table-level contracts no single row can break.
s = clean

years = sorted(r[0] for r in s.select("year").distinct().collect())
if years != EXPECTED_YEARS:
    raise ValueError(f"Year coverage changed: {years}. Previous silver left in place.")

nat = s.filter(F.col("area_code") == "20")
n_classes = dim_l.count()
if nat.count() != len(EXPECTED_YEARS) * n_classes:
    raise ValueError("A published national total is required once per class-year. "
                     "Previous silver left in place.")
if nat.filter(F.col("head").isNull()).count():
    raise ValueError("A published national total is required once per class-year; "
                     "one is suppressed. Previous silver left in place.")

# Match the R ingestion contract: both published island aggregates must be
# present for every class-year.
islands = s.filter(F.col("area_code").isin("10", "19"))
if (islands.count() != 2 * len(EXPECTED_YEARS) * n_classes or
        islands.filter(F.col("head").isNull()).count()):
    raise ValueError("A published island total is required once per island-class-year. "
                     "Previous silver left in place.")

(clean.write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(f"{FQ}.silver_livestock_regional"))
print("silver rows:", clean.count())  # expect 1397, quarantine 0

print("all assertions passed")
