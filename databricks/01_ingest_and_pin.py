# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,01 - Ingest and pin
# MAGIC %md
# MAGIC # 01 - Ingest and pin
# MAGIC
# MAGIC Reads the pinned Stats NZ extract of AGR_AGR_003 (Livestock Numbers by Regional
# MAGIC Council), verifies it byte-for-byte against a recorded hash, and writes bronze
# MAGIC unchanged.
# MAGIC
# MAGIC Source data: Stats NZ, Agricultural production statistics, licensed by Stats NZ
# MAGIC for re-use under the Creative Commons Attribution 4.0 International licence.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS workspace.nz_livestock;
# MAGIC CREATE VOLUME IF NOT EXISTS workspace.nz_livestock.raw;

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.removeAll()  # widget values persist across runs; start clean

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nz_livestock")
dbutils.widgets.text("source_file", "agr_agr_003_2026-09-04.csv")
dbutils.widgets.text("expected_sha256",
    "e9d82621c2db8517dbf906a8b952d462a360cd2adcc351eb107e187afbe03a4c")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
SRC = dbutils.widgets.get("source_file")
EXPECT = dbutils.widgets.get("expected_sha256")

FQ = f"{CATALOG}.{SCHEMA}"
SRC_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/raw/{SRC}"
print(SRC_PATH)

# COMMAND ----------

# DBTITLE 1,Hash gate
import hashlib

def sha256_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()

got = sha256_of(SRC_PATH)
if got != EXPECT:
    raise ValueError(
        "Pinned extract does not match the recorded hash.\n"
        f"  expected: {EXPECT}\n"
        f"  found:   {got}\n"
        "Refusing to proceed: the analysis below is only valid for the pinned bytes."
    )
print("hash gate: PASS")
print("sha256:", got)

# COMMAND ----------

# DBTITLE 1,Read bronze
from pyspark.sql import functions as F

bronze = (spark.read
    .option("header", True)
    .option("inferSchema", False)  # everything as string; cast deliberately in 02
    .option("mode", "PERMISSIVE")
    .csv(SRC_PATH))

print("rows:", bronze.count())  # expect 19626
display(bronze.limit(10))

# COMMAND ----------

# DBTITLE 1,Shape assertions
REQUIRED = ["LIVESTOCK_AGR_AGR_003", "AREA_AGR_AGR_003",
           "YEAR_AGR_AGR_003", "OBS_VALUE", "OBS_STATUS"]
missing = [c for c in REQUIRED if c not in bronze.columns]
if missing:
    raise ValueError(f"Pinned extract is missing required column(s): {missing}")

statuses = {r[0] for r in bronze.select("OBS_STATUS").distinct().collect()
            if r[0] not in (None, "")}
unexpected = statuses - {"s", "c"}
if unexpected:
    raise ValueError(f"Unknown OBS_STATUS value(s): {sorted(unexpected)}")

display(bronze.groupBy("OBS_STATUS").count().orderBy("OBS_STATUS"))
# expect: null/empty 17759, c 235, s 1632

# COMMAND ----------

# DBTITLE 1,Write bronze and manifest
# The schema already exists (section 3.2). Idempotent belt-and-braces so this
# notebook also works against a fresh workspace.
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {FQ}")

(bronze
    .withColumn("_source_file", F.lit(SRC))
    .withColumn("_source_sha256", F.lit(got))
    .withColumn("_ingested_at", F.current_timestamp())
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(f"{FQ}.bronze_agr_agr_003"))

(spark.createDataFrame([(SRC, got, bronze.count())],
    "source_file string, sha256 string, row_count long")
    .withColumn("ingested_at", F.current_timestamp())
    .write.mode("append").saveAsTable(f"{FQ}.ingest_manifest"))

display(spark.table(f"{FQ}.ingest_manifest"))

# COMMAND ----------

# DBTITLE 1,dim_livestock
# --- cell 7: livestock dimension
livestock_rows = [("6731", "Sheep", 23583001),
    ("7193", "Dairy cattle", 5836845),
    ("7077", "Beef cattle", 3679443)]
(spark.createDataFrame(
    livestock_rows,
    "livestock_code string, livestock_class string, verified_2024_head long")
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(f"{FQ}.dim_livestock"))

# COMMAND ----------

# DBTITLE 1,dim_area
# --- cell 8: area dimension
# Names follow SSGA23. Aotearoa Data Explorer still shows the older spellings
# "Hawkes Bay" and "Manawatu-Wanganui" for this dataflow; SSGA23 is used here.
# Chatham Islands (18) sits under the South Island because codes 11-18 sum
# exactly to code 19. That follows the table's aggregation structure, not
# geography - the Chatham Islands are not part of the South Island.
area_rows = [
    ("1","Northland","North Island",False), ("2","Auckland","North Island",False),
    ("3","Waikato","North Island",False), ("4","Bay of Plenty","North Island",False),
    ("5","Gisborne","North Island",False), ("6","Hawke's Bay","North Island",False),
    ("7","Taranaki","North Island",False), ("8","Manawat\u016b-Whanganui","North Island",False),
    ("9","Wellington","North Island",False), ("10","Total North Island",None,True),
    ("11","Tasman","South Island",False), ("12","Nelson","South Island",False),
    ("13","Marlborough","South Island",False),("14","West Coast","South Island",False),
    ("15","Canterbury","South Island",False), ("16","Otago","South Island",False),
    ("17","Southland","South Island",False), ("18","Chatham Islands","South Island",False),
    ("19","Total South Island",None,True), ("20","Total New Zealand",None,True),
]
(spark.createDataFrame(
    area_rows, "area_code string, region string, island string, is_aggregate boolean")
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(f"{FQ}.dim_area"))

display(spark.table(f"{FQ}.dim_area").orderBy("area_code"))

# COMMAND ----------

# DBTITLE 1,Exit
dbutils.notebook.exit(f"ingested {SRC} sha256={got[:12]}...")