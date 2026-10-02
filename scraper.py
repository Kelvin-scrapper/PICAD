"""
PICAD scraper — Japan Post Insurance (JPI) Annual Report, Data Section (A4).

Source page: PAGE_URL. The latest "Annual Report YYYY (A4 size) (Data Section)" PDF is picked by its
link text (no hardcoded file names). Download only: saves the PDF to downloads/ and returns its path,
the report year and the PDF creation date (used for LAST_RELEASE_DATE, per runbook).

Usage:
    from scraper import fetch_data
    path, info = fetch_data("downloads")
"""
import os
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PAGE_URL = "https://www.jp-life.japanpost.jp/english/aboutus/financial/en_abt_fnc_ar.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
LINK_RE = re.compile(r"Annual Report\s+(\d{4})\s*\(A4 size\)\s*\(Data Section\)", re.I)


def _pdf_created(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        raw = (pdf.metadata or {}).get("CreationDate", "")
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", raw)
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date() if m else None


def fetch_data(downloads_dir, year=None):
    """Download the Data Section (A4) PDF of the latest (or given) report year."""
    os.makedirs(downloads_dir, exist_ok=True)
    r = requests.get(PAGE_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        m = LINK_RE.search(a.get_text(" ", strip=True))
        if m and a["href"].lower().endswith(".pdf"):
            found.setdefault(int(m.group(1)), urljoin(PAGE_URL, a["href"]))
    if not found:
        with open(os.path.join(downloads_dir, "debug_page.html"), "wb") as f:
            f.write(r.content)
        raise RuntimeError("No 'Annual Report YYYY (A4 size) (Data Section)' link (page saved to downloads/)")
    year = year or max(found)
    url = found[year]
    path = os.path.join(downloads_dir, url.rsplit("/", 1)[-1])
    f = requests.get(url, headers=HEADERS, timeout=180)
    f.raise_for_status()
    with open(path, "wb") as fh:
        fh.write(f.content)
    info = {"report_year": year, "created": _pdf_created(path), "url": url}
    print(f"[scraper] Annual Report {year} data section -> {os.path.basename(path)} "
          f"({len(f.content):,} bytes), PDF created {info['created']}")
    return path, info


if __name__ == "__main__":
    print(fetch_data(os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")))
