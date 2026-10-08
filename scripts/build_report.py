"""
Generate laporan Power BI (format PBIR) "Data Quality Monitoring" dari kode.

Output: powerbi/DataQualityMonitoring.Report/  (bisa dibuka di Power BI Desktop via DataQualityMonitoring.pbip)
Halaman:
  1. Ringkasan DQ                - KPI, gauge DQ Score, skor per dataset, tren antar run, detail rule
  2. Error Records (Quarantine)  - record yang gagal validasi & siapa yang harus memperbaiki
  3. DQ Rule Catalog (Metadata)  - isi tabel metadata yang mengendalikan DQ Engine

Usage: python scripts/build_report.py
"""
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "powerbi"
REPORT = ROOT / "DataQualityMonitoring.Report"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
VC_SCHEMA = f"{SCHEMA}/visualContainer/2.9.0/schema.json"

# Palet warna sederhana & konsisten
NAVY, GREEN, RED, AMBER, GREY_BG, WHITE, TEXT = "#1F3A5F", "#2E9E44", "#D9342B", "#F2A900", "#F3F6FA", "#FFFFFF", "#252423"


# ---------------------------------------------------------------- helpers
def uid(*parts):
    """ID deterministik 20 hex (stabil antar build -> diff git rapi)."""
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def color(hex_):
    return {"solid": {"color": lit(f"'{hex_}'")}}


