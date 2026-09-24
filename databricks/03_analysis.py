# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,03 - Analysis and reconciliation
# MAGIC %md
# MAGIC # 03 - Analysis and reconciliation
# MAGIC
# MAGIC National change, regional contribution, reconciliation tiers, coverage,
# MAGIC and dairy window counterpoint.
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
dbutils.widgets.text("run_id", "manual")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
RUN_ID = dbutils.widgets.get("run_id")
for key, value in {"catalog": CATALOG, "schema": SCHEMA}.items():
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"invalid {key}: {value!r}")
if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", RUN_ID):
    raise ValueError(f"invalid run_id: {RUN_ID!r}")

FQ = f"`{CATALOG}`.`{SCHEMA}`"
print(FQ)

# COMMAND ----------

# DBTITLE 1,Window and dimensions
from functools import reduce

from pyspark.sql import functions as F

s = spark.table(f"{FQ}.silver_livestock_regional")

# Derived rather than repeated: 02 has already required every year of the
# window, so its ends are silver's ends. The region count comes from the
# dimension, as R derives it from AREA, not from a literal 17.
YEARS = sorted(r[0] for r in s.select("year").distinct().collect())
START_YEAR, END_YEAR = YEARS[0], YEARS[-1]
LAST_CENSUS = s.filter("is_census_year").agg(F.max("year")).first()[0]
# Where the national dairy herd peaks in this sample; chosen after looking at
# the series, as the report says.
DAIRY_PEAK_YEAR = 2014
peak = (s.filter((F.col("area_code") == "20") & (F.col("livestock_class") == "Dairy cattle"))
    .orderBy(F.desc("head")).first())
if peak["year"] != DAIRY_PEAK_YEAR:
    raise ValueError(f"DAIRY_PEAK_YEAR is {DAIRY_PEAK_YEAR} but the national dairy herd "
                     f"peaks in {peak['year']}")
EXPECTED_REGIONS = spark.table(f"{FQ}.dim_area").filter(~F.col("is_aggregate")).count()
N_CLASSES = spark.table(f"{FQ}.dim_livestock").count()
print(START_YEAR, END_YEAR, LAST_CENSUS, EXPECTED_REGIONS, N_CLASSES)
# Every gold table records the run that wrote it and the extract it came
# from, so a number on a dashboard can be traced back to a hash.
SOURCE_SHA256 = [r[0] for r in s.select("_source_sha256").distinct().collect()]
if len(SOURCE_SHA256) != 1:
    raise ValueError(f"silver mixes extracts: {SOURCE_SHA256}")

def save(df, name):
    (df.withColumn("_run_id", F.lit(RUN_ID))
       .withColumn("_source_sha256", F.lit(SOURCE_SHA256[0]))
       .write.mode("overwrite").option("overwriteSchema", "true")
       .saveAsTable(f"{FQ}.{name}"))

# COMMAND ----------

# DBTITLE 1,National change
nat = (s.filter(F.col("area_code") == "20")
    .filter(F.col("year").isin(START_YEAR, END_YEAR))
    .groupBy("livestock_class").pivot("year", [START_YEAR, END_YEAR]).agg(F.first("head"))
    .select("livestock_class",
            F.col(str(START_YEAR)).alias("start_head"),
            F.col(str(END_YEAR)).alias("end_head"))
    .withColumn("start_year", F.lit(START_YEAR))
    .withColumn("end_year", F.lit(END_YEAR))
    .withColumn("change_head", F.col("end_head") - F.col("start_head")))
if nat.count() != N_CLASSES or nat.filter(F.col("change_head").isNull()).count():
    raise ValueError("gold_national_change is incomplete")
save(nat, "gold_national_change")
display(nat)

# COMMAND ----------

# DBTITLE 1,Regional contribution
# A region enters only if both endpoints are published.
# A region suppressed at either end would otherwise read as a fall to zero.
reg = (s.filter(~F.col("is_aggregate"))
    .filter(F.col("livestock_class") == "Sheep")
    .filter(F.col("head").isNotNull())
    .select("region", "year", "head"))

first = reg.filter(F.col("year") == START_YEAR).select("region", F.col("head").alias("start_head"))
last = reg.filter(F.col("year") == END_YEAR).select("region", F.col("head").alias("end_head"))

change = first.join(last, "region").withColumn("change", F.col("end_head") - F.col("start_head"))
totals = change.agg(
    F.sum(F.when(F.col("change") < 0, F.col("change"))).alias("fall"),
    F.sum("start_head").alias("start_total")).first()
if totals["fall"] is None:
    raise ValueError("No measurable region declined; share_of_fall is undefined")

# Unrounded, as the R outputs are: rounding belongs to whatever displays the
# table, and a sum of rounded shares does not reproduce the rounded total.
gold = (change
    .withColumn("share_of_fall", 100 * F.col("change") / F.lit(totals["fall"]))
    .withColumn("share_of_start", 100 * F.col("start_head") / F.lit(totals["start_total"]))
    .orderBy("change"))
save(gold, "gold_regional_change")
display(gold)

# COMMAND ----------

# DBTITLE 1,Reconciliation in tiers
regional = (s.filter(~F.col("is_aggregate"))
    .groupBy("livestock_class", "year")
    .agg(F.coalesce(F.sum("head"), F.lit(0)).alias("region_sum"),
         F.count("*").alias("regions_present"),
         F.sum(F.col("suppressed").cast("int")).alias("regions_suppressed")))

