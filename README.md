# Demo: Metadata Driven Framework untuk Data Quality di Microsoft Fabric

> Satu framework untuk banyak dataset, dikendalikan oleh **metadata (konfigurasi)**, tanpa hard-code.

📘 **Ingin mencoba sendiri dari nol?** Ikuti tutorial langkah demi langkah di [tutorial/README.md](tutorial/README.md).

| Item | Nilai |
|---|---|
| Workspace | `ws_fabric_metadata_driven_dq` |
| Lakehouse | `lh_metadata_dq` (Lakehouse schemas: `bronze`, `silver`, `gold`, `meta`, `dq`) |
| Pipeline | `pl_metadata_driven_dq` (01 → 02 → 03) |
| Notebook | `01_Ingest_Bronze`, `02_DQ_Engine`, `03_Gold_DQ_Dashboard`, `04_Demo_Change_Metadata` |
| Power BI | Semantic model + report `Data Quality Monitoring` (Direct Lake) |

## Arsitektur (mengikuti diagram)

```mermaid
flowchart LR
    subgraph S1["1. Source Systems"]
        XL1["source_data_dummy.xlsx<br/>Customer, Sales, Product, Inventory"]
        XL2["dq_rule_catalog.xlsx<br/>DQ Rule Catalog"]
    end

    subgraph S2["2. Ingest & Orchestration"]
        PL["Data Pipeline<br/>pl_metadata_driven_dq<br/>notebook 01 → 02 → 03"]
    end

    subgraph S3["3. Lakehouse lh_metadata_dq"]
        BR[("bronze.*<br/>Raw Data")]
        META[("meta.dq_rule_catalog<br/>Metadata")]
        SV[("silver.*<br/>Cleansed & Validated")]
        GD[("gold.*<br/>Business Ready")]
    end

    subgraph S4["4. DQ Engine - 02_DQ_Engine"]
        direction TB
        E1["1. Read Metadata"] --> E2["2. Execute Rules"] --> E3["3. Generate Results"]
    end

    subgraph S5["5. DQ Results & Monitoring"]
        R1[("dq.dq_results")]
        R2[("dq.dq_error_records<br/>Quarantine")]
        R3[("dq.dq_score_per_dataset")]
        R4[("dq.dq_run_history")]
    end

    subgraph S6["6. Consumption"]
        C1["Power BI / Semantic Model<br/>Direct Lake"]
        C2["Data Agent / Copilot"]
        C3["Excel"]
    end

    XL1 --> PL
    XL2 --> PL
    PL -- "01_Ingest_Bronze" --> BR
    PL -- "01_Ingest_Bronze" --> META
    META --> E1
    BR --> E2
    E3 -- "lolos rule blocking" --> SV
    E3 --> R1 & R2 & R3 & R4
    SV -- "03_Gold_DQ_Dashboard" --> GD
    GD --> S6
    S5 --> S6
```

### Alur kerja DQ Engine

```mermaid
sequenceDiagram
    autonumber
    participant P as Pipeline / Notebook 04
    participant E as 02_DQ_Engine
    participant M as meta.dq_rule_catalog
    participant B as bronze.*
    participant D as dq.*
    participant S as silver.*

    P->>E: Jalankan (parameter RUN_ID, BLOCKING_SEVERITIES)
    E->>M: Baca rule dengan Is_Active = 'Y'
    loop Setiap dataset di metadata
        E->>B: Baca tabel bronze.{dataset}
        E->>E: Terapkan rule via Rule Library (1 kolom flag _pass_{Rule_ID} per rule)
        E->>D: Simpan hasil per rule (dq_results) dan record gagal (dq_error_records)
        E->>S: Simpan record yang lolos rule High/Medium
    end
    E->>D: Simpan DQ score per dataset dan run history
    E-->>P: notebook.exit(run_id, overall_dq_score, rules_failed)
```

### Konsep: ubah metadata, bukan kode

```mermaid
flowchart LR
    U["Data Steward<br/>ubah / tambah rule"] --> M[("DQ Rule Catalog<br/>Excel atau meta.dq_rule_catalog")]
    M --> E["DQ Engine<br/>kode TIDAK berubah"]
    E --> R["Hasil DQ baru<br/>skor dan status ikut berubah"]
```

## Isi folder