def field(entity, prop, kind="Column"):
    return {kind: {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj(entity, prop, kind="Column", label=None):
    p = {"field": field(entity, prop, kind), "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if label:
        p["displayName"] = label
    return p


def M(entity, prop, label=None):
    return proj(entity, prop, "Measure", label)


def C(entity, prop, label=None):
    return proj(entity, prop, "Column", label)


def container(title=None, bg=WHITE):
    """Visual container: background putih, sudut membulat, judul opsional."""
    vco = {
        "background": [{"properties": {"show": lit("true"), "color": color(bg)}}],
        "border": [{"properties": {"show": lit("true"), "color": color("#E1E5EA"), "radius": lit("8D")}}],
        "padding": [{"properties": {k: lit("8D") for k in ("top", "bottom", "left", "right")}}],
    }
    if title:
        vco["title"] = [{"properties": {"show": lit("true"), "text": lit(f"'{title}'"),
                                        "fontColor": color(NAVY), "bold": lit("true")}}]
    else:
        vco["title"] = [{"properties": {"show": lit("false")}}]
    return vco


def visual(page, key, vtype, pos, roles=None, objects=None, vco=None, sort=None):
    x, y, w, h = pos
    v = {"visualType": vtype}
    if roles:
        v["query"] = {"queryState": {r: {"projections": p} for r, p in roles.items()}}
        if sort:
            v["query"]["sortDefinition"] = {"sort": sort, "isDefaultSort": True}
    if objects:
        v["objects"] = objects
    if vco:
        v["visualContainerObjects"] = vco
    name = uid(page, key)
    z = 1000 + len(PAGES[page]["visuals"]) * 1000
    PAGES[page]["visuals"].append({
        "$schema": VC_SCHEMA, "name": name,
        "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
        "visual": v,
    })


def textbox(page, key, pos, text, size="20px", bold=True, col=NAVY):
    run = {"value": text, "textStyle": {"fontFamily": "Segoe UI Semibold" if bold else "Segoe UI",
                                        "fontSize": size, "color": col}}
    visual(page, key, "textbox", pos,
           objects={"general": [{"properties": {"paragraphs": [{"textRuns": [run], "horizontalTextAlignment": "left"}]}}]},
           vco={"background": [{"properties": {"show": lit("false")}}],
                "border": [{"properties": {"show": lit("false")}}],
                "padding": [{"properties": {k: lit("0D") for k in ("top", "bottom", "left", "right")}}]})


def slicer(page, key, pos, entity, prop, header):
    visual(page, key, "slicer", pos, roles={"Values": [C(entity, prop)]},
           objects={"data": [{"properties": {"mode": lit("'Dropdown'")}}],
                    "header": [{"properties": {"show": lit("true"), "text": lit(f"'{header}'")}}]},
           vco={"background": [{"properties": {"show": lit("true"), "color": color(WHITE)}}],
                "border": [{"properties": {"show": lit("true"), "color": color("#E1E5EA"), "radius": lit("8D")}}],
                "padding": [{"properties": {k: lit("8D") for k in ("top", "bottom", "left", "right")}}]})


def kpi_card(page, key, pos, measures, title=None):
    """Card multi-value (1 visual, beberapa KPI)."""
    visual(page, key, "cardVisual", pos, roles={"Data": measures},
           objects={"value": [{"properties": {"fontSize": lit("24D"), "bold": lit("true"), "fontColor": color(NAVY)},
                               "selector": {"id": "default"}}],
                    "label": [{"properties": {"show": lit("true"), "fontSize": lit("10D")}, "selector": {"id": "default"}}],
                    "outline": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}],
                    "cardCalloutArea": [{"properties": {"show": lit("true"), "paddingUniform": lit("8L"),
                                                        "rectangleRoundedCurve": lit("6L"),
                                                        "backgroundFillColor": color("#F7F9FC"),
                                                        "backgroundTransparency": lit("0D")}}]},
           vco=container(title))


def table(page, key, pos, cols, title, sort=None, totals=True):
    objects = {"columnHeaders": [{"properties": {"columnAdjustment": lit("'growToFit'"),
                                                 "autoSizeColumnWidth": lit("true"),
                                                 "fontColor": color(WHITE), "backColor": color(NAVY),
                                                 "bold": lit("true")}}],
               "values": [{"properties": {"backColorPrimary": color(WHITE), "backColorSecondary": color("#F2F5F9"),
                                          "fontColorPrimary": color(TEXT), "fontColorSecondary": color(TEXT)}}]}
    if not totals:
        objects["total"] = [{"properties": {"totals": lit("false")}}]
    visual(page, key, "tableEx", pos, roles={"Values": cols}, sort=sort, objects=objects,
           vco={**container(title), "stylePreset": [{"properties": {"name": lit("'None'")}}]})


def bar(page, key, pos, cat, meas, title, col=NAVY, sort_dir="Ascending"):
    visual(page, key, "clusteredBarChart", pos, roles={"Category": [cat], "Y": [meas]},
           sort=[{"field": meas["field"], "direction": sort_dir}],
           objects={"dataPoint": [{"properties": {"defaultColor": color(col)}}],
                    "labels": [{"properties": {"show": lit("true")}}]},
           vco=container(title))


def page(key, display):
    PAGES[key] = {"name": uid("page", key), "displayName": display, "visuals": []}


# ---------------------------------------------------------------- content
PAGES = {}
R, E, RUN, RULE = "DQ Result", "DQ Error Record", "DQ Run", "DQ Rule"

# ===== Halaman 1: Ringkasan DQ =====
page("overview", "Ringkasan DQ")
textbox("overview", "title", (20, 12, 820, 36), "Data Quality Monitoring - Metadata Driven Framework", "22px")
textbox("overview", "subtitle", (20, 50, 820, 24),
        "Hasil DQ Engine (Microsoft Fabric). Default: run terakhir - pilih Run ID untuk melihat run sebelumnya.",
        "12px", bold=False, col="#605E5C")
slicer("overview", "s_run", (900, 8, 180, 80), RUN, "Run ID", "Run ID")
slicer("overview", "s_ds", (1090, 8, 170, 80), RULE, "Dataset", "Dataset")
kpi_card("overview", "kpi", (20, 98, 1240, 110), [
    M(R, "DQ Score"), M(R, "DQ Score Change", "Δ vs Run Sebelumnya"), M(R, "Rules Executed"),
    M(R, "Rules Passed"), M(R, "Rules Failed"), M(R, "Failed Records")])
visual("overview", "gauge", "gauge", (20, 220, 300, 236),
       roles={"Y": [M(R, "DQ Score")], "TargetValue": [M(R, "DQ Score Target", "Target")]},
       objects={"axis": [{"properties": {"min": lit("0D"), "max": lit("1D")}}],
                "dataPoint": [{"properties": {"fill": color(GREEN), "target": color(RED)}}]},
       vco=container("Overall DQ Score vs Target"))
bar("overview", "by_ds", (330, 220, 460, 236), C(RULE, "Dataset"), M(R, "DQ Score"), "DQ Score per Dataset", GREEN)
visual("overview", "trend", "lineChart", (800, 220, 460, 236),
       roles={"Category": [C(RUN, "Run ID")], "Y": [M(R, "DQ Score")]},
       sort=[{"field": field(RUN, "Run ID"), "direction": "Ascending"}],
       objects={"dataPoint": [{"properties": {"defaultColor": color(NAVY)}}],
                "labels": [{"properties": {"show": lit("true")}}]},
       vco=container("Tren DQ Score per Eksekusi (Run History)"))
table("overview", "rules", (20, 468, 840, 242), [
    C(RULE, "Rule ID"), C(RULE, "Dataset"), C(RULE, "Column Name", "Column"), C(RULE, "Rule Type"),
    C(RULE, "Severity"), M(R, "DQ Score", "Pass %"), M(R, "Threshold"), M(R, "Failed Records"),
    M(R, "Rule Status", "Status")], "Rule Validation Detail (run terakhir)",
    sort=[{"field": field(R, "DQ Score", "Measure"), "direction": "Ascending"}])
visual("overview", "sev", "donutChart", (870, 468, 390, 242),
       roles={"Category": [C(RULE, "Severity")], "Y": [M(R, "Failed Records")]},
       objects={"labels": [{"properties": {"show": lit("true"), "labelStyle": lit("'Both'")}}]},
       vco=container("Failed Records per Severity"))

# ===== Halaman 2: Error Records (Quarantine) =====
page("errors", "Error Records (Quarantine)")
textbox("errors", "title", (20, 12, 820, 36), "Error Records (Quarantine)", "22px")
textbox("errors", "subtitle", (20, 50, 820, 24),
        "Record yang gagal validasi dan dikarantina - lengkap dengan nilai, rule, dan tim pemilik untuk perbaikan.",
        "12px", bold=False, col="#605E5C")
slicer("errors", "s_ds", (900, 8, 180, 80), RULE, "Dataset", "Dataset")
slicer("errors", "s_sev", (1090, 8, 170, 80), RULE, "Severity", "Severity")
kpi_card("errors", "kpi", (20, 98, 1240, 100), [
    M(E, "Error Record Count", "Record Dikarantina"), M(E, "Distinct Failed Values", "Nilai Unik Gagal"),
    M(R, "Failed Record Rate", "Failed Record Rate"), M(R, "Rules Failed")])
bar("errors", "by_rule", (20, 210, 620, 230), C(RULE, "Rule Description", "Rule"), M(E, "Error Record Count"),
    "Record Gagal per Rule", RED, "Descending")
bar("errors", "by_owner", (650, 210, 610, 230), C(RULE, "Owner"), M(E, "Error Record Count"),
    "Record Gagal per Owner (siapa yang memperbaiki)", AMBER, "Descending")
table("errors", "detail", (20, 452, 1240, 258), [
    C(RULE, "Rule ID", "Error Code"), C(RULE, "Dataset"), C(RULE, "Column Name", "Column"),
    C(E, "Failed Value", "Value"), C(RULE, "Rule Description", "Error Message"), C(RULE, "Owner"),
    M(E, "Error Record Count", "Jumlah"), C(E, "Record JSON")], "Detail Error Record (run terakhir)", totals=False)

# ===== Halaman 3: DQ Rule Catalog (Metadata) =====
page("catalog", "DQ Rule Catalog (Metadata)")
textbox("catalog", "title", (20, 12, 900, 36), "DQ Rule Catalog - Metadata yang Mengendalikan DQ Engine", "22px")
textbox("catalog", "subtitle", (20, 50, 1000, 24),
        "Tambah / ubah / nonaktifkan rule cukup di tabel metadata ini (meta.dq_rule_catalog) - tanpa mengubah kode engine.",
        "12px", bold=False, col="#605E5C")
slicer("catalog", "s_active", (1090, 8, 170, 80), RULE, "Is Active", "Is Active")
kpi_card("catalog", "kpi", (20, 98, 400, 100), [M(RULE, "Total Rules"), M(RULE, "Active Rules")])
bar("catalog", "by_type", (430, 98, 410, 210), C(RULE, "Rule Type"), M(RULE, "Total Rules"), "Jumlah Rule per Rule Type", NAVY,
    "Descending")
bar("catalog", "by_ds", (850, 98, 410, 210), C(RULE, "Dataset"), M(RULE, "Total Rules"), "Jumlah Rule per Dataset", GREEN,
    "Descending")
textbox("catalog", "note", (20, 210, 400, 98),
        "Severity High/Medium = blocking (record dikarantina, tidak masuk Silver). Severity Low = warning saja.",
        "12px", bold=False, col=TEXT)
table("catalog", "rules", (20, 320, 1240, 390), [
    C(RULE, "Rule ID"), C(RULE, "Dataset"), C(RULE, "Column Name", "Column"), C(RULE, "Rule Type"),
    C(RULE, "Rule Parameter"), C(RULE, "Catalog Threshold", "Threshold %"), C(RULE, "Severity"),
    C(RULE, "Owner"), C(RULE, "Rule Description", "Description"), C(RULE, "Is Active")], "DQ Rule Catalog",
    sort=[{"field": field(RULE, "Rule ID"), "direction": "Ascending"}], totals=False)


# ---------------------------------------------------------------- write files
def write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    theme_src = REPORT / "StaticResources" / "SharedResources" / "BaseThemes" / "CY24SU06.json"
    theme = theme_src.read_bytes() if theme_src.exists() else None
    if (REPORT / "definition").exists():
        shutil.rmtree(REPORT / "definition")
    d = REPORT / "definition"

    write(REPORT / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": "../DataQualityMonitoring.SemanticModel"}}})
    write(d / "version.json", {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    write(d / "report.json", {
        "$schema": f"{SCHEMA}/report/1.3.0/schema.json",
        "themeCollection": {"baseTheme": {"name": "CY24SU06", "reportVersionAtImport": "5.56", "type": "SharedResources"}},
        "layoutOptimization": "None",
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                              "items": [{"name": "CY24SU06", "path": "BaseThemes/CY24SU06.json", "type": "BaseTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True,
                     "allowChangeFilterTypes": True, "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True}})
    write(d / "pages" / "pages.json", {"$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json",
                                       "pageOrder": [p["name"] for p in PAGES.values()],
                                       "activePageName": PAGES["overview"]["name"]})
    for p in PAGES.values():
        pdir = d / "pages" / p["name"]
        write(pdir / "page.json", {
            "$schema": f"{SCHEMA}/page/2.1.0/schema.json", "name": p["name"], "displayName": p["displayName"],
            "displayOption": "FitToPage", "height": 720, "width": 1280,
            "objects": {"background": [{"properties": {"color": color(GREY_BG), "transparency": lit("0D")}}]}})
        for v in p["visuals"]:
            write(pdir / "visuals" / v["name"] / "visual.json", v)
    if theme:
        theme_src.write_bytes(theme)
    print(f"Report generated: {REPORT} ({sum(len(p['visuals']) for p in PAGES.values())} visuals, {len(PAGES)} pages)")


if __name__ == "__main__":
    main()