published = (s.filter(F.col("area_code") == "20")
    .select("livestock_class", "year", F.col("head").alias("published")))

# Left join from the published totals, so a class-year with no regional rows
# at all still appears (as incomplete) instead of silently disappearing.
recon = (published.join(regional, ["livestock_class", "year"], "left")
    .fillna({"region_sum": 0, "regions_present": 0, "regions_suppressed": 0})
    .withColumn("residual", F.col("published") - F.col("region_sum"))
    .withColumn("residual_pct",
        F.when(F.col("published") > 0, 100 * F.col("residual") / F.col("published")))
    .withColumn("fully_published",
        (F.col("regions_present") == EXPECTED_REGIONS) & (F.col("regions_suppressed") == 0))
    # A null published total cannot reach here (02 refuses it), but if it
    # did, case logic would treat the null comparison as false and label the
    # class-year "off by a few head". It is named instead.
    .withColumn("tier",
        F.when(F.col("published").isNull(), F.lit("Missing national total"))
         .when(~F.col("fully_published"), F.lit("Incomplete region row"))
         .when(F.col("residual") == 0, F.lit("Exact"))
         .otherwise(F.lit("Fully published, off by a few head"))))

if recon.count() != len(YEARS) * N_CLASSES:
    raise ValueError("gold_reconciliation must cover every class-year")
save(recon, "gold_reconciliation")

display(recon.groupBy("tier")
    .agg(F.count("*").alias("class_years"),
         F.max(F.abs("residual")).alias("max_residual"))
    .orderBy("tier"))

# COMMAND ----------

# DBTITLE 1,Island reconciliation
# The two published island totals against the published national total:
# three aggregates this analysis never sums, so any difference is the source
# table's own.
islands = (s.filter(F.col("area_code").isin("10", "19", "20"))
    .groupBy("year", "livestock_class")
    .pivot("area_code", ["10", "19", "20"]).agg(F.first("head"))
    .select("year", "livestock_class",
            F.col("10").alias("a10"), F.col("19").alias("a19"), F.col("20").alias("a20"))
    .withColumn("residual", F.col("a20") - (F.col("a10") + F.col("a19"))))
if (islands.count() != len(YEARS) * N_CLASSES or
        islands.filter(F.col("residual").isNull()).count()):
    raise ValueError("gold_island_reconciliation is incomplete")
save(islands, "gold_island_reconciliation")

# COMMAND ----------

# DBTITLE 1,Coverage
# coverage: SHEEP ONLY, over the regional council areas
# Match the R table's two denominators and units: unrounded fractions over
# observed rows and all expected regions. Absent regions are not suppression.
cov = (s.filter(~F.col("is_aggregate") & (F.col("livestock_class") == "Sheep"))
    .groupBy("year")
    .agg(F.count("*").alias("regions_present"),
         F.count("head").alias("regions_with_value"),
         F.sum(F.col("suppressed").cast("int")).alias("regions_suppressed"))
    .withColumn("regions_expected", F.lit(EXPECTED_REGIONS))
    .withColumn("regions_absent", F.lit(EXPECTED_REGIONS) - F.col("regions_present"))
    .withColumn("suppression_rate",
        F.col("regions_suppressed") / F.col("regions_present"))
    .withColumn("suppression_rate_all_regions",
        F.col("regions_suppressed") / F.lit(EXPECTED_REGIONS))
    .orderBy("year"))

# group_by emits no row for a year with no regional sheep rows at all, which
# would drop that year from the table that exists to report incompleteness.
got = sorted(r["year"] for r in cov.select("year").collect())
if got != YEARS:
    raise ValueError(f"gold_coverage is missing years: {sorted(set(YEARS) - set(got))}")
save(cov, "gold_coverage")
display(cov)

# COMMAND ----------

# DBTITLE 1,Dairy windows
# the counterpoint: the direction depends on the window you choose
windows = [(START_YEAR, DAIRY_PEAK_YEAR), (DAIRY_PEAK_YEAR, END_YEAR),
           (START_YEAR, LAST_CENSUS)]
census = set(r["year"] for r in s.filter("is_census_year").select("year").distinct().collect())
design = lambda y: F.lit("census" if y in census else "survey")
frames = []
for y0, y1 in windows:
    pivoted = (s.filter((F.col("area_code") == "20") & F.col("year").isin(y0, y1))
        .groupBy("livestock_class").pivot("year", [y0, y1]).agg(F.first("head")))
    frames.append(pivoted.select(
        F.lit(y0).alias("start_year"),
        F.lit(y1).alias("end_year"),
        "livestock_class",
        F.col(str(y0)).alias("start_head"),
        F.col(str(y1)).alias("end_head"),
        (F.col(str(y1)) - F.col(str(y0))).alias("change_head"),
        # Unrounded, as in the R CSV.
        (100 * (F.col(str(y1)) - F.col(str(y0))) / F.col(str(y0))).alias("change_pct"),
        design(y0).alias("start_design"),
        design(y1).alias("end_design")))

dw = reduce(lambda a, b: a.unionByName(b), frames)
if (dw.count() != len(windows) * N_CLASSES or
        dw.filter(F.col("change_pct").isNull()).count()):
    raise ValueError("gold_dairy_windows is incomplete")
save(dw, "gold_dairy_windows")
display(dw.orderBy("livestock_class", "start_year"))
