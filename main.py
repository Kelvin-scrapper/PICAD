"""
PICAD — Japan Post Insurance annual report data (annual, fiscal year ending March 31).

Outputs (output/):
  PICAD_DATA_YYYYMMDD.xlsx   years printed in the latest report (current + prior year where shown)
  PICAD_META_YYYYMMDD.xlsx   LAST_RELEASE_DATE (PDF creation date, T11:00:00) only with --initial
  PICAD_YYYYMMDD.ZIP

Usage:
  cd PICAD
  python main.py                 # latest report
  python main.py --year 2025     # a back-number report
  python main.py --initial       # initial ingest: add LAST_RELEASE_DATE to META
"""
import argparse
import os
import zipfile
from datetime import date, datetime

import openpyxl
import pandas as pd

import mapper
import scraper

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(HERE, "output")
DOWNLOADS_DIR = os.path.join(HERE, "downloads")
OUTPUT_PREFIX = "PICAD"


def _datestamp():
    return datetime.now().strftime("%Y%m%d")


def _save_data(df, ds):
    path = os.path.join(OUTPUT_DIR, f"{OUTPUT_PREFIX}_DATA_{ds}.xlsx")
    df.to_excel(path, index=False, header=False)
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    ws.title = "DATA"
    for row in ws.iter_rows(min_row=3, min_col=2):
        for cell in row:
            if isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0.##"
    wb.save(path)
    return path


def _save_metadata(ds, info, initial):
    path = os.path.join(OUTPUT_DIR, f"{OUTPUT_PREFIX}_META_{ds}.xlsx")
    rows = mapper.build_metadata_rows(info, initial)
    nxt = f"{info['report_year'] + 1}-09-01T00:00:00"      # runbook: reports usually published in September
    for r in rows:
        r["NEXT_RELEASE_DATE"] = nxt
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


def _create_zip(data, meta, ds):
    path = os.path.join(OUTPUT_DIR, f"{OUTPUT_PREFIX}_{ds}.ZIP")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(data, os.path.basename(data))
        z.write(meta, os.path.basename(meta))
    return path


def scrape(year=None, initial=False):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pdf, info = scraper.fetch_data(DOWNLOADS_DIR, year)
    df = mapper.map_to_output(pdf)
    ds = _datestamp()
    data = _save_data(df, ds)
    meta = _save_metadata(ds, info, initial)
    z = _create_zip(data, meta, ds)
    if mapper.UNKNOWN:
        print(f"[main] {len(mapper.UNKNOWN)} source rows without a code (inform DataOps / Data Engineering):")
        for u in mapper.UNKNOWN:
            print("   ", u)
    print(f"[main] {data}\n[main] {meta}\n[main] {z}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="report year (default: latest on the page)")
    ap.add_argument("--initial", action="store_true", help="initial ingest: include LAST_RELEASE_DATE")
    a = ap.parse_args()
    scrape(a.year, a.initial)


if __name__ == "__main__":
    main()