| Path | Keterangan |
|---|---|
| [data/source_data_dummy.xlsx](data/source_data_dummy.xlsx) | Data dummy 4 dataset: Customer (1.000), Sales (5.000), Product (200), Inventory (600) - sengaja berisi error |
| [data/dq_rule_catalog.xlsx](data/dq_rule_catalog.xlsx) | **Tabel Metadata (DQ Rule Catalog)** - 12 rule (11 aktif, 1 non-aktif) |
| [scripts/generate_dummy_data.py](scripts/generate_dummy_data.py) | Generator data dummy & rule catalog |
| [scripts/setup_fabric.py](scripts/setup_fabric.py) | Membuat workspace (di capacity pilihan) + lakehouse dengan schemas aktif |
| [scripts/deploy_to_fabric.py](scripts/deploy_to_fabric.py) | Deploy otomatis (upload Excel, notebook, pipeline) via Fabric REST API |
| [scripts/build_report.py](scripts/build_report.py) | Generator report Power BI (PBIR) "Data Quality Monitoring" |
| [scripts/deploy_powerbi.py](scripts/deploy_powerbi.py) | Deploy semantic model (TMDL, Direct Lake) + report ke workspace |
| [powerbi/](powerbi/) | Project PBIP: `DataQualityMonitoring.SemanticModel` (TMDL) + `DataQualityMonitoring.Report` (PBIR) |
| [notebooks/](notebooks/) | Source notebook (`.py` percent-format, mudah dibaca/di-review) + `.ipynb` yang di-deploy |
| [tutorial/](tutorial/) | Tutorial langkah demi langkah (jalur otomatis & manual via portal) |
| [requirements.txt](requirements.txt) | Dependensi Python untuk script |

## Tabel Metadata (DQ Rule Catalog)

| Kolom | Arti |
|---|---|
| `Rule_ID` | ID unik rule, juga dipakai sebagai `Error_Code` |
| `Dataset` / `Column` | Target validasi (tabel `bronze.<dataset>`) |
| `Rule_Type` | `NOT_NULL`, `VALID_FORMAT` (regex), `UNIQUE`, `RANGE` (`min\|max`), `VALID_VALUE` (`A,B,C`), `REFERENTIAL` (`Dataset.Kolom`), `CUSTOM_SQL` (ekspresi SQL) |
| `Rule_Parameter` | Parameter rule sesuai tipe |
| `Threshold` | Minimal % record lolos agar status rule = **PASS** |
| `Severity` | `High`/`Medium` = **blocking** (record dikarantina, tidak masuk Silver); `Low` = warning saja |
| `Owner`, `Description` | Pemilik rule & pesan error |
| `Is_Active` | `Y`/`N` - nonaktifkan rule tanpa ubah kode |

## Output tabel

| Tabel | Isi |
|---|---|
| `dq.dq_results` | Hasil per rule per eksekusi: Total, Failed, Pass %, Threshold, Status (PASS/FAIL) |
| `dq.dq_error_records` | **Quarantine** - detail record gagal: Dataset, Column, Value, Error_Code, Error_Message, Record (JSON) |
| `dq.dq_score_per_dataset` | DQ Score per dataset (rata-rata Pass %) |
| `dq.dq_run_history` | Metadata eksekusi: Run_ID, waktu, durasi, jumlah rule, Overall DQ Score |
| `silver.*` | Data yang lolos rule blocking |
| `gold.sales_by_category_month`, `gold.customer_sales_summary` | Data business-ready dari Silver |

## Skenario demo (± 15 menit)

