#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Standalone script to pull Feishu Bitable records and save JSON to Desktop.
Defaults are pre-filled so you can run directly:

  python3 pull_bitable.py

You can also override via CLI args:
  python3 pull_bitable.py --app-id CLI --app-secret SECRET \
      --app-token APP_TOKEN --table-id TBL_ID [--view-id VIEW_ID] \
      [--open-base https://open.feishu.cn] [--outfile /path/to/out.json]
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ===== Default configuration (you can change here) =====
DEFAULT_OPEN_BASE = os.getenv("OPEN_BASE", "https://open.feishu.cn")
DEFAULT_APP_ID = os.getenv("APP_ID", "cli_a989be153375d013")
DEFAULT_APP_SECRET = os.getenv("APP_SECRET", "uCVV1EC9At8CqyZbHpp3cdmIaCgXRqtB")
# From your link: https://.../base/YroIb5eqmawDUnspOTccmprFn2f?table=tbl6FdmkeqWl5cs5&view=vew2BpQrSd
DEFAULT_APP_TOKEN = "YroIb5eqmawDUnspOTccmprFn2f"
DEFAULT_TABLE_ID = "tbl6FdmkeqWl5cs5"
DEFAULT_VIEW_ID = "vew2BpQrSd"  # optional; can be empty

# Save to user's Desktop by default
DEFAULT_OUTFILE = os.path.join(os.getenv("OUTPUT_DIR", os.path.join(os.path.expanduser("~"), "Desktop")), f"bitable_{DEFAULT_TABLE_ID}.json")


def get_tenant_access_token(open_base: str, app_id: str, app_secret: str) -> str:
    url = f"{open_base}/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"get_tenant_access_token failed: {data}")
    return data["tenant_access_token"]


def list_bitable_records(
    open_base: str,
    app_token: str,
    table_id: str,
    tenant_token: str,
    view_id: Optional[str] = None,
    page_size: int = 500,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    headers = {"Authorization": f"Bearer {tenant_token}"}

    while True:
        url = f"{open_base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        params: Dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        if view_id:
            params["view_id"] = view_id

        r = requests.get(url, headers=headers, params=params, timeout=15)
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"list_records failed: {data}")
        items.extend(data["data"].get("items", []))
        if not data["data"].get("has_more"):
            break
        page_token = data["data"].get("page_token")
    return items


def save_json(items: List[Dict[str, Any]], outfile: str) -> str:
    os.makedirs(os.path.dirname(outfile), exist_ok=True)
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return outfile


# ===== Strict view order helpers =====
def list_fields(
    open_base: str,
    app_token: str,
    table_id: str,
    tenant_token: str,
    view_id: Optional[str],
) -> List[str]:
    """Return ordered field names according to view's visible order.
    Fallback to table field order if view layout API not available.
    """
    headers = {"Authorization": f"Bearer {tenant_token}"}
    # 1) table fields
    url_fields = f"{open_base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    fields: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(url_fields, headers=headers, params=params, timeout=10).json()
        if r.get("code") != 0:
            raise RuntimeError(f"list_fields failed: {r}")
        fields += r["data"].get("items", [])
        if not r["data"].get("has_more"):
            break
        page_token = r["data"].get("page_token")

    field_id_order = [f["field_id"] for f in fields]
    id_to_name = {f["field_id"]: f["field_name"] for f in fields}

    # 2) try view columns order (best effort, not all envs support)
    try:
        if view_id:
            url_view = f"{open_base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/views/{view_id}"
            rv = requests.get(url_view, headers=headers, timeout=10).json()
            data = rv.get("data", {})
            view = data.get("view", data)
            cols = view.get("columns")
            if isinstance(cols, list) and cols:
                vis = [c.get("field_id") for c in cols if c.get("is_visible", True)]
                rest = [fid for fid in field_id_order if fid not in vis]
                field_id_order = vis + rest
    except Exception:
        pass

    ordered_names = [id_to_name[fid] for fid in field_id_order if fid in id_to_name]
    return ordered_names


def save_csv_with_order(
    items: List[Dict[str, Any]], ordered_field_names: List[str], outfile_csv: str
) -> str:
    import csv

    rows = [it.get("fields", {}) or {} for it in items]
    os.makedirs(os.path.dirname(outfile_csv), exist_ok=True)
    with open(outfile_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ordered_field_names)
        w.writeheader()
        for r in rows:
            row_out: Dict[str, Any] = {}
            for k in ordered_field_names:
                v = r.get(k)
                if isinstance(v, (list, dict)):
                    # Join lists by semicolon for readability; dict as compact JSON
                    row_out[k] = (
                        "; ".join([json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(x) for x in v])
                        if isinstance(v, list)
                        else json.dumps(v, ensure_ascii=False)
                    )
                else:
                    row_out[k] = v
            w.writerow(row_out)
    return outfile_csv


def save_xlsx_with_order(
    items: List[Dict[str, Any]], ordered_field_names: List[str], outfile_xlsx: str
) -> str:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "BitableExport"

    # header
    ws.append(ordered_field_names)

    # rows
    for it in items:
        r = it.get("fields", {}) or {}
        row = []
        for k in ordered_field_names:
            v = r.get(k)
            if isinstance(v, (list, dict)):
                cell = (
                    "; ".join([json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(x) for x in v])
                    if isinstance(v, list)
                    else json.dumps(v, ensure_ascii=False)
                )
            else:
                cell = v
            row.append(cell)
        ws.append(row)

    os.makedirs(os.path.dirname(outfile_xlsx), exist_ok=True)
    wb.save(outfile_xlsx)
    return outfile_xlsx


def pull_to_files(
    open_base: str,
    app_id: str,
    app_secret: str,
    app_token: str,
    table_id: str,
    view_id: Optional[str],
    outfile: str,  # 应该是完整的 .xlsx 路径
) -> Dict[str, Any]:
    """End-to-end: fetch token, list records, save Excel only.
    Returns dict with count and Excel file path.
    """
    token = get_tenant_access_token(open_base, app_id, app_secret)
    items = list_bitable_records(open_base, app_token, table_id, token, view_id=view_id)
    ordered_field_names = list_fields(open_base, app_token, table_id, token, view_id)
    out: Dict[str, Any] = {"count": len(items)}
    # 只导出 Excel
    out["xlsx"] = save_xlsx_with_order(items, ordered_field_names, outfile)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Pull Feishu Bitable records to JSON")
    parser.add_argument("--open-base", default=DEFAULT_OPEN_BASE)
    parser.add_argument("--app-id", default=DEFAULT_APP_ID)
    parser.add_argument("--app-secret", default=DEFAULT_APP_SECRET)
    parser.add_argument("--app-token", default=DEFAULT_APP_TOKEN)
    parser.add_argument("--table-id", default=DEFAULT_TABLE_ID)
    parser.add_argument("--view-id", default=DEFAULT_VIEW_ID)
    parser.add_argument("--outfile", default=DEFAULT_OUTFILE)
    parser.add_argument("--csv", action="store_true", help="also save CSV with view column order")
    parser.add_argument("--xlsx", action="store_true", help="also save Excel (xlsx) with view column order")

    args = parser.parse_args(argv)

    print(f"[INFO] open_base={args.open_base}")
    print(f"[INFO] app_id={args.app_id}")
    print(f"[INFO] app_token={args.app_token}")
    print(f"[INFO] table_id={args.table_id}")
    if args.view_id:
        print(f"[INFO] view_id={args.view_id}")

    try:
        print("[STEP] fetching tenant_access_token …")
        token = get_tenant_access_token(args.open_base, args.app_id, args.app_secret)
        print("[OK] tenant_access_token obtained")

        print("[STEP] listing records …")
        t0 = time.time()
        items = list_bitable_records(
            args.open_base, args.app_token, args.table_id, token, view_id=args.view_id
        )
        dt = time.time() - t0
        print(f"[OK] fetched {len(items)} records in {dt:.2f}s")

        print("[STEP] fetching field order …")
        ordered_field_names = list_fields(
            args.open_base, args.app_token, args.table_id, token, args.view_id
        )

        print(f"[STEP] saving JSON to {args.outfile} …")
        path = save_json(items, args.outfile)
        print(f"[DONE] JSON saved: {path}")

        if args.csv:
            csv_out = os.path.splitext(args.outfile)[0] + ".csv"
            print(f"[STEP] saving CSV (strict column order) to {csv_out} …")
            save_csv_with_order(items, ordered_field_names, csv_out)
            print(f"[DONE] CSV saved: {csv_out}")

        if args.xlsx:
            xlsx_out = os.path.splitext(args.outfile)[0] + ".xlsx"
            print(f"[STEP] saving Excel (strict column order) to {xlsx_out} …")
            save_xlsx_with_order(items, ordered_field_names, xlsx_out)
            print(f"[DONE] Excel saved: {xlsx_out}")
        return 0
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

