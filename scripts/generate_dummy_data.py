"""
Generate data dummy (Excel) untuk demo Metadata Driven Data Quality di Microsoft Fabric.

Output:
  data/source_data_dummy.xlsx  -> 4 sheet (Customer, Sales, Product, Inventory) = "Source Systems"
  data/dq_rule_catalog.xlsx    -> 1 sheet (DQ_Rule_Catalog)                   = "Tabel Metadata"

Catatan: data SENGAJA disisipi error (null, email salah, duplikat, nilai negatif,
kategori tidak valid, dll.) supaya hasil Data Quality terlihat menarik saat demo.
"""
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

random.seed(42)  # agar data selalu sama setiap kali di-generate (reproducible)
OUT = Path(__file__).resolve().parent.parent / "data"
OUT.mkdir(exist_ok=True)

CITIES = ["Jakarta", "Bandung", "Surabaya", "Medan", "Makassar", "Yogyakarta", "Semarang", "Denpasar"]
SEGMENTS = ["Retail", "Corporate", "SME"]
FIRST = ["Andi", "Budi", "Citra", "Dewi", "Eka", "Fajar", "Gita", "Hadi", "Indah", "Joko", "Kartika", "Lina"]
LAST = ["Saputra", "Wijaya", "Santoso", "Pratama", "Lestari", "Hidayat", "Nugroho", "Siregar"]
CATEGORIES = ["Electronics", "Fashion", "Grocery", "Home"]
WAREHOUSES = ["WH-JKT", "WH-SBY", "WH-MDN"]


def customers(n=1000):
    rows = []
    for i in range(1, n + 1):
        fn, ln = random.choice(FIRST), random.choice(LAST)
        rows.append({
            "Customer_ID": f"C{i:05d}",
            "Customer_Name": f"{fn} {ln}",
            "Email": f"{fn.lower()}.{ln.lower()}{i}@contoso.co.id",
            # format pakai "-" agar tetap dibaca sebagai teks (angka 0 di depan tidak hilang)
            "Phone": f"08{random.randint(11, 99)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
            "City": random.choice(CITIES),
            "Segment": random.choice(SEGMENTS),
            "Created_Date": date(2024, 1, 1) + timedelta(days=random.randint(0, 600)),
        })
    df = pd.DataFrame(rows)
    # --- Sisipkan error ---
    df.loc[random.sample(range(n), 4), "Customer_ID"] = None                 # DQ001 NOT NULL
    for idx in random.sample(range(n), 12):                                  # DQ002 VALID FORMAT
        df.loc[idx, "Email"] = random.choice(["abc@", "user.contoso.co.id", "test@@mail", "-"])
    for idx in random.sample(range(n), 60):                                  # DQ006 (Low severity -> warning)
        df.loc[idx, "Phone"] = random.choice(["unknown", "+1-555-0100", "0812-34"])
    return df


def products(n=200):
    rows = [{
        "Product_ID": f"P{i:04d}",
        "Product_Name": f"Product {i}",
        "Category": random.choice(CATEGORIES),
        "Unit_Price": round(random.uniform(10_000, 5_000_000), 0),
    } for i in range(1, n + 1)]
    df = pd.DataFrame(rows)
    df.loc[random.sample(range(n), 1), "Category"] = "X"                     # DQ005 VALID VALUE
    df.loc[random.sample(range(n), 2), "Unit_Price"] = 0                     # DQ012 (rule non-aktif)
    return df


def sales(cust_ids, prod_ids, n=5000):
    rows = [{
        "Transaction_ID": f"T{i:06d}",
        "Customer_ID": random.choice(cust_ids),
        "Product_ID": random.choice(prod_ids),
        "Quantity": random.randint(1, 20),
        "Amount": round(random.uniform(50_000, 10_000_000), 0),
        "Transaction_Date": date(2026, 1, 1) + timedelta(days=random.randint(0, 270)),
    } for i in range(1, n + 1)]
    df = pd.DataFrame(rows)
    for idx in random.sample(range(n), 3):                                   # DQ003 UNIQUE (duplikat)
        df.loc[(idx + 7) % n, "Transaction_ID"] = df.loc[idx, "Transaction_ID"]
    df.loc[random.sample(range(n), 125), "Amount"] = -100                    # DQ004 RANGE -> FAIL (2.5%)
    df.loc[random.sample(range(n), 5), "Quantity"] = 0                       # DQ008 RANGE
    df.loc[random.sample(range(n), 8), "Customer_ID"] = "C99999"             # DQ007 REFERENTIAL (orphan)
    df.loc[random.sample(range(n), 2), "Transaction_Date"] = date(2027, 12, 31)  # DQ011 CUSTOM SQL
    return df


def inventory(prod_ids):
    rows = [{
        "Product_ID": pid,
        "Warehouse": wh,
        "Stock_Qty": random.randint(0, 500),
        "Last_Update": date(2026, 10, 1),
    } for pid in prod_ids for wh in WAREHOUSES]
    df = pd.DataFrame(rows)
    df.loc[random.sample(range(len(df)), 5), "Stock_Qty"] = -10              # DQ009 RANGE
    df.loc[random.sample(range(len(df)), 2), "Product_ID"] = None            # DQ010 NOT NULL
    return df


