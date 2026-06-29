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
import re
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
    full_text_parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            full_text_parts.append(page.extract_text() or "")
            for table in page.extract_tables() or []:
                if not table or len(table) < 2:
                    continue
                if not headers:
                    headers = [(c or "").strip() for c in table[0]]
                for r in table[1:]:
                    rows.append({headers[j]: (r[j] or "") for j in range(min(len(headers), len(r)))})

    lines: list[Line] = []
    if rows:
        cols = _detect_columns(headers, override)
        for i, row in enumerate(rows, start=1):
            line = _row_to_line(i, row, cols, default_ccy)
            if line:
                lines.append(line)

    # Fall back to the text-regex parser (handles statements with no real tables, e.g. HSBC).
    if not lines:
        lines = parse_pdf_text("\n".join(full_text_parts), default_ccy)
    # Fall back to the coordinate/column parser (paid-out/paid-in/balance layouts, e.g. UK bank accounts).
    if not lines:
        lines = parse_pdf_columns(path, default_ccy)
    if not lines:
        raise SystemExit("Could not extract transactions from this PDF (no tables, no recognised text rows, "
                         "no paid-out/paid-in columns). The statement may need a custom profile.")
    return lines


# Text-regex statement parser: "DD/MM/YY  <card>  <merchant>  $amount" with optional
# "ORIGINAL TRANSACTION AMOUNT <CCY> <amt>" / "OVERSEAS TRANSACTION FEE $fee" follow-on lines.
_TXN_RE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{4})\s+(.+?)\s+(-?\$[\d,]+\.\d{2})\s*$")
_ORIG_RE = re.compile(r"ORIGINAL TRANSACTION AMOUNT\s+([A-Z]{3})\s+([\d,]+\.\d{2})", re.I)
_FEE_RE = re.compile(r"OVERSEAS TRANSACTION FEE\s+\$?([\d,]+\.\d{2})", re.I)
_SKIP_RE = re.compile(r"OPENING BALANCE|CLOSING BALANCE|BANK PAYMENT|PAYMENT RECEIVED|MINIMUM PAYMENT", re.I)


def parse_pdf_text(full_text: str, default_ccy: str) -> list[Line]:
    lines: list[Line] = []
    current: Line | None = None
    idx = 0
    for raw in full_text.splitlines():
        s = raw.strip()
        m = _TXN_RE.match(s)
        if m:
            date_s, _card, detail, amt_s = m.groups()
            amount = parse_amount(amt_s)
            if amount <= 0 or _SKIP_RE.search(detail):   # skip payments/credits/balances
                current = None
                continue
            idx += 1
            current = Line(
                id=f"L{idx:03d}", date=parse_date(date_s), merchant=detail.strip(),
                description=detail.strip(), amount=amount, currency=default_ccy, source="bank",
            )
            if current.date is None:
                current.flags.append(f"unparseable date: {date_s!r} - fix in preview")
            lines.append(current)
            continue
        if current:
            mo = _ORIG_RE.search(s)
            if mo:
                # foreign-origin but already charged in AUD on the card -> keep currency AUD, record origin
                current.foreignOrigin = mo.group(1).upper()
                current.flags.append(f"foreign origin {mo.group(1)} {mo.group(2)} (charged in AUD on card)")
                continue
            mf = _FEE_RE.search(s)
            if mf:
                # fold the overseas FX fee into the line amount (claim the true card cost)
                fee = parse_amount(mf.group(1))
                current.fxFee = fee
                current.amount = round(current.amount + fee, 2)
                current.flags.append(f"incl overseas FX fee ${fee:.2f}")
    return lines


# Coordinate/column parser for bank-account PDFs with paid-out / paid-in / balance columns
# (e.g. UK first direct). Uses word x-positions to bucket amounts into the right column, so
# only debits (paid out) become expense lines; credits and the running balance are ignored.
_NUM_RE = re.compile(r"^-?[\d,]+\.\d{2}$")
_MONTHS = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}


def parse_pdf_columns(path: str, default_ccy: str) -> list[Line]:
    import pdfplumber
    out: list[Line] = []
    current_date = None
    last: Line | None = None
    idx = 0
    cols = None  # persist column geometry across pages (the header only prints on page 1)
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            rows: dict = {}
            for w in page.extract_words():
                rows.setdefault(round(w["top"]), []).append(w)
            header_top = -1
            for top in sorted(rows):
                t = [w["text"].lower() for w in rows[top]]
                if "paid" in t and "balance" in t and ("out" in t or "in" in t):
                    paids = [w for w in sorted(rows[top], key=lambda x: x["x0"]) if w["text"].lower() == "paid"]
                    bal = [w for w in rows[top] if w["text"].lower() == "balance"][0]
                    cols = {"paid_out": paids[0]["x0"],
                            "paid_in": paids[1]["x0"] if len(paids) > 1 else 409.0,
                            "balance": bal["x0"]}
                    header_top = top
                    break
            if not cols:
                continue
            b_oi = (cols["paid_out"] + cols["paid_in"]) / 2   # paid-out | paid-in boundary
            b_ib = (cols["paid_in"] + cols["balance"]) / 2    # paid-in | balance boundary
            for top in sorted(rows):
                if top <= header_top:
                    continue
                rw = sorted(rows[top], key=lambda x: x["x0"])
                body = rw
                if len(rw) >= 3 and re.match(r"^\d{1,2}$", rw[0]["text"]) and rw[1]["text"].lower()[:3] in _MONTHS:
                    d = parse_date(f"{rw[0]['text']} {rw[1]['text'][:3]} {rw[2]['text']}")
                    if d:
                        current_date = d
                    body = rw[3:]
                paid_out = None
                had_amount = False
                details: list[str] = []
                for w in body:
                    txt = w["text"]
                    if _NUM_RE.match(txt):
                        had_amount = True
                        if w["x0"] >= b_ib:
                            pass                          # balance column - ignore
                        elif w["x0"] >= b_oi:
                            pass                          # paid in (credit) - ignore
                        else:
                            paid_out = parse_amount(txt)  # paid out (debit) - an expense
                    elif txt == "D":
                        pass                              # overdrawn marker
                    else:
                        details.append(txt)
                detail = " ".join(details).strip()
                if "http" in detail.lower() or detail.lower().startswith("page"):
                    continue                              # footer noise
                if paid_out and paid_out > 0:
                    idx += 1
                    last = Line(id=f"L{idx:03d}", date=current_date, merchant=detail[:60],
                                description=detail, amount=paid_out, currency=default_ccy, source="bank")
                    out.append(last)
                elif not had_amount and detail and last is not None and len(last.merchant) < 40:
                    last.merchant = (last.merchant + " " + detail).strip()[:60]   # text overflow only
    return out


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
