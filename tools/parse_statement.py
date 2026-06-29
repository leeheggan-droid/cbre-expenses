"""
parse_statement — turn a bank statement (CSV or PDF) into normalized expense lines.

Bank-agnostic: auto-detects common column names, overridable with a per-bank config
(see samples/bank-config.example.json). PDF parsing uses pdfplumber tables when available.

Usage:
    python tools/parse_statement.py <statement.csv|.pdf> [--config bank.json] [--out lines.json]

Output: a JSON list of normalized lines (proposed/flags left for classify.py to fill).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbre_lib import Line, parse_amount, parse_date, dump_json  # noqa: E402

# Column-name aliases for auto-detection (lowercased, punctuation-insensitive match).
COLUMN_ALIASES = {
    "date":        ["date", "transaction date", "trans date", "posting date", "value date", "txn date"],
    "description": ["description", "narrative", "details", "transaction details", "particulars", "memo", "reference"],
    "merchant":    ["merchant", "payee", "name", "merchant name", "vendor"],
    "amount":      ["amount", "debit", "value", "transaction amount", "amount (aud)", "withdrawal", "money out"],
    "currency":    ["currency", "ccy", "foreign currency", "original currency"],
}


def _norm(h: str) -> str:
    return "".join(ch for ch in h.lower().strip() if ch.isalnum() or ch == " ").strip()


def _detect_columns(headers: list[str], override: dict | None) -> dict:
    """Map our canonical fields -> the statement's actual header for each, using aliases."""
    override = override or {}
    normalized = {_norm(h): h for h in headers}
    mapping: dict[str, str | None] = {}
    for field, aliases in COLUMN_ALIASES.items():
        if field in override and override[field] in headers:
            mapping[field] = override[field]
            continue
        mapping[field] = next((normalized[_norm(a)] for a in aliases if _norm(a) in normalized), None)
    return mapping


def _row_to_line(idx: int, row: dict, cols: dict, default_ccy: str) -> Line | None:
    raw_amount = row.get(cols["amount"]) if cols["amount"] else None
    amount = parse_amount(raw_amount)
    if amount == 0.0:
        return None  # skip blank/zero rows (headers, balance lines, etc.)

    desc = (row.get(cols["description"]) or "").strip() if cols["description"] else ""
    merchant = (row.get(cols["merchant"]) or "").strip() if cols["merchant"] else ""
    if not merchant:
        # Many statements have only a narrative; use it as the merchant too.
        merchant = desc.split("  ")[0][:60] if desc else "UNKNOWN"

    ccy = (row.get(cols["currency"]) or "").strip().upper() if cols["currency"] else ""
    line = Line(
        id=f"L{idx:03d}",
        date=parse_date(row.get(cols["date"])) if cols["date"] else None,
        merchant=merchant,
        description=desc,
        amount=abs(amount),                 # expenses are positive claim amounts
        currency=ccy or default_ccy,
        source="bank",
    )
    if line.date is None and cols["date"]:
        line.flags.append(f"unparseable date: {row.get(cols['date'])!r} — fix in preview")
    return line


def parse_csv(path: str, override: dict | None, default_ccy: str) -> list[Line]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        cols = _detect_columns(headers, override)
        if not cols["amount"]:
            raise SystemExit(f"Could not find an amount column in headers: {headers}\n"
                             f"Pass --config with an explicit mapping.")
        lines = []
        for i, row in enumerate(reader, start=1):
            line = _row_to_line(i, row, cols, default_ccy)
            if line:
                lines.append(line)
    return lines


def parse_pdf(path: str, override: dict | None, default_ccy: str) -> list[Line]:
    try:
        import pdfplumber
    except ImportError:
        raise SystemExit("pdfplumber not installed. Run: pip install pdfplumber")
    rows: list[dict] = []
    headers: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table or len(table) < 2:
                    continue
                if not headers:
                    headers = [(c or "").strip() for c in table[0]]
                for r in table[1:]:
                    rows.append({headers[j]: (r[j] or "") for j in range(min(len(headers), len(r)))})
    if not rows:
        raise SystemExit("No tables extracted from PDF. A text-regex profile may be needed for this bank.")
    cols = _detect_columns(headers, override)
    lines = []
    for i, row in enumerate(rows, start=1):
        line = _row_to_line(i, row, cols, default_ccy)
        if line:
            lines.append(line)
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse a bank statement into normalized expense lines.")
    ap.add_argument("statement", help="path to .csv or .pdf statement")
    ap.add_argument("--config", help="per-bank column-mapping JSON (optional)")
    ap.add_argument("--default-ccy", default="AUD", help="currency to assume when none in the statement")
    ap.add_argument("--out", help="output JSON path (default: stdout)")
    args = ap.parse_args()

    override = json.load(open(args.config, encoding="utf-8")).get("columns") if args.config else None
    ext = os.path.splitext(args.statement)[1].lower()
    if ext == ".csv":
        lines = parse_csv(args.statement, override, args.default_ccy)
    elif ext == ".pdf":
        lines = parse_pdf(args.statement, override, args.default_ccy)
    else:
        raise SystemExit(f"Unsupported file type: {ext} (use .csv or .pdf)")

    out = [ln.to_dict() for ln in lines]
    if args.out:
        dump_json(out, args.out)
        print(f"Parsed {len(out)} lines -> {args.out}")
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
