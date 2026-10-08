"""
Deploy Power BI semantic model (Direct Lake) + report (PBIR) dari folder PBIP ke Microsoft Fabric.

  powerbi/DataQualityMonitoring.SemanticModel  -> Semantic model "Data Quality Monitoring"
  powerbi/DataQualityMonitoring.Report         -> Report         "Data Quality Monitoring"

Idempotent: jika item sudah ada -> updateDefinition, jika belum -> create.
Usage: python scripts/deploy_powerbi.py [--model-only]
"""
import base64
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_to_fabric import API, FABRIC, WORKSPACE_NAME, call, find, token  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "powerbi"
MODEL_DIR = ROOT / "DataQualityMonitoring.SemanticModel"
REPORT_DIR = ROOT / "DataQualityMonitoring.Report"
ITEM_NAME = "Data Quality Monitoring"
SKIP = {".pbi", ".platform"}  # file cache lokal Power BI Desktop, tidak ikut di-deploy


def folder_parts(folder: Path, overrides: dict | None = None):
    """Ubah seluruh file di folder PBIP menjadi 'parts' definisi Fabric (path relatif + base64)."""
    parts = []
    for f in sorted(folder.rglob("*")):
        rel = f.relative_to(folder).as_posix()
        if f.is_dir() or any(p in SKIP for p in rel.split("/")) or f.name in SKIP:
            continue
        data = (overrides or {}).get(rel, f.read_bytes())
        if isinstance(data, str):
            data = data.encode("utf-8")
        parts.append({"path": rel, "payload": base64.b64encode(data).decode(), "payloadType": "InlineBase64"})
    return parts


def upsert(ws_id, item_type, parts):
    existing = call("GET", f"{API}/workspaces/{ws_id}/items?type={item_type}")["value"]
    it = find(existing, ITEM_NAME)
    if it:
        call("POST", f"{API}/workspaces/{ws_id}/items/{it['id']}/updateDefinition", json={"definition": {"parts": parts}})
        print(f"  updated {item_type}: {ITEM_NAME} ({it['id']})")
        return it["id"]
    call("POST", f"{API}/workspaces/{ws_id}/items",
         json={"displayName": ITEM_NAME, "type": item_type, "definition": {"parts": parts}})
    it = find(call("GET", f"{API}/workspaces/{ws_id}/items?type={item_type}")["value"], ITEM_NAME)
    print(f"  created {item_type}: {ITEM_NAME} ({it['id']})")
    return it["id"]


def refresh_model(ws_id, model_id):
    """Refresh (framing) Direct Lake model agar membaca versi Delta terbaru."""
    pbi = {"Authorization": f"Bearer {token('https://analysis.windows.net/powerbi/api')}"}
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{ws_id}/datasets/{model_id}/refreshes"
    requests.post(url, headers=pbi, json={"type": "full"}).raise_for_status()
    for _ in range(30):
        time.sleep(5)
        last = requests.get(url + "?$top=1", headers=pbi).json()["value"][0]
        if last["status"] != "Unknown":
            print(f"  refresh: {last['status']}", last.get("serviceExceptionJson", ""))
            return last["status"]
    return "Timeout"


def main():
    ws_id = find(call("GET", f"{API}/workspaces")["value"], WORKSPACE_NAME)["id"]
    print("[1] Semantic model")
    model_id = upsert(ws_id, "SemanticModel", folder_parts(MODEL_DIR))
    refresh_model(ws_id, model_id)

    if "--model-only" not in sys.argv:
        print("[2] Report")
        # Saat deploy, report diikat ke semantic model di workspace (byConnection), bukan ke folder lokal (byPath)
        pbir = {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
            "version": "4.0",
            "datasetReference": {"byConnection": {"connectionString": f"semanticmodelid={model_id}"}},
        }
        upsert(ws_id, "Report", folder_parts(REPORT_DIR, {"definition.pbir": json.dumps(pbir, indent=2)}))
    print("Done.")


if __name__ == "__main__":
    main()
