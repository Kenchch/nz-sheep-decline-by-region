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
# MAGIC This work is based on Stats NZ's data (Agricultural production statistics,
# MAGIC AGR_AGR_003), licensed by Stats NZ for re-use under the Creative Commons
# MAGIC Attribution 4.0 International licence (https://creativecommons.org/licenses/by/4.0/).

# COMMAND ----------

# DBTITLE 1,Parameters
import re

# The hash recorded in data-raw/SOURCE.md. CI checks that this copy matches it.
PINNED_SHA256 = "e9d82621c2db8517dbf906a8b952d462a360cd2adcc351eb107e187afbe03a4c"

# Keep existing values: Lakeflow task parameters override these defaults.
dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nz_livestock")
dbutils.widgets.text("source_file", "agr_agr_003_2026-09-04.csv")
dbutils.widgets.text("expected_sha256", PINNED_SHA256)

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
SRC = dbutils.widgets.get("source_file")
EXPECT = dbutils.widgets.get("expected_sha256")

# Parameters become SQL identifiers and a file path, so they are validated
# rather than interpolated as given: a name with a hyphen would be a syntax
# error, and a source_file of "../x" would read outside the volume.
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
for key, value in {"catalog": CATALOG, "schema": SCHEMA}.items():
    if not IDENT.fullmatch(value):
        raise ValueError(f"invalid {key}: {value!r}")
if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", SRC):
    raise ValueError(f"source_file must be a bare file name: {SRC!r}")
if not re.fullmatch(r"[0-9a-f]{64}", EXPECT):
    raise ValueError(f"expected_sha256 is not a SHA-256 hex digest: {EXPECT!r}")

FQ = f"`{CATALOG}`.`{SCHEMA}`"
SRC_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/raw/{SRC}"
print(SRC_PATH)

# A task parameter can replace the pinned hash without a commit. That is
# allowed, for a deliberate new vintage, but it is never silent: it is printed
# here and recorded in the manifest below.
HASH_OVERRIDDEN = EXPECT != PINNED_SHA256
if HASH_OVERRIDDEN:
    print(f"WARNING: expected_sha256 overrides the pinned hash {PINNED_SHA256[:12]}...")

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
    .option("mode", "FAILFAST")
    .csv(SRC_PATH))

n_bronze = bronze.count()
print("rows:", n_bronze)  # expect 19626; reuse the same count in the manifest

# Spark reads the file separately from the hash above. Hashing again after
# the read closes the window in which the file could have been replaced
# between the check and the use.
if sha256_of(SRC_PATH) != got:
    raise ValueError("The extract changed while it was being read. Refusing to proceed.")
display(bronze.limit(10))

# COMMAND ----------

# DBTITLE 1,Shape assertions
REQUIRED = ["LIVESTOCK_AGR_AGR_003", "AREA_AGR_AGR_003",
            "YEAR_AGR_AGR_003", "OBS_VALUE", "OBS_STATUS"]
missing = [c for c in REQUIRED if c not in bronze.columns]
if missing:
    raise ValueError(f"Pinned extract is missing required column(s): {missing}")
extra = [c for c in bronze.columns if c not in REQUIRED + ["DATAFLOW"]]
if extra:
    raise ValueError(f"Pinned extract has unexpected column(s): {extra}")

statuses = {r[0] for r in bronze.select("OBS_STATUS").distinct().collect()
            if r[0] not in (None, "")}
unexpected = statuses - {"s", "c"}
if unexpected:
    raise ValueError(f"Unknown OBS_STATUS value(s): {sorted(unexpected)}")

display(bronze.groupBy("OBS_STATUS").count().orderBy("OBS_STATUS"))
# expect: null/empty 17759, c 235, s 1632

# COMMAND ----------

# DBTITLE 1,Write bronze and manifest
# The source volume must already exist and contain the pinned CSV (see README).
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {FQ}")

(bronze
    .withColumn("_source_file", F.lit(SRC))
    .withColumn("_source_sha256", F.lit(got))
    .withColumn("_ingested_at", F.current_timestamp())
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(f"{FQ}.bronze_agr_agr_003"))

(spark.createDataFrame([(SRC, got, n_bronze, HASH_OVERRIDDEN)],
    "source_file string, sha256 string, row_count long, hash_overridden boolean")
    .withColumn("ingested_at", F.current_timestamp())
    .write.mode("append").option("mergeSchema", "true")
    .saveAsTable(f"{FQ}.ingest_manifest"))

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
# The codes are this table's own (10, 19 and 20 are aggregates), not SSGA23
# codes; the names follow SSGA23. Aotearoa Data Explorer still shows the older
# spellings "Hawkes Bay" and "Manawatu-Wanganui" for this dataflow.
# Chatham Islands (18) sits under the South Island because codes 11-18 sum to
# code 19, to within the source table's own rounding of a head or two in
# complete years. That follows the table's aggregation structure, not
# geography - the Chatham Islands are not part of the South Island.
area_rows = [
    ("1","Northland","North Island",False), ("2","Auckland","North Island",False),
    ("3","Waikato","North Island",False), ("4","Bay of Plenty","North Island",False),
    ("5","Gisborne","North Island",False), ("6","Hawke's Bay","North Island",False),
    ("7","Taranaki","North Island",False), ("8","Manawatū-Whanganui","North Island",False),
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
