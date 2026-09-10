#!/usr/bin/env python3
"""Pre-submit checks for a PeopleSoft expense report, built from real auditor send-backs.

Run this against a DUMP of the live report (what is actually keyed in PeopleSoft), not against
the offline plan - the auditor reads the report, so the check must too. See docs/LESSONS.md for
the send-back that produced each rule, and docs/PS-DRIVER-NOTES.md for the dump snippet.

Input: a JSON file holding a list of lines, each like
  {"line": "18", "date": "05/07/2026", "type": "GRNDTRN", "amount": 12.0, "currency": "AUD",
   "merchant": "Grab", "descr": "...", "attendees": ["Surname,First / Org", ...],
   "evidence": "e-receipt" | "tax_invoice" | "folio" | "card_slip" | "statement" | "photo" | "none",
   "folio_fb": 0.0}          # optional: food & drink total inside a hotel folio, in the folio currency

Exit code 1 when any FAIL is found; 0 otherwise. Warnings never fail the run.

Usage:
  python tools/presubmit_checks.py report_dump.json
  python tools/presubmit_checks.py report_dump.json --json   # machine-readable
"""
from __future__ import annotations

import json
import re
import sys

MEAL_TYPES = {"MEAL50", "MEAL100", "MEALCLI", "MEALINT", "MEALINC", "SUBSIST", "LIGHTRE"}
LODGING_TYPES = {"LODGING", "ACCDOM", "ACCINT"}
GROUND_TYPES = {"GRNDTRN", "TAXIBU", "TAXIINT"}

# A taxi/ride description must say where it went or why. The auditor's words: "please indicate
# the destination details (start point - end point) or purpose of travels".
ROUTE_RE = re.compile(r"\b(to|->|→|from)\b|\bairport transfer\b|\btransfer\b", re.IGNORECASE)
PURPOSE_RE = re.compile(r"\b(meeting|client|office|hq|airport|hotel|dinner|site|conference|return)\b", re.IGNORECASE)

# Merchants that are food & drink even when they sit on a hotel bill.
FOOD_MERCHANT_RE = re.compile(r"\b(bar|restaurant|cafe|café|bistro|grill|kitchen|dining|lounge|pub)\b", re.IGNORECASE)

# Evidence that the auditor has already rejected as "not an official receipt/invoice".
WEAK_EVIDENCE = {"card_slip", "none", ""}


def check_lines(lines: list[dict]) -> tuple[list[str], list[str]]:
    """Return (failures, warnings) for a list of report lines."""
    fails: list[str] = []
    warns: list[str] = []
    for ln in lines:
        tag = f"line {ln.get('line', '?')} ({ln.get('type')}, {ln.get('currency')} {ln.get('amount')})"
        typ = (ln.get("type") or "").upper()
        descr = ln.get("descr") or ""
        merchant = ln.get("merchant") or ""
        evidence = (ln.get("evidence") or "").lower()

        # Rule 1 - taxi lines carry a route or a purpose (send-back 10 Sep 2026, line 18).
        if typ in GROUND_TYPES and not (ROUTE_RE.search(descr) or PURPOSE_RE.search(descr)):
            fails.append(f"{tag}: taxi description has no start-end route or purpose: {descr!r}")

        # Rule 2 - a card slip is not a receipt (send-back 10 Sep 2026, line 23).
        if evidence in WEAK_EVIDENCE:
            fails.append(f"{tag}: evidence is {evidence or 'missing'!r}; needs an official receipt/tax invoice or missing-receipt approval")

        # Rule 3 - food and drink is a meal type, never lodging (send-back 10 Sep 2026, line 23).
        if typ in LODGING_TYPES and FOOD_MERCHANT_RE.search(merchant + " " + descr):
            fails.append(f"{tag}: lodging line whose merchant/description reads as food & drink ({merchant!r}); use a meal type")

        # Rule 4 - a hotel folio with food & drink must be split (send-back 10 Sep 2026, line 24).
        if typ in LODGING_TYPES:
            fb = ln.get("folio_fb")
            if fb is None:
                warns.append(f"{tag}: folio_fb not recorded; confirm the folio holds no food & drink before submitting")
            elif float(fb) > 0:
                fails.append(f"{tag}: folio carries food & drink of {fb}; split it into a separate meal line")

        # Rule 5 - meals list their attendees (HK MEAL50/MEAL100 both require them).
        if typ in MEAL_TYPES and not ln.get("attendees"):
            fails.append(f"{tag}: meal line has no attendees recorded")

    return fails, warns


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    with open(argv[1], encoding="utf-8-sig") as fh:
        data = json.load(fh)
    lines = data["lines"] if isinstance(data, dict) else data
    fails, warns = check_lines(lines)
    if "--json" in argv:
        print(json.dumps({"fail": fails, "warn": warns}, indent=2))
    else:
        for w in warns:
            print("WARN ", w)
        for f in fails:
            print("FAIL ", f)
        print(f"{len(lines)} lines checked: {len(fails)} fail, {len(warns)} warn")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
