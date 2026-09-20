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
# MAGIC Source data: Stats NZ, Agricultural production statistics, licensed by Stats NZ
# MAGIC for re-use under the Creative Commons Attribution 4.0 International licence.

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.removeAll()

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nz_livestock")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")

FQ = f"{CATALOG}.{SCHEMA}"
print(FQ)

# COMMAND ----------

# DBTITLE 1,National change
from pyspark.sql import functions as F

s = spark.table(f"{FQ}.silver_livestock_regional")

nat = (s.filter(F.col("area_code") == "20")
    .filter(F.col("year").isin(2002, 2025))
    .groupBy("livestock_class").pivot("year").agg(F.first("head"))
    .withColumn("change", F.col("2025") - F.col("2002")))
display(nat)

# COMMAND ----------

# DBTITLE 1,Regional contribution
# A region enters only if both endpoints are published.
# A region suppressed at either end would otherwise read as a fall to zero.
reg = s.filter(~F.col("is_aggregate")) \
    .filter(F.col("livestock_class") == "Sheep") \
    .filter(F.col("head").isNotNull()) \
    .select("region", "year", "head")

ends = reg.groupBy("region").agg(F.min("year").alias("y0"), F.max("year").alias("y1"))
both = ends.filter((F.col("y0") == 2002) & (F.col("y1") == 2025)).select("region")

first = reg.join(both, "region").filter(F.col("year") == 2002) \
    .select("region", F.col("head").alias("head_2002"))
last = reg.join(both, "region").filter(F.col("year") == 2025) \
    .select("region", F.col("head").alias("head_2025"))

change = first.join(last, "region").withColumn("change", F.col("head_2025") - F.col("head_2002"))
total_fall = change.filter(F.col("change") < 0).agg(F.sum("change")).collect()[0][0]

gold = (change.withColumn("share_of_fall",
    F.round(100 * F.col("change") / F.lit(total_fall), 1))
    .orderBy("change"))
gold.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{FQ}.gold_regional_change")
display(gold)

# COMMAND ----------

# DBTITLE 1,Reconciliation in tiers
EXPECTED_REGIONS = 17

regional = (s.filter(~F.col("is_aggregate"))
    .groupBy("livestock_class", "year")
    .agg(F.sum("head").alias("region_sum"),
         F.count("*").alias("regions_present"),
         F.sum(F.col("suppressed").cast("int")).alias("regions_suppressed")))

published = (s.filter(F.col("area_code") == "20")
    .select("livestock_class", "year", F.col("head").alias("published")))

recon = (regional.join(published, ["livestock_class", "year"])
    .withColumn("residual", F.col("published") - F.col("region_sum"))
    .withColumn("fully_published",
        (F.col("regions_present") == EXPECTED_REGIONS) & (F.col("regions_suppressed") == 0))
    .withColumn("tier",
        F.when(~F.col("fully_published"), F.lit("Incomplete region row"))
         .when(F.col("residual") == 0, F.lit("Exact"))
         .otherwise(F.lit("Fully published, off by a few head"))))

recon.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{FQ}.gold_reconciliation")

display(recon.groupBy("tier")
    .agg(F.count("*").alias("class_years"),
         F.max(F.abs("residual")).alias("max_residual"))
    .orderBy("tier"))

# COMMAND ----------

# DBTITLE 1,Coverage
# coverage: SHEEP ONLY, over 17 regional council areas
cov = (s.filter(~F.col("is_aggregate") & (F.col("livestock_class") == "Sheep"))
    .groupBy("year")
    .agg(F.count("*").alias("regions_present"),
         F.sum(F.col("suppressed").cast("int")).alias("regions_suppressed"))
    .withColumn("regions_expected", F.lit(EXPECTED_REGIONS))
    .withColumn("regions_absent", F.lit(EXPECTED_REGIONS) - F.col("regions_present"))
    .withColumn("suppression_rate",
        F.round(100 * F.col("regions_suppressed") / F.lit(EXPECTED_REGIONS), 1))
    .orderBy("year"))
cov.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{FQ}.gold_coverage")
display(cov)

# COMMAND ----------

# DBTITLE 1,Dairy windows
# the counterpoint: the direction depends on the window you choose
windows = [(2002, 2014), (2014, 2025), (2002, 2022)]
frames = []
for y0, y1 in windows:
    pivoted = s.filter((F.col("area_code") == "20") & F.col("year").isin(y0, y1)) \
        .groupBy("livestock_class").pivot("year").agg(F.first("head"))
    w = pivoted.select(
        F.lit(y0).alias("start_year"),
        F.lit(y1).alias("end_year"),
        "livestock_class",
        (F.col(str(y1)) - F.col(str(y0))).alias("change_head"),
        F.round(100 * (F.col(str(y1)) - F.col(str(y0))) / F.col(str(y0)), 1).alias("change_pct"))
    frames.append(w)

from functools import reduce
dw = reduce(lambda a, b: a.unionByName(b), frames)
dw.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{FQ}.gold_dairy_windows")
display(dw.orderBy("livestock_class", "start_year"))