# %% [markdown]
# # 02 - Metadata Driven Data Quality Engine
#
# **Langkah 4 pada diagram:** *Read Metadata → Execute Rules → Generate Results*
#
# Ini adalah **SATU engine generik** yang dipakai untuk **SEMUA dataset**. Tidak ada aturan yang di-hard-code:
#
# | Tahap | Yang dilakukan | Output |
# |---|---|---|
# | 1. Read Metadata | Baca rule aktif dari `meta.dq_rule_catalog` | daftar rule |
# | 2. Execute Rules | Terjemahkan setiap `Rule_Type` → ekspresi Spark, jalankan ke tabel `bronze.*` | flag lolos/gagal per baris |
# | 3. Generate Results | Hitung skor & simpan hasil | `dq.dq_results`, `dq.dq_error_records` (quarantine), `dq.dq_score_per_dataset`, `dq.dq_run_history`, `silver.*` |
#
# **Mau tambah dataset / rule baru?** Cukup tambahkan baris di DQ Rule Catalog → jalankan ulang notebook ini. *Tanpa ubah kode.*

# %%
# PARAMETERS CELL (bisa dioverride dari Data Pipeline)
RUN_ID = ""                                   # kosong = dibuat otomatis, mis. RUN_20261008_053000
BLOCKING_SEVERITIES = ["High", "Medium"]      # baris yang gagal rule dengan severity ini -> dikarantina (tidak masuk Silver)
                                              # severity lain (mis. "Low") hanya dicatat sebagai warning

# %%
import json
from datetime import datetime
from functools import reduce
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

run_start = datetime.utcnow()
RUN_ID = RUN_ID or f"RUN_{run_start:%Y%m%d_%H%M%S}"
print(f"Run ID: {RUN_ID}")

# %% [markdown]
# ## Tahap 1 - Read Metadata
# Engine hanya membaca rule dengan `Is_Active = 'Y'`. Rule non-aktif (contoh: DQ012) otomatis dilewati.

# %%
rules = (spark.table("meta.dq_rule_catalog")
         .filter(F.col("Is_Active") == "Y")
         .orderBy("Dataset", "Rule_ID")
         .collect())

datasets = sorted({r.Dataset for r in rules})
print(f"{len(rules)} rule aktif untuk {len(datasets)} dataset: {datasets}")
display(spark.table("meta.dq_rule_catalog"))

# %% [markdown]
# ## Tahap 2 - Execute Rules (Rule Library)
# Setiap `Rule_Type` dipetakan ke **satu fungsi kecil** yang menambahkan kolom boolean `_pass_<Rule_ID>` ke DataFrame.
# Ini satu-satunya tempat "logika" berada - dan logika ini **reusable** untuk dataset apa pun.
# Menambah tipe rule baru (mis. `MAX_LENGTH`) = menambah satu fungsi di sini.

# %%
def rule_not_null(df, col, param):
    """NOT_NULL: nilai kolom tidak boleh kosong."""
    return df, F.col(col).isNotNull()

def rule_valid_format(df, col, param):
    """VALID_FORMAT: nilai harus cocok dengan regex di Rule_Parameter."""
    return df, F.col(col).cast("string").rlike(param)

def rule_unique(df, col, param):
    """UNIQUE: nilai tidak boleh muncul lebih dari sekali (NULL juga dianggap gagal)."""
    cnt = F.count(F.lit(1)).over(Window.partitionBy(col))
    return df, F.col(col).isNotNull() & (cnt == 1)

def rule_range(df, col, param):
    """RANGE: Rule_Parameter = 'min|max' (inklusif). Salah satu boleh kosong, mis. '0|' artinya >= 0."""
    lo, hi = (param.split("|") + [""])[:2]
    cond = F.lit(True)
    if lo.strip():
        cond = cond & (F.col(col) >= float(lo))
    if hi.strip():
        cond = cond & (F.col(col) <= float(hi))
    return df, F.col(col).isNotNull() & cond

