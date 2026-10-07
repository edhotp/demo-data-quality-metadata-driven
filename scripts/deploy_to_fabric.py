"""
Deploy demo Metadata Driven DQ ke Microsoft Fabric (idempotent - aman dijalankan berulang).

Langkah:
  1. Konversi notebooks/*.py (format "percent" # %%) -> notebooks/*.ipynb
  2. Upload file Excel dummy ke OneLake: <lakehouse>/Files/landing/
  3. Create / update 4 notebook di workspace (default lakehouse sudah ter-attach)
  4. Create / update Data Pipeline: 01 -> 02 -> 03

Prasyarat: `az login` dengan user yang punya akses ke workspace.
Usage   : python scripts/deploy_to_fabric.py [--run]
"""
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

WORKSPACE_NAME = "ws_fabric_metadata_driven_dq"
LAKEHOUSE_NAME = "lh_metadata_dq"
PIPELINE_NAME = "pl_metadata_driven_dq"
NOTEBOOKS = ["01_Ingest_Bronze", "02_DQ_Engine", "03_Gold_DQ_Dashboard", "04_Demo_Change_Metadata"]
PIPELINE_STEPS = NOTEBOOKS[:3]  # notebook 04 hanya untuk demo manual

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.fabric.microsoft.com/v1"
ONELAKE = "https://onelake.dfs.fabric.microsoft.com"
HDR_SKILL = {"x-ms-fabric-skill": "spark-cli"}


def token(resource):
    out = subprocess.run(f'az account get-access-token --resource {resource} --query accessToken -o tsv',
                         shell=True, capture_output=True, text=True, check=True)
    return out.stdout.strip()


FABRIC = {"Authorization": f"Bearer {token('https://api.fabric.microsoft.com')}", **HDR_SKILL}


def call(method, url, **kw):
    """Panggil Fabric REST API + tunggu Long Running Operation (202) jika ada."""
    r = requests.request(method, url, headers=FABRIC, **kw)
    if r.status_code == 202 and "Location" in r.headers:
        loc = r.headers["Location"]
        while True:
            time.sleep(int(r.headers.get("Retry-After", 3)))
            r = requests.get(loc, headers=FABRIC)
            state = r.json().get("status") if r.content else None
            if state in ("Succeeded", "Failed", "Cancelled") or r.status_code == 200 and state is None:
                if state == "Failed":
                    raise RuntimeError(r.text)
                res = requests.get(loc + "/result", headers=FABRIC)
                return res.json() if res.ok and res.content else {}
    if not r.ok:
        raise RuntimeError(f"{method} {url} -> {r.status_code}: {r.text}")
    return r.json() if r.content else {}


def find(items, name):
    return next((i for i in items if i["displayName"] == name), None)


# ---------- 1. .py (percent format) -> .ipynb ----------
def py_to_ipynb(src: Path, ws_id: str, lh_id: str) -> dict:
    cells, cur, kind = [], [], None

    def flush():
        if kind is None:
            return
        lines = cur[:]
        while lines and not lines[-1].strip():
            lines.pop()
        if kind == "markdown":
            lines = [l[2:] if l.startswith("# ") else l.lstrip("#") for l in lines]
        src_lines = [l + "\n" for l in lines]
        if src_lines:
            src_lines[-1] = src_lines[-1].rstrip("\n")
        cell = {"cell_type": kind, "metadata": {}, "source": src_lines}
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
            if any("PARAMETERS CELL" in l for l in lines):
                cell["metadata"] = {"tags": ["parameters"]}
        cells.append(cell)

    for line in src.read_text(encoding="utf-8").splitlines():
        if line.startswith("# %%"):
            flush()
            kind, cur = ("markdown" if "[markdown]" in line else "code"), []
        else:
            cur.append(line)
    flush()
    return {
        "nbformat": 4, "nbformat_minor": 5, "cells": cells,
        "metadata": {
            "language_info": {"name": "python"},
            "kernel_info": {"name": "synapse_pyspark"},
            "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark", "language": "Python"},
            "dependencies": {"lakehouse": {"default_lakehouse": lh_id, "default_lakehouse_name": LAKEHOUSE_NAME,
                                           "default_lakehouse_workspace_id": ws_id}},
        },
    }


def b64(obj) -> str:
    data = obj if isinstance(obj, str) else json.dumps(obj, indent=1, ensure_ascii=False)
    return base64.b64encode(data.encode("utf-8")).decode()


