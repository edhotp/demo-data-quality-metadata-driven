"""
Siapkan workspace + lakehouse untuk demo Metadata Driven DQ (idempotent - aman dijalankan berulang).

  - Workspace  : FABRIC_WORKSPACE (default ws_fabric_metadata_driven_dq), di-assign ke capacity yang dipilih
  - Lakehouse  : FABRIC_LAKEHOUSE (default lh_metadata_dq) dengan Lakehouse schemas aktif

Usage:
  python scripts/setup_fabric.py --list-capacities          # lihat capacity yang bisa dipakai
  python scripts/setup_fabric.py --capacity "<nama capacity>"
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_to_fabric import API, LAKEHOUSE_NAME, WORKSPACE_NAME, call, find  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capacity", help="Nama (displayName) Fabric capacity untuk workspace baru")
    ap.add_argument("--list-capacities", action="store_true")
    args = ap.parse_args()

    caps = call("GET", f"{API}/capacities")["value"]
    if args.list_capacities:
        for c in caps:
            print(f"{c['displayName']:<50} sku={c['sku']:<6} state={c['state']:<9} region={c.get('region', '')}")
        return

    # ---- 1. Workspace ----
    ws = find(call("GET", f"{API}/workspaces")["value"], WORKSPACE_NAME)
    if ws:
        print(f"Workspace sudah ada : {WORKSPACE_NAME} ({ws['id']})")
    else:
        if not args.capacity:
            sys.exit("Workspace belum ada. Jalankan ulang dengan --capacity \"<nama capacity>\" "
                     "(lihat daftar dengan --list-capacities).")
        cap = find(caps, args.capacity)
        if not cap or cap["state"] != "Active":
            sys.exit(f"Capacity '{args.capacity}' tidak ditemukan atau tidak Active.")
        ws = call("POST", f"{API}/workspaces", json={
            "displayName": WORKSPACE_NAME, "capacityId": cap["id"],
            "description": "Demo Metadata Driven Data Quality Framework"})
        print(f"Workspace dibuat    : {WORKSPACE_NAME} ({ws['id']}) di capacity {cap['displayName']}")

    # ---- 2. Lakehouse (schemas enabled) ----
    lh = find(call("GET", f"{API}/workspaces/{ws['id']}/lakehouses")["value"], LAKEHOUSE_NAME)
    if lh:
        print(f"Lakehouse sudah ada : {LAKEHOUSE_NAME} ({lh['id']})")
        return
    call("POST", f"{API}/workspaces/{ws['id']}/items", json={
        "displayName": LAKEHOUSE_NAME, "type": "Lakehouse",
        "description": "Lakehouse demo Metadata Driven DQ (bronze/silver/gold/meta/dq)",
        "creationPayload": {"enableSchemas": True}})
    for _ in range(10):  # tunggu sampai lakehouse muncul di daftar
        lh = find(call("GET", f"{API}/workspaces/{ws['id']}/lakehouses")["value"], LAKEHOUSE_NAME)
        if lh:
            break
        time.sleep(3)
    print(f"Lakehouse dibuat    : {LAKEHOUSE_NAME} ({lh['id']})")


if __name__ == "__main__":
    main()