# =====================================================================================
# METADATA / DQ RULE CATALOG
#   Rule_Type yang didukung engine:
#     NOT_NULL     -> kolom tidak boleh kosong                     (Rule_Parameter kosong)
#     VALID_FORMAT -> nilai harus cocok dengan regex               (Rule_Parameter = regex)
#     UNIQUE       -> nilai tidak boleh duplikat                   (Rule_Parameter kosong)
#     RANGE        -> nilai harus di antara min|max (inklusif)     (Rule_Parameter = "min|max", boleh kosong salah satu)
#     VALID_VALUE  -> nilai harus salah satu dari daftar           (Rule_Parameter = "A,B,C")
#     REFERENTIAL  -> nilai harus ada di dataset lain              (Rule_Parameter = "Dataset.Kolom")
#     CUSTOM_SQL   -> ekspresi SQL bebas yang harus bernilai TRUE  (Rule_Parameter = ekspresi SQL)
#   Threshold   = minimal % baris yang lolos agar rule berstatus PASS
#   Is_Active   = Y/N -> rule bisa dinonaktifkan TANPA mengubah kode
# =====================================================================================
RULES = [
    # Rule_ID, Dataset, Column, Rule_Type, Rule_Parameter, Threshold, Severity, Owner, Description, Is_Active
    ("DQ001", "Customer", "Customer_ID", "NOT_NULL", "", 100, "High", "Data Team", "Customer ID wajib ada", "Y"),
    ("DQ002", "Customer", "Email", "VALID_FORMAT", r"^[A-Za-z0-9._+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.]+$", 98, "Medium", "Data Team", "Format email valid", "Y"),
    ("DQ003", "Sales", "Transaction_ID", "UNIQUE", "", 100, "High", "Finance", "Transaction ID tidak boleh duplikat", "Y"),
    ("DQ004", "Sales", "Amount", "RANGE", "0|", 99, "High", "Finance", "Nilai Amount tidak boleh negatif", "Y"),
    ("DQ005", "Product", "Category", "VALID_VALUE", "Electronics,Fashion,Grocery,Home", 99, "Medium", "Product", "Kategori harus valid", "Y"),
    ("DQ006", "Customer", "Phone", "VALID_FORMAT", r"^08[0-9]{2}-[0-9]{4}-[0-9]{3,5}$", 95, "Low", "CRM Team", "Nomor HP format Indonesia (08xx-xxxx-xxxx)", "Y"),
    ("DQ007", "Sales", "Customer_ID", "REFERENTIAL", "Customer.Customer_ID", 99, "High", "Finance", "Customer di transaksi harus terdaftar", "Y"),
    ("DQ008", "Sales", "Quantity", "RANGE", "1|100", 99, "Medium", "Finance", "Quantity antara 1 - 100", "Y"),
    ("DQ009", "Inventory", "Stock_Qty", "RANGE", "0|", 99, "High", "Supply Chain", "Stok tidak boleh negatif", "Y"),
    ("DQ010", "Inventory", "Product_ID", "NOT_NULL", "", 100, "High", "Supply Chain", "Product ID wajib ada", "Y"),
    ("DQ011", "Sales", "Transaction_Date", "CUSTOM_SQL", "Transaction_Date <= current_date()", 99, "Medium", "Finance", "Tanggal transaksi tidak boleh di masa depan", "Y"),
    ("DQ012", "Product", "Unit_Price", "RANGE", "1|", 100, "Medium", "Product", "Harga harus > 0 (contoh rule NON-AKTIF)", "N"),
]
RULE_COLS = ["Rule_ID", "Dataset", "Column", "Rule_Type", "Rule_Parameter", "Threshold",
             "Severity", "Owner", "Description", "Is_Active"]

if __name__ == "__main__":
    cust = customers()
    prod = products()
    sal = sales(cust["Customer_ID"].dropna().tolist(), prod["Product_ID"].tolist())
    inv = inventory(prod["Product_ID"].tolist())

    with pd.ExcelWriter(OUT / "source_data_dummy.xlsx", engine="openpyxl") as xw:
        cust.to_excel(xw, sheet_name="Customer", index=False)
        sal.to_excel(xw, sheet_name="Sales", index=False)
        prod.to_excel(xw, sheet_name="Product", index=False)
        inv.to_excel(xw, sheet_name="Inventory", index=False)

    with pd.ExcelWriter(OUT / "dq_rule_catalog.xlsx", engine="openpyxl") as xw:
        pd.DataFrame(RULES, columns=RULE_COLS).to_excel(xw, sheet_name="DQ_Rule_Catalog", index=False)

    print(f"Customer={len(cust)} Sales={len(sal)} Product={len(prod)} Inventory={len(inv)} Rules={len(RULES)}")
    print(f"Saved to {OUT}")