def upsert_item(ws_id, existing, name, item_type, parts, description=""):
    definition = {"parts": parts}
    if item_type == "Notebook":
        definition["format"] = "ipynb"
    it = find(existing, name)
    if it:
        call("POST", f"{API}/workspaces/{ws_id}/items/{it['id']}/updateDefinition", json={"definition": definition})
        print(f"  updated  {item_type:<13} {name}")
        return it["id"]
    created = call("POST", f"{API}/workspaces/{ws_id}/items",
                   json={"displayName": name, "type": item_type, "description": description, "definition": definition})
    if not created.get("id"):  # LRO result kadang kosong -> cari ulang
        created = find(call("GET", f"{API}/workspaces/{ws_id}/items")["value"], name)
    print(f"  created  {item_type:<13} {name}")
    return created["id"]


def upload_onelake(ws_id, lh_id, local: Path, remote: str):
    """Upload file ke OneLake via ADLS Gen2 DFS API (create -> append -> flush)."""
    h = {"Authorization": f"Bearer {token('https://storage.azure.com')}"}
    url = f"{ONELAKE}/{ws_id}/{lh_id}/Files/{remote}"
    data = local.read_bytes()
    requests.put(f"{url}?resource=file", headers=h).raise_for_status()
    requests.patch(f"{url}?action=append&position=0", headers=h, data=data).raise_for_status()
    requests.patch(f"{url}?action=flush&position={len(data)}", headers=h).raise_for_status()
    print(f"  uploaded Files/{remote} ({len(data):,} bytes)")


def main():
    ws = find(call("GET", f"{API}/workspaces")["value"], WORKSPACE_NAME)
    ws_id = ws["id"]
    lh = find(call("GET", f"{API}/workspaces/{ws_id}/lakehouses")["value"], LAKEHOUSE_NAME)
    lh_id = lh["id"]
    print(f"Workspace {WORKSPACE_NAME} = {ws_id}\nLakehouse {LAKEHOUSE_NAME} = {lh_id}")

    print("[1] Upload Excel ke OneLake")
    for f in ["source_data_dummy.xlsx", "dq_rule_catalog.xlsx"]:
        upload_onelake(ws_id, lh_id, ROOT / "data" / f, f"landing/{f}")

    print("[2] Notebooks")
    existing = call("GET", f"{API}/workspaces/{ws_id}/items")["value"]
    nb_ids = {}
    for nb in NOTEBOOKS:
        ipynb = py_to_ipynb(ROOT / "notebooks" / f"{nb}.py", ws_id, lh_id)
        (ROOT / "notebooks" / f"{nb}.ipynb").write_text(json.dumps(ipynb, indent=1, ensure_ascii=False), encoding="utf-8")
        nb_ids[nb] = upsert_item(ws_id, existing, nb, "Notebook",
                                 [{"path": "notebook-content.ipynb", "payload": b64(ipynb), "payloadType": "InlineBase64"}])

    print("[3] Data Pipeline (orchestration)")
    activities, prev = [], None
    for nb in PIPELINE_STEPS:
        activities.append({
            "name": nb, "type": "TridentNotebook",
            "dependsOn": [{"activity": prev, "dependencyConditions": ["Succeeded"]}] if prev else [],
            "policy": {"timeout": "0.01:00:00", "retry": 0, "retryIntervalInSeconds": 30,
                       "secureOutput": False, "secureInput": False},
            "typeProperties": {"notebookId": nb_ids[nb], "workspaceId": ws_id},
        })
        prev = nb
    pipeline = {"properties": {"description": "Metadata Driven DQ: Ingest Bronze -> DQ Engine -> Gold & Dashboard",
                               "activities": activities}}
    pl_id = upsert_item(ws_id, existing, PIPELINE_NAME, "DataPipeline",
                        [{"path": "pipeline-content.json", "payload": b64(pipeline), "payloadType": "InlineBase64"}])

    if "--run" in sys.argv:
        r = requests.post(f"{API}/workspaces/{ws_id}/items/{pl_id}/jobs/instances?jobType=Pipeline", headers=FABRIC)
        r.raise_for_status()
        print(f"[4] Pipeline run started: {r.headers.get('Location')}")
    print("Done.")


if __name__ == "__main__":
    main()
