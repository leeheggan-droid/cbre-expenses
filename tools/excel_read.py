"""
excel_read — read a filled review .xlsx (from excel_template.py) back into an approved plan.

The operator's edits in Excel are mapped back onto the Line contract:
  * Claim = No        -> claimGuess "personal" (excluded from the claim)
  * ExpenseType       -> proposed.typeCode (display mapped back to its code) + typeDisplay
  * Attendees text    -> proposed.attendees [{name, company:"", title:""}]
  * Split5050 = Yes   -> proposed.split = True

Usage:
    python tools/excel_read.py review.xlsx --out approved.json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbre_lib import EXPENSE_TYPES, MEAL_TYPES_NEED_ATTENDEES, dump_json  # noqa: E402

import openpyxl  # noqa: E402

DISPLAY_TO_CODE = {v: k for k, v in EXPENSE_TYPES.items()}


def _yes(v) -> bool:
    return str(v).strip().lower() in ("yes", "y", "true", "1")


def _parse_attendees(text):
    """'Surname,First; Surname,First' -> [{name, company:'', title:''}]."""
    out = []
    for chunk in str(text or "").split(";"):
        name = chunk.strip()
        if name:
            out.append({"name": name, "company": "", "title": ""})
    return out


def _parse_flags(text):
    return [f.strip() for f in str(text or "").split(";") if f.strip()]


def _num(v):
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def read_workbook(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Review"] if "Review" in wb.sheetnames else wb.active

    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    idx = {name: i for i, name in enumerate(header)}

    def get(row, name):
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else None

    lines = []
    for row in rows:
        if get(row, "ID") in (None, ""):
            continue  # skip blank trailing rows

        claim_yes = _yes(get(row, "Claim"))
        display = (get(row, "ExpenseType") or "")
        display = str(display).strip()
        code = DISPLAY_TO_CODE.get(display)
        split = _yes(get(row, "Split5050"))
        attendees = _parse_attendees(get(row, "Attendees"))

        proposed = {
            "typeCode": code,
            "typeDisplay": display or None,
            "needsAttendees": code in MEAL_TYPES_NEED_ATTENDEES if code else False,
            "attendees": attendees,
            "split": split,
        }
        line = {
            "id": str(get(row, "ID")),
            "date": get(row, "Date"),
            "merchant": get(row, "Merchant"),
            "amount": _num(get(row, "Amount")),
            "currency": get(row, "Currency"),
            "claimGuess": "business" if claim_yes else "personal",
            "proposed": proposed,
            "flags": _parse_flags(get(row, "Notes")),
        }
        lines.append(line)
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Read a filled review .xlsx back into an approved plan JSON.")
    ap.add_argument("xlsx", help="filled review spreadsheet (from excel_template.py)")
    ap.add_argument("--out", required=True, help="output approved plan JSON path")
    args = ap.parse_args()

    lines = read_workbook(args.xlsx)
    out = {"lines": lines}
    dump_json(out, args.out)
    claimed = sum(1 for ln in lines if ln["claimGuess"] != "personal")
    print(f"Read {len(lines)} lines ({claimed} claimed) -> {args.out}")


if __name__ == "__main__":
    main()
