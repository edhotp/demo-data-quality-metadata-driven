# %% [markdown]
# # 01 - Ingest Source Data ke Bronze (Raw Data)
#
# **Langkah 1-3 pada diagram:** *Source Systems → Ingest → Data Storage (Bronze)*
#
# Notebook ini:
# 1. Membuat schema medallion di Lakehouse: `bronze`, `silver`, `gold`, plus `meta` (metadata) & `dq` (hasil DQ).
# 2. Membaca file **Excel dummy** (mensimulasikan source system ERP/CRM) dari `Files/landing/`.
# 3. Menyimpan setiap sheet **apa adanya** (raw) ke tabel Delta `bronze.<dataset>`.
# 4. Memuat **DQ Rule Catalog** (metadata aturan data quality) dari Excel ke tabel `meta.dq_rule_catalog`.
#
# > Di produksi, langkah ingest biasanya dilakukan oleh **Fabric Data Factory** (Copy activity / Copy job / Dataflow Gen2).
# > Untuk demo, kita pakai notebook agar mudah dipahami.

# %%
# PARAMETERS CELL (bisa dioverride dari Data Pipeline)
SOURCE_FILE = "/lakehouse/default/Files/landing/source_data_dummy.xlsx"   # file Excel sumber data
RULE_FILE   = "/lakehouse/default/Files/landing/dq_rule_catalog.xlsx"     # file Excel metadata rule DQ
DATASETS    = ["Customer", "Sales", "Product", "Inventory"]               # sheet yang akan di-ingest

# %%
import pandas as pd
from pyspark.sql import functions as F

# Buat schema medallion + schema untuk metadata & hasil DQ.
# (Lakehouse dibuat dengan "Lakehouse schemas" aktif, sehingga CREATE SCHEMA didukung)
for schema in ["bronze", "silver", "gold", "meta", "dq"]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
print("Schema siap: bronze, silver, gold, meta, dq")

# %%
def pandas_to_spark(pdf: pd.DataFrame):
    """Konversi pandas -> Spark DataFrame dengan aman.
    - Nilai kosong (NaN) di kolom teks diubah menjadi None (NULL di Spark).
    - Kolom tanggal (datetime) diubah menjadi tipe DATE.
    """
    for c in pdf.columns:
        if pdf[c].dtype == "object":
            pdf[c] = pdf[c].astype(object).where(pdf[c].notna(), None)
    sdf = spark.createDataFrame(pdf)
    for c, t in sdf.dtypes:
        if t.startswith("timestamp"):
            sdf = sdf.withColumn(c, F.to_date(c))
    return sdf

# %%
# ===== INGEST: Excel (Source System) -> Bronze =====
# Bronze = data mentah apa adanya. TIDAK ada validasi di sini (itu tugas DQ Engine).
for ds in DATASETS:
    pdf = pd.read_excel(SOURCE_FILE, sheet_name=ds)
    sdf = (pandas_to_spark(pdf)
           .withColumn("_ingest_time", F.current_timestamp())     # kolom audit: kapan data masuk
           .withColumn("_source_file", F.lit(SOURCE_FILE.split("/")[-1])))
    target = f"bronze.{ds.lower()}"
    sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(target)
    print(f"{target:<20} {sdf.count():>6} rows")

# %%
# ===== METADATA: DQ Rule Catalog (Excel) -> meta.dq_rule_catalog =====
# Inilah "otak" dari framework: semua aturan DQ disimpan sebagai DATA, bukan sebagai KODE.
# Menambah / mengubah / menonaktifkan rule cukup dengan mengubah tabel ini.
rules_pdf = pd.read_excel(RULE_FILE, sheet_name="DQ_Rule_Catalog", dtype=str).fillna("")
rules_pdf["Threshold"] = rules_pdf["Threshold"].astype(float)
rules_sdf = (spark.createDataFrame(rules_pdf)
             .withColumn("Updated_At", F.current_timestamp()))
rules_sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("meta.dq_rule_catalog")
display(spark.table("meta.dq_rule_catalog"))
