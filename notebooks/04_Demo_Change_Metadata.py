# %% [markdown]
# # 04 - DEMO: Ubah Metadata, BUKAN Kode
#
# Notebook ini untuk sesi demo ke tim. Tujuannya membuktikan bahwa:
# - **Menambah rule baru**, **mengaktifkan / menonaktifkan rule**, dan **mengubah threshold**
#   cukup dilakukan dengan mengubah **tabel metadata** `meta.dq_rule_catalog`.
# - Engine (`02_DQ_Engine`) **tidak diubah sama sekali**, tapi hasilnya langsung berubah.
#
# > Alternatif lain: ubah file Excel `dq_rule_catalog.xlsx` di `Files/landing/`, lalu jalankan ulang pipeline.

# %%
# Kondisi metadata SEBELUM diubah
display(spark.sql("SELECT Rule_ID, Dataset, Column, Rule_Type, Rule_Parameter, Threshold, Severity, Is_Active "
                  "FROM meta.dq_rule_catalog ORDER BY Rule_ID"))

# %%
# 1) AKTIFKAN rule yang tadinya non-aktif (DQ012: harga produk harus > 0)
spark.sql("UPDATE meta.dq_rule_catalog SET Is_Active = 'Y', Updated_At = current_timestamp() WHERE Rule_ID = 'DQ012'")

# 2) TAMBAH rule baru tanpa coding: nama customer wajib diisi & City harus dari daftar kota yang dilayani
spark.sql("DELETE FROM meta.dq_rule_catalog WHERE Rule_ID IN ('DQ013', 'DQ014')")   # agar demo bisa diulang
spark.sql("""
    INSERT INTO meta.dq_rule_catalog
    (Rule_ID, Dataset, Column, Rule_Type, Rule_Parameter, Threshold, Severity, Owner, Description, Is_Active, Updated_At)
    VALUES
    ('DQ013', 'Customer', 'Customer_Name', 'NOT_NULL', '', 100, 'High', 'Data Team', 'Nama customer wajib ada', 'Y', current_timestamp()),
    ('DQ014', 'Customer', 'City', 'VALID_VALUE', 'Jakarta,Bandung,Surabaya,Medan', 90, 'Low', 'CRM Team', 'Kota di luar area layanan', 'Y', current_timestamp())
""")

# 3) UBAH threshold: Sales Amount dilonggarkan dari 99% menjadi 97%
spark.sql("UPDATE meta.dq_rule_catalog SET Threshold = 97, Updated_At = current_timestamp() WHERE Rule_ID = 'DQ004'")

display(spark.sql("SELECT Rule_ID, Dataset, Column, Rule_Type, Rule_Parameter, Threshold, Severity, Is_Active "
                  "FROM meta.dq_rule_catalog ORDER BY Rule_ID"))

# %%
# Jalankan ulang engine yang SAMA (tanpa perubahan kode) + refresh dashboard
print(notebookutils.notebook.run("02_DQ_Engine", 1800))
notebookutils.notebook.run("03_Gold_DQ_Dashboard", 1800)

# %%
# Bandingkan 2 eksekusi terakhir: jumlah rule & skor berubah hanya karena metadata berubah
display(spark.sql("""
    SELECT Run_ID, Start_Time, Rules_Executed, Rules_Failed, Overall_DQ_Score, Run_Status
    FROM dq.dq_run_history ORDER BY Start_Time DESC LIMIT 2
"""))