def rule_valid_value(df, col, param):
    """VALID_VALUE: nilai harus salah satu dari daftar 'A,B,C'."""
    allowed = [v.strip() for v in param.split(",")]
    return df, F.col(col).isin(allowed)

def rule_referential(df, col, param):
    """REFERENTIAL: nilai harus ada di dataset lain. Rule_Parameter = 'Dataset.Kolom' (dibaca dari bronze)."""
    ref_ds, ref_col = param.split(".")
    ref = (spark.table(f"bronze.{ref_ds.lower()}")
           .select(F.col(ref_col).alias("_ref_key")).where("_ref_key IS NOT NULL").distinct()
           .withColumn("_ref_found", F.lit(True)))
    df = df.join(ref, df[col] == ref["_ref_key"], "left").drop("_ref_key")
    cond = F.col("_ref_found")
    return df, cond

def rule_custom_sql(df, col, param):
    """CUSTOM_SQL: ekspresi SQL bebas yang harus bernilai TRUE, mis. 'Transaction_Date <= current_date()'."""
    return df, F.expr(param)

# Rule Library: Rule_Type (dari metadata) -> fungsi
RULE_LIBRARY = {
    "NOT_NULL": rule_not_null,
    "VALID_FORMAT": rule_valid_format,
    "UNIQUE": rule_unique,
    "RANGE": rule_range,
    "VALID_VALUE": rule_valid_value,
    "REFERENTIAL": rule_referential,
    "CUSTOM_SQL": rule_custom_sql,
}

def apply_rule(df: DataFrame, rule) -> DataFrame:
    """Terapkan 1 rule dari metadata -> tambahkan kolom _pass_<Rule_ID> (True = lolos, False = gagal)."""
    handler = RULE_LIBRARY.get(rule.Rule_Type)
    if handler is None:
        raise ValueError(f"Rule_Type '{rule.Rule_Type}' ({rule.Rule_ID}) belum didukung engine")
    df, cond = handler(df, rule.Column, rule.Rule_Parameter)
    df = df.withColumn(f"_pass_{rule.Rule_ID}", F.coalesce(cond, F.lit(False)))  # NULL dianggap gagal
    return df.drop("_ref_found")

# %% [markdown]
# ## Tahap 2 & 3 - Jalankan rule untuk SEMUA dataset, lalu hasilkan output
# Loop di bawah ini **sama untuk semua dataset** - inilah inti dari *metadata driven*.

# %%
result_rows, error_dfs = [], []
run_time = F.lit(run_start).cast("timestamp")

for ds in datasets:
    ds_rules = [r for r in rules if r.Dataset == ds]
    bronze = spark.table(f"bronze.{ds.lower()}")
    data_cols = [c for c in bronze.columns if not c.startswith("_")]   # kolom bisnis (tanpa kolom audit)

    # --- Execute Rules: tambahkan 1 kolom flag per rule ---
    df = bronze
    for r in ds_rules:
        df = apply_rule(df, r)
    df = df.withColumn("_record", F.to_json(F.struct(*data_cols))).cache()

    # --- Generate Results (1): ringkasan per rule -> dq_results ---
    agg = df.agg(F.count(F.lit(1)).alias("total"),
                 *[F.sum(F.when(~F.col(f"_pass_{r.Rule_ID}"), 1).otherwise(0)).alias(r.Rule_ID) for r in ds_rules]
                ).collect()[0]
    total = agg["total"]
    for r in ds_rules:
        failed = agg[r.Rule_ID] or 0
        pass_pct = round((total - failed) / total * 100, 2) if total else 100.0
        result_rows.append((RUN_ID, run_start, r.Rule_ID, ds, r.Column, r.Rule_Type, r.Description,
                            r.Severity, r.Owner, float(r.Threshold), total, failed, total - failed, pass_pct,
                            "PASS" if pass_pct >= float(r.Threshold) else "FAIL"))

    # --- Generate Results (2): detail baris gagal -> dq_error_records (quarantine) ---
    for r in ds_rules:
        error_dfs.append(
            df.filter(~F.col(f"_pass_{r.Rule_ID}"))
              .select(F.lit(RUN_ID).alias("Run_ID"), F.lit(ds).alias("Dataset"),
                      F.lit(r.Column).alias("Column"), F.col(r.Column).cast("string").alias("Value"),
                      F.lit(r.Rule_ID).alias("Error_Code"), F.lit(r.Severity).alias("Severity"),
                      F.lit(r.Description).alias("Error_Message"), F.col("_record").alias("Record"),
                      run_time.alias("Run_Time")))

    # --- Generate Results (3): data bersih -> Silver ---
    # Baris yang gagal rule "blocking" (High/Medium) tidak masuk Silver; rule "Low" hanya warning.
    blocking = [f"_pass_{r.Rule_ID}" for r in ds_rules if r.Severity in BLOCKING_SEVERITIES]
    is_clean = reduce(lambda a, b: a & b, [F.col(c) for c in blocking], F.lit(True))
    silver = (df.filter(is_clean).select(*data_cols)
                .withColumn("_dq_run_id", F.lit(RUN_ID))
                .withColumn("_dq_validated_at", run_time))
    silver.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"silver.{ds.lower()}")
    print(f"{ds:<10} total={total:>5} | rules={len(ds_rules)} | silver={silver.count():>5}")
    df.unpersist()

