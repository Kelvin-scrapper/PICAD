"""
PICAD mapper — JPI Annual Report (Data Section PDF) -> AfricaAI 2-header-row DATA.

Raw file layout (text layer, pdfplumber): tables are located by their title line, never by page number:
  (n) Securities Composition                         2 years x (Amount, %)            -> Amount
  4) Policy-reserve-matching bonds sold ...          sub-tables per currency + year,
  5) Available-for-sale securities sold ...          columns Sales / Gains / Losses     -> all 3, Total excluded
  1) Breakdown by Asset Composition                   2 years x (Amount, %), 3 groups    -> Amount, Subtotal/Net excluded
  2) Overseas Loans and Investments by Geographic Area  'As of March 31, YYYY' blocks,
                                                      4 x (Amount, %)                    -> Amounts
  3) Composition of Foreign-Currency-Denominated Assets by Currency -> Amount (incl. Total)
  2) Assets Held-to-Maturity in Trust / ... / Other Money Held in Trust
                                                      2 years x (Book, Fair, Net, Gains, Losses) -> Book, Fair
  4) Currency Composition of Money Held in Trust      2 years x (Amount, %)            -> Amount, Total excluded
Labels wrap over several lines; a row's label = pending label-only lines + its own text.
Values: '(x)' -> -x, '–' -> empty. Period = fiscal year end (March 31, YYYY) -> 'YYYY'.
"""
import os
import re

import pandas as pd
import pdfplumber

HERE = os.path.dirname(os.path.abspath(__file__))

# ≤ 20 series rule does not apply (156 series) -> headers.json
import json
with open(os.path.join(HERE, "headers.json"), encoding="utf-8") as _f:
    COLUMN_HEADERS = json.load(_f)

NUM = r"\(?-?[\d,]+(?:\.\d+)?\)?|[–—-]"
NUM_RE = re.compile(rf"^(?:{NUM})$")
YEAR_RE = re.compile(r"(?<!\d)(20\d\d)(?!\d)")
UNKNOWN = []      # rows found in the source with no code (reported by main.py)


