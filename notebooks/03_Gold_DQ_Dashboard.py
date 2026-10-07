# %% [markdown]
# # 03 - Gold Layer & DQ Dashboard
#
# **Langkah 3 (Gold), 5 (DQ Results & Monitoring) dan 6 (Consumption) pada diagram.**
#
# 1. Membangun tabel **Gold** (business ready) HANYA dari data **Silver** yang sudah lolos validasi.
# 2. Menampilkan **DQ Scorecard** dari tabel hasil DQ: Overall DQ Score, DQ Score per Dataset,
#    Rule Validation Detail, dan Error Record (Quarantine) - seperti panel A/B/C di diagram.
#
# > Tabel `dq.*` dan `gold.*` dapat langsung dipakai oleh **Power BI (Direct Lake)**, Semantic Model, Data Agent, dll.

# %%
from pyspark.sql import functions as F

# %% [markdown]
# ## 1. Gold layer - data siap analitik (hanya dari Silver yang sudah tervalidasi)

# %%
sales, product, customer = spark.table("silver.sales"), spark.table("silver.product"), spark.table("silver.customer")

# Penjualan per kategori & bulan
gold_sales = (sales.join(product.select("Product_ID", "Category"), "Product_ID", "left")
              .withColumn("Month", F.date_format("Transaction_Date", "yyyy-MM"))
              .groupBy("Month", "Category")
              .agg(F.countDistinct("Transaction_ID").alias("Transactions"),
                   F.sum("Quantity").alias("Total_Qty"),
                   F.sum("Amount").alias("Total_Amount")))
gold_sales.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("gold.sales_by_category_month")

# Ringkasan penjualan per customer
gold_cust = (sales.join(customer.select("Customer_ID", "Customer_Name", "City", "Segment"), "Customer_ID", "inner")
             .groupBy("Customer_ID", "Customer_Name", "City", "Segment")
             .agg(F.count("*").alias("Transactions"), F.sum("Amount").alias("Total_Amount")))
gold_cust.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("gold.customer_sales_summary")

display(spark.table("gold.sales_by_category_month").orderBy("Month", "Category"))

# %% [markdown]
# ## 2. DQ Scorecard (eksekusi terakhir)

# %%
last_run = spark.table("dq.dq_run_history").orderBy(F.desc("Start_Time")).first()
RUN_ID = last_run.Run_ID
print(f"Run terakhir: {RUN_ID} | Overall DQ Score: {last_run.Overall_DQ_Score}% | "
      f"Rule FAIL: {last_run.Rules_Failed}/{last_run.Rules_Executed} | Durasi: {last_run.Duration_Sec}s")

res = spark.table("dq.dq_results").filter(F.col("Run_ID") == RUN_ID).orderBy("Dataset", "Rule_ID").toPandas()
score = spark.table("dq.dq_score_per_dataset").filter(F.col("Run_ID") == RUN_ID).orderBy(F.desc("DQ_Score")).toPandas()
err = (spark.table("dq.dq_error_records").filter(F.col("Run_ID") == RUN_ID)
       .select("Dataset", "Column", "Value", "Error_Code", "Error_Message").limit(8).toPandas())

# %%
# Visualisasi sederhana dengan matplotlib (meniru panel B & C pada diagram)
import matplotlib.pyplot as plt
import numpy as np

fig = plt.figure(figsize=(16, 9))
gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.2])

# --- Gauge: Overall DQ Score ---
ax = fig.add_subplot(gs[0, 0], aspect="equal")
val = float(last_run.Overall_DQ_Score)
color = "#2e9e44" if val >= 95 else "#f2a900" if val >= 85 else "#d9342b"
ax.pie([val, 100 - val, 100], colors=[color, "#e6e6e6", "white"], startangle=180, counterclock=False,
       wedgeprops=dict(width=0.3))
ax.text(0, -0.15, f"{val:.1f}%", ha="center", fontsize=30, weight="bold")
ax.set_title("Overall DQ Score", fontsize=14, weight="bold")
ax.set_ylim(-0.5, 1.1)

# --- Bar: DQ Score per Dataset ---
ax = fig.add_subplot(gs[0, 1])
bars = ax.barh(score["Dataset"], score["DQ_Score"], color="#2e9e44")
ax.set_xlim(min(80, score["DQ_Score"].min() - 2), 100)
ax.invert_yaxis()
ax.bar_label(bars, labels=[f"{v:.1f}%" for v in score["DQ_Score"]], padding=3)
ax.set_title("DQ Score per Dataset", fontsize=14, weight="bold")

# --- Tabel: Rule Validation Detail ---
ax = fig.add_subplot(gs[1, 0]); ax.axis("off")
cols = ["Dataset", "Rule_ID", "Rule_Type", "Column", "Total_Records", "Failed_Records", "Pass_Pct", "Threshold", "Status"]
tbl = ax.table(cellText=res[cols].values, colLabels=cols, loc="upper center", cellLoc="center")
tbl.auto_set_font_size(False); tbl.set_fontsize(8); tbl.scale(1, 1.3)
for i, status in enumerate(res["Status"], start=1):
    tbl[i, len(cols) - 1].set_facecolor("#c8efd0" if status == "PASS" else "#f8c9c6")
ax.set_title("Rule Validation Detail", fontsize=14, weight="bold")

# --- Tabel: Error Record (Quarantine) ---
ax = fig.add_subplot(gs[1, 1]); ax.axis("off")
tbl = ax.table(cellText=err.values, colLabels=list(err.columns), loc="upper center", cellLoc="center")
tbl.auto_set_font_size(False); tbl.set_fontsize(8); tbl.scale(1, 1.3)
ax.set_title("Error Record (Quarantine) - sampel", fontsize=14, weight="bold")

fig.suptitle(f"Metadata Driven Data Quality - {RUN_ID}", fontsize=16, weight="bold")
plt.tight_layout()
plt.show()

# %% [markdown]
# ## 3. Query siap pakai untuk monitoring (bisa dipakai juga di SQL analytics endpoint / Power BI)

# %%
# Tren DQ score antar eksekusi (history) - berguna untuk melihat perbaikan kualitas data dari waktu ke waktu
display(spark.sql("""
    SELECT Run_ID, Start_Time, Rules_Executed, Rules_Failed, Overall_DQ_Score, Run_Status
    FROM dq.dq_run_history ORDER BY Start_Time DESC
"""))

# %%
# Jumlah record yang dikarantina per dataset & rule pada eksekusi terakhir
display(spark.sql(f"""
    SELECT Dataset, Error_Code, Error_Message, Severity, COUNT(*) AS Error_Count
    FROM dq.dq_error_records WHERE Run_ID = '{RUN_ID}'
    GROUP BY Dataset, Error_Code, Error_Message, Severity ORDER BY Error_Count DESC
"""))