# %%
# ===== Simpan hasil DQ (append = menyimpan history setiap eksekusi) =====
results_df = spark.createDataFrame(result_rows,
    "Run_ID string, Run_Time timestamp, Rule_ID string, Dataset string, Column string, Rule_Type string, "
    "Rule_Description string, Severity string, Owner string, Threshold double, Total_Records long, "
    "Failed_Records long, Passed_Records long, Pass_Pct double, Status string")
results_df.write.mode("append").option("mergeSchema", "true").saveAsTable("dq.dq_results")

errors_df = reduce(DataFrame.unionByName, error_dfs)
errors_df.write.mode("append").option("mergeSchema", "true").saveAsTable("dq.dq_error_records")

# DQ Score per dataset = rata-rata Pass % dari semua rule di dataset tsb
score_df = (results_df.groupBy("Run_ID", "Run_Time", "Dataset")
            .agg(F.round(F.avg("Pass_Pct"), 2).alias("DQ_Score"),
                 F.count("*").alias("Rules_Executed"),
                 F.sum(F.when(F.col("Status") == "FAIL", 1).otherwise(0)).alias("Rules_Failed")))
score_df.write.mode("append").option("mergeSchema", "true").saveAsTable("dq.dq_score_per_dataset")

# Metadata eksekusi (run history)
overall = results_df.agg(F.round(F.avg("Pass_Pct"), 2)).collect()[0][0]
n_fail = results_df.filter("Status = 'FAIL'").count()
run_end = datetime.utcnow()
spark.createDataFrame(
    [(RUN_ID, run_start, run_end, round((run_end - run_start).total_seconds(), 1), len(datasets), len(rules),
      n_fail, float(overall), "COMPLETED_WITH_FAILURES" if n_fail else "COMPLETED")],
    "Run_ID string, Start_Time timestamp, End_Time timestamp, Duration_Sec double, Datasets int, "
    "Rules_Executed int, Rules_Failed int, Overall_DQ_Score double, Run_Status string"
).write.mode("append").option("mergeSchema", "true").saveAsTable("dq.dq_run_history")

print(f"Overall DQ Score: {overall}% | Rule FAIL: {n_fail}/{len(rules)}")

# %% [markdown]
# ## Hasil eksekusi ini

# %%
display(results_df.orderBy("Dataset", "Rule_ID"))

# %%
display(spark.table("dq.dq_error_records").filter(F.col("Run_ID") == RUN_ID)
        .select("Dataset", "Column", "Value", "Error_Code", "Error_Message", "Run_Time").limit(50))

# %%
# Kirim ringkasan ke Data Pipeline (bisa dipakai untuk kondisi / alert di pipeline)
notebookutils.notebook.exit(json.dumps({"run_id": RUN_ID, "overall_dq_score": overall, "rules_failed": n_fail}))