# ---------------------------------------------------------------- value / period helpers
def parse_value(tok):
    t = tok.strip()
    if t in ("–", "—", "-"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    v = float(t.strip("()").replace(",", ""))
    v = -v if neg else v
    return 0.0 if v == 0 else v


def parse_period(year):
    return str(int(year))


def _split(line):
    """'Japanese corporate bonds 136,837 – (119,614)' -> ('Japanese corporate bonds', ['136,837','–','(119,614)'])"""
    toks = re.sub(r"[¥$]\s*", "", line).split()      # older reports print '¥ 1,234' / '$ 12'
    i = len(toks)
    while i > 0 and NUM_RE.match(toks[i - 1]):
        i -= 1
    return " ".join(toks[:i]), toks[i:]


def _norm(s):
    return re.sub(r"\s+", " ", s.replace("- ", "-")).strip().lower()


def rows(lines, min_nums=2):
    """Yield (label, numbers) with wrapped labels joined. Label-only lines are held as pending."""
    pending = []
    for ln in lines:
        label, nums = _split(ln)
        if len(nums) < min_nums:
            if ln.strip():
                pending.append(ln.strip())
            continue
        full = " ".join(pending + ([label] if label else []))
        pending = []
        if re.match(r"^\(millions of", _norm(label or full)) or re.fullmatch(r"[\d\s]+", " ".join(nums)) and len(nums) <= 3                 and all(YEAR_RE.fullmatch(n) for n in nums):
            continue                                            # unit / year header lines
        yield _norm(full), _norm(label), nums


# ---------------------------------------------------------------- locating tables
def _pages_text(path):
    with pdfplumber.open(path) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


def _section(all_lines, title_re, last=True):
    """Lines from a title line to the next numbered title / notes. Picks the last (or first) occurrence."""
    starts = [i for i, l in enumerate(all_lines) if re.match(title_re, l.strip(), re.I) and not re.search(r"\.{5,}", l)]
    if not starts:
        raise ValueError(f"table title not found: {title_re}")
    s = starts[-1] if last else starts[0]
    out = []
    for l in all_lines[s + 1:]:
        if re.match(r"^(\(\d+\)|\d\))\s+[A-Z]", l.strip()) or re.match(r"^Notes?\s*:?", l.strip()):
            break
        out.append(l)
    return all_lines[s], out


def _years(lines):
    for l in lines:
        ys = YEAR_RE.findall(l)
        if len(ys) >= 2 and re.fullmatch(r"[\d\s]+|For the years ended March 31\s[\d\s]+|As of March 31\s[\d\s]+", l.strip()):
            return ys
    raise ValueError("year header not found")


# ---------------------------------------------------------------- label -> code part rules
def _first(label, rules):
    for key, pat in rules:
        if re.search(pat, label):
            return key
    return None


SECCOM = [("CORGOVBOND.JCORB.PUBENTB", r"public entity"), ("CORGOVBOND.JLGOVB", r"japanese local government"),
          ("CORGOVBOND.JGOVB", r"japanese government"), ("CORGOVBOND.JCORB", r"japanese corporate"),
          ("FORSEC.FORCORGOVB", r"foreign corporate"), ("FORSEC.FORSTOCKOTHER", r"foreign stocks"),
          ("CORGOVBOND", r"^corporate and government"), ("DOMSTOCK", r"domestic stocks"),
          ("FORSEC", r"^foreign securities"), ("OTHER", r"^other securities"), ("TOTAL", r"^total$")]

SOLD = [("BOND.JGOVB", r"japanese government"), ("BOND.JLGOVB", r"japanese local government"),
        ("BOND.JCORB", r"japanese corporate"), ("BOND", r"^bonds$"), ("STOCK", r"^stocks$"),
        ("FORSEC.FORBOND", r"^foreign bonds"), ("FORSEC.FOROTHER", r"foreign other"),
        ("FORSEC", r"^foreign securities"), ("OTHER", r"^other securities")]

REGIONS = [("NRAM", r"north america"), ("EURP", r"europe"), ("OCE", r"oceania"), ("ASIACHINA", r"\basia\b"),
           ("CSAMER", r"central and south america"), ("O9", r"middle east"), ("AFR", r"africa"),
           ("INTORG", r"international organi[sz]ation")]

CURRENCY = [("USD", r"u\.?s\.? dollar"), ("EUR", r"^euro$"), ("AUD", r"australian dollar"), ("NZD", r"new zealand"),
            ("CAD", r"canadian"), ("SGD", r"singapore"), ("GBP", r"british pound|pound sterling"),
            ("SEK", r"swedish"), ("PLN", r"polish"), ("TOTAL", r"^total$")]

TRUST = [("AHELDMAT", r"held-to-maturity"), ("AHELDRES", r"held for reserves|reserves in trust"),
         ("OTHERMONHELD.DOMSTOCK", r"domestic stocks"), ("OTHERMONHELD.FORSTOCK", r"foreign stocks"),
         ("OTHERMONHELD.FORBOND", r"foreign bonds"), ("OTHERMONHELD", r"other money held"),
         ("OTHERMONHELD.OTHER", r"(^|\s)other$")]

TRUSTCUR = [("JPY", r"japanese yen"), ("USD", r"u\.?s\.? dollar"), ("EUR", r"^euro$"), ("OTHER", r"^others?$")]


# ---------------------------------------------------------------- table extractors -> {(code, year): value}
def _put(out, code, year, tok, table, label):
    if tok is None:
        return
    out[(code, parse_period(year))] = parse_value(tok)


def ex_amount_table(lines, prefix, rules, out, table, skip=(r"^total$",), own=True):
    ys = _years(lines)
    for full, lab, nums in rows(lines):
        key = _first(lab if own and lab else full, rules) or _first(full, rules)
        if any(re.search(s, lab or full) for s in skip) and key != "TOTAL":
            continue
        if key is None:
            UNKNOWN.append((table, full, nums)); continue
        for k, y in enumerate(ys):
            _put(out, f"PICAD.{prefix}.{key}.A", y, nums[2 * k] if 2 * k < len(nums) else None, table, full)


def ex_sold(lines, prefix, out, table):
    ccy, year = None, None
    for ln in lines:
        s = ln.strip()
        if re.search(r"millions of yen", s, re.I):
            ccy = "JPY"; continue
        if re.search(r"millions of u\.?s\.? dollars", s, re.I):
            ccy = "USD"; continue
        if re.fullmatch(r"20\d\d", s):
            year = s; continue
        label, nums = _split(s)
        if len(nums) != 3 or not ccy or not year:
            continue
        lab = _norm(label)
        if lab == "total":
            continue
        key = _first(lab, SOLD)
        if key is None:
            UNKNOWN.append((table, lab, nums)); continue
        for col, tok in zip(("SALE", "GAIN", "LOS"), nums):
            _put(out, f"PICAD.{prefix}.{ccy}.{col}.{key}.A", year, tok, table, lab)


def ex_breakdown(lines, out, table):
    ys = _years(lines)
    groups = ["FORCURA", "FORCURFIX", "YENDENA"]
    g = 0
    for full, lab, nums in rows(lines):
        if lab.startswith("subtotal"):
            g += 1; continue
        if "net overseas" in full:
            continue
        if "loans to non-residents" in full:
            key = "YENDENA.LOANNONRES"
        elif "other assets" in full:
            key = "YENDENA.FORCORGOVB"
        else:
            part = "CASHEQ" if "cash" in full else "STOCK" if "stocks" in full else "CORGOVB" if "bond" in full else None
            if part is None or g > 1:
                UNKNOWN.append((table, full, nums)); continue
            key = f"{groups[g]}.{part}"
        for k, y in enumerate(ys):
            _put(out, f"PICAD.BREAKACOMP.{key}.A", y, nums[2 * k], table, full)


def ex_geo(lines, out, table):
    year = None
    for full, lab, nums in rows(lines, min_nums=8):
        m = re.search(r"as of march 31,?\s*(20\d\d)", full + " " + " ".join(nums[:2]))
        if m:
            year = m.group(1); continue
        reg = _first(full, REGIONS)
        if reg is None or year is None:
            UNKNOWN.append((table, full, nums)); continue
        for idx, part in ((0, "FORSEC"), (2, "FORSEC.CORGOVB"), (4, "FORSEC.STOCK"), (6, "LOANONRES")):
            _put(out, f"PICAD.OVERLOAN.{part}.{reg}.A", year, nums[idx], table, full)


def ex_trust(lines, out, table):
    ys = _years(lines)
    for full, lab, nums in rows(lines, min_nums=10):
        key = _first(lab, TRUST) if lab else None
        key = key or _first(full, TRUST)
        if key is None:
            UNKNOWN.append((table, full, nums)); continue
        base, _, sub = key.partition(".")
        for k, y in enumerate(ys):
            for off, col in ((0, "BOOK"), (1, "FAIR")):
                code = f"PICAD.{base}.{col}" + (f".{sub}" if sub else "") + ".A"
                _put(out, code, y, nums[5 * k + off], table, full)


def extract(path):
    UNKNOWN.clear()
    lines = [l for t in _pages_text(path) for l in t.split("\n")]
    out = {}
    _, sec = _section(lines, r"^\(\d+\)\s*Securities Composition\s*$")
    ex_amount_table(sec, "SECCOM", SECCOM, out, "Securities Composition")
    _, sec = _section(lines, r"^\d\)\s*Policy-reserve-matching bonds sold")
    ex_sold(sec, "POLRESYEAR", out, "Policy-reserve-matching bonds sold")
    _, sec = _section(lines, r"^\d\)\s*Available-for-sale securities sold")
    ex_sold(sec, "ASALESECYEAR", out, "Available-for-sale securities sold")
    _, sec = _section(lines, r"^\d\)\s*Breakdown by Asset Composition")
    ex_breakdown(sec, out, "Breakdown by Asset Composition")
    _, sec = _section(lines, r"^\d\)\s*Overseas Loans and Investments by Geographic Area")
    ex_geo(sec, out, "Overseas Loans and Investments by Geographic Area")
    _, sec = _section(lines, r"^\d\)\s*Composition of Foreign-Currency-Denominated Assets by Currency")
    ex_amount_table(sec, "COMFORCUR", CURRENCY, out, "Composition of Foreign-Currency-Denominated Assets by Currency", skip=())
    _, sec = _section(lines, r"^\d\)\s*Assets Held-to-Maturity in Trust")
    ex_trust(sec, out, "Assets Held-to-Maturity in Trust / ... / Other Money Held in Trust")
    _, sec = _section(lines, r"^\d\)\s*Currency Composition of Money Held in Trust")
    ex_amount_table(sec, "CURCOMMON", TRUSTCUR, out, "Currency Composition of Money Held in Trust")
    return out


# ---------------------------------------------------------------- output
def map_to_output(file_path, existing_path=None):
    """DATA frame: row 0 codes, row 1 descriptions, one row per year found in the report."""
    vals = extract(file_path)
    codes = COLUMN_HEADERS["codes"][1:]
    descs = COLUMN_HEADERS["descriptions"][1:]
    extra = sorted({c for c, _ in vals} - set(codes))
    for c in extra:
        UNKNOWN.append(("no code in headers.json", c, None))
    years = sorted({y for _, y in vals})
    data = [[y] + [vals.get((c, y)) for c in codes] for y in years]
    df = pd.DataFrame([[None] + codes, [None] + descs] + data)
    print(f"[mapper] {len(vals)} values, {len(codes)} series, years {years}, "
          f"{sum(1 for c in codes if any((c, y) in vals for y in years))} series with data, {len(UNKNOWN)} unmatched")
    return df


def build_metadata_rows(info=None, initial=False):
    from scraper import PAGE_URL
    rows = []
    for code, desc in zip(COLUMN_HEADERS["codes"][1:], COLUMN_HEADERS["descriptions"][1:]):
        row = {"CODE": code, "DESCRIPTION": desc, "FREQUENCY": "Annual", "UNIT": "Millions of Yen"
               if ".USD." not in code or not code.startswith(("PICAD.POLRESYEAR", "PICAD.ASALESECYEAR"))
               else "Millions of U.S. Dollars",
               "SOURCE_NAME": "Japan Post Insurance - JPI", "SOURCE_URL": PAGE_URL, "DATASET": "PICAD",
               "NEXT_RELEASE_DATE": ""}
        if initial and info and info.get("created"):
            row["LAST_RELEASE_DATE"] = f"{info['created'].isoformat()}T11:00:00"
        rows.append(row)
    return rows
