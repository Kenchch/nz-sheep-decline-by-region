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
# MAGIC silver. Failed rows go to quarantine rather than being deleted.
# MAGIC
# MAGIC Source data: Stats NZ, Agricultural production statistics, licensed by Stats NZ
# MAGIC for re-use under the Creative Commons Attribution 4.0 International licence.

# COMMAND ----------

# DBTITLE 1,Parameters
# Keep existing values: Lakeflow task parameters override these defaults.
dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nz_livestock")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")

FQ = f"{CATALOG}.{SCHEMA}"
print(FQ)

# COMMAND ----------

# DBTITLE 1,Build candidate table
from pyspark.sql import functions as F

CENSUS_YEARS = [2002, 2007, 2012, 2017, 2022]
EXPECTED_YEARS = list(range(2002, 2026))

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
    .filter(F.col("year").isNull() | (F.col("year") >= 2002))
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
            "YEAR_AGR_AGR_003"))

print("candidate rows:", cand.count())  # expect 1397

# COMMAND ----------

# DBTITLE 1,Rules and quarantine
RULES = {
    "head_non_negative": F.col("head").isNull() | (
        (F.col("head") >= 0) & ~F.isnan("head") & (F.col("head") != float("inf"))),
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

summary = (checked
    .select(F.explode("broken_rules").alias("rule"))
    .groupBy("rule").count().orderBy("rule"))
display(summary)
# expect exactly one row: census_year_reported = 9

# COMMAND ----------

# DBTITLE 1,Publish silver or refuse
BLOCKING = ["head_non_negative", "value_iff_suppressed",
            "region_label_present", "no_duplicate_cells", "year_in_range",
            "status_known"]
MAX_REJECT_RATE = 0.01

is_rejected = F.coalesce(
    F.arrays_overlap("broken_rules", F.array(*[F.lit(b) for b in BLOCKING])),
    F.lit(False))
rejected = checked.filter(is_rejected)
# The complement of the same predicate, not `subtract`: subtract is EXCEPT
# DISTINCT, so it would also collapse any duplicate rows it did not reject.
clean = checked.filter(~is_rejected).drop(
    "broken_rules", "n_broken", "_value_missing", "OBS_STATUS", "OBS_VALUE",
    "YEAR_AGR_AGR_003")

n_all, n_bad = checked.count(), rejected.count()
rate = (n_bad / n_all) if n_all else 0.0
print(f"rows={n_all} rejected={n_bad} rate={rate:.4%}")

(rejected.write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(f"{FQ}.quarantine_livestock"))

if not n_all:
    raise ValueError("No candidate livestock rows. Previous silver left in place.")

if rate > MAX_REJECT_RATE:
    raise ValueError(
        f"Reject rate {rate:.2%} exceeds {MAX_REJECT_RATE:.0%}. "
        f"Previous silver left in place. Inspect {FQ}.quarantine_livestock.")

# COMMAND ----------

# DBTITLE 1,Validate before publishing
# Validate clean candidates before overwrite: failed coverage checks must not
# replace the last good silver table. Explicit raises also survive python -O.
s = clean

years = sorted(r[0] for r in s.select("year").distinct().collect())
if years != EXPECTED_YEARS:
    raise ValueError(f"Year coverage changed: {years}. Previous silver left in place.")

if s.filter(F.col("head").isNull() != F.col("suppressed")).count():
    raise ValueError("Every missing value must be suppressed, and every suppressed cell missing")

if s.filter(F.col("region").isNull()).count():
    raise ValueError("Unmapped AREA code")

nat = s.filter(F.col("area_code") == "20")
n_classes = dim_l.count()
if nat.count() != len(EXPECTED_YEARS) * n_classes:
    raise ValueError("A published national total is required once per class-year. "
                     "Previous silver left in place.")
if nat.filter(F.col("head").isNull()).count():
    raise ValueError("National totals are never suppressed. Previous silver left in place.")

# Match the R ingestion contract: both published island aggregates must be
# present for every class-year, including after rejected rows are removed.
islands = s.filter(F.col("area_code").isin("10", "19"))
if (islands.count() != 2 * len(EXPECTED_YEARS) * n_classes or
        islands.filter(F.col("head").isNull()).count()):
    raise ValueError("A published island total is required once per island-class-year. "
                     "Previous silver left in place.")

(clean.write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(f"{FQ}.silver_livestock_regional"))
print("silver rows:", clean.count())  # expect 1397, quarantine 0

print("all assertions passed")