1. **Tunjukkan masalahnya** - buka `source_data_dummy.xlsx`: ada email salah, Amount negatif, transaksi duplikat, dll.
2. **Tunjukkan metadata** - buka `dq_rule_catalog.xlsx`: semua aturan DQ hanyalah *baris data*.
3. **Jalankan pipeline** `pl_metadata_driven_dq` (atau notebook 01 → 02 → 03 satu per satu).
4. **Bahas engine** di `02_DQ_Engine`: satu loop generik + *Rule Library* (1 fungsi per `Rule_Type`).
5. **Lihat hasil** di `03_Gold_DQ_Dashboard`: Overall DQ Score, DQ Score per Dataset, Rule Validation Detail, Error Record (Quarantine).
6. **"Aha moment"** - jalankan `04_Demo_Change_Metadata`: aktifkan DQ012, tambah DQ013/DQ014, ubah threshold DQ004 → engine yang **sama** menghasilkan skor berbeda. *Tanpa mengubah kode.*
7. **Power BI** - buka report **Data Quality Monitoring** di workspace (lihat bagian [Power BI Report](#power-bi-report-data-quality-monitoring)). Setelah langkah 6, report langsung menampilkan run terbaru (Direct Lake, tanpa import ulang).

> Catatan: notebook `01_Ingest_Bronze` memuat ulang rule catalog dari Excel setiap pipeline jalan. Perubahan via notebook 04 bersifat sementara sampai pipeline berikutnya; untuk perubahan permanen, ubah Excel (atau jadikan tabel `meta.dq_rule_catalog` sebagai *source of truth*).

## Power BI Report: Data Quality Monitoring

Semantic model **Direct Lake** + report PBIR, disimpan sebagai PBIP di [powerbi/](powerbi/) (bisa dibuka di Power BI Desktop via [DataQualityMonitoring.pbip](powerbi/DataQualityMonitoring.pbip)).

```mermaid
erDiagram
    "DQ Run" ||--o{ "DQ Result" : "Run ID"
    "DQ Rule" ||--o{ "DQ Result" : "Rule ID"
    "DQ Run" ||--o{ "DQ Error Record" : "Run ID"
    "DQ Rule" ||--o{ "DQ Error Record" : "Rule ID = Error_Code"
```

| Tabel model | Sumber (lakehouse) | Peran |
|---|---|---|
| `DQ Result` | `dq.dq_results` | Fakta hasil per rule per run + measure utama (DQ Score, Rules Passed/Failed, Failed Records, Threshold, Rule Status) |
| `DQ Error Record` | `dq.dq_error_records` | Fakta record gagal (quarantine) + Error Record Count |
| `DQ Run` | `dq.dq_run_history` | Dimensi eksekusi (Run ID, Start Time, Run Status) |
| `DQ Rule` | `meta.dq_rule_catalog` | Dimensi rule dari metadata (Dataset, Column, Rule Type, Severity, Owner, ...) |

Semua measure otomatis memakai **run terakhir** (atau run yang dipilih di slicer *Run ID*), sehingga visual tidak menjumlahkan beberapa run sekaligus.

| Halaman | Isi |
|---|---|
| **Ringkasan DQ** | KPI (DQ Score, perubahan vs run sebelumnya, Rules Executed/Passed/Failed, Failed Records), gauge DQ Score vs target 95%, DQ Score per Dataset, tren DQ Score antar run, Rule Validation Detail (PASS/FAIL), Failed Records per Severity |
| **Error Records (Quarantine)** | Jumlah record dikarantina, record gagal per rule & per owner (siapa yang memperbaiki), detail record gagal + JSON record asli |
| **DQ Rule Catalog (Metadata)** | Isi metadata rule: jumlah rule per tipe/dataset, rule aktif, parameter, threshold, severity |

Build & deploy ulang:

```powershell
python scripts/build_report.py      # generate PBIR (powerbi/DataQualityMonitoring.Report) dari kode
python scripts/deploy_powerbi.py    # deploy semantic model (TMDL) + report ke workspace, lalu refresh model
```

## Deploy ulang / dari nol

```powershell
az login                                   # login dengan user yang punya akses ke workspace
python -m pip install -r requirements.txt
python scripts/setup_fabric.py --capacity "<nama capacity>"   # workspace + lakehouse (lewati jika sudah ada)
python scripts/generate_dummy_data.py      # (opsional) regenerate data dummy
python scripts/deploy_to_fabric.py --run   # upload + create/update notebook & pipeline + jalankan pipeline
python scripts/deploy_powerbi.py           # semantic model + report Power BI
```

Nama workspace/lakehouse bisa diganti lewat environment variable `FABRIC_WORKSPACE` dan `FABRIC_LAKEHOUSE`.

## Mengapa Metadata Driven?

1. **Scalability** - satu engine untuk ratusan hingga ribuan dataset.
2. **Maintainability** - aturan dikelola di metadata, bukan di kode.
3. **Reusability** - Rule Library dipakai ulang untuk semua dataset.
4. **Consistency** - standar & format hasil yang sama untuk semua dataset.
5. **Faster Delivery** - dataset baru = tambah baris konfigurasi.

## Referensi (Microsoft Learn)

- [Medallion lakehouse architecture in Microsoft Fabric](https://learn.microsoft.com/fabric/onelake/onelake-medallion-lakehouse-architecture)
- [Data quality in materialized lake views](https://learn.microsoft.com/fabric/data-engineering/materialized-lake-views/data-quality) - alternatif deklaratif (`CONSTRAINT ... CHECK ... ON MISMATCH DROP`)
- [Lakehouse schemas](https://learn.microsoft.com/fabric/data-engineering/lakehouse-schemas)
- [NotebookUtils (notebook.run / exit)](https://learn.microsoft.com/fabric/data-engineering/notebook-utilities)
- [Notebook activity di Data Pipeline](https://learn.microsoft.com/fabric/data-factory/notebook-activity)
- [Direct Lake semantic model](https://learn.microsoft.com/fabric/fundamentals/direct-lake-overview)
