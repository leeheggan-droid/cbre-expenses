"""
attendees - the per-meal attendee interview step.

CBRE client meals/drinks must record who attended (and get a 50/50 529200/529300 split). For each
meal/drink line that needs attendees, the operator answers: how many people, how many CBRE, how many
client, and their names in "Surname,First" format with each person's organisation.

  python tools/attendees.py list  classified.json
  python tools/attendees.py apply classified.json --answers answers.json --out approved.json

answers.json shape (keyed by line id):
  { "L034": { "attendees": [
        {"name": "Smith,Pat",   "org": "CBRE"},
        {"name": "Jones,Alex",  "org": "AcmeCorp"},
        {"name": "Doe,Jane",    "org": "AcmeCorp"}
  ] } }
Anyone whose org is not "CBRE" counts as a client -> the line becomes a client meal (attendees + split).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbre_lib import ACCT_CLIENT, ACCT_EMPLOYEE, dump_json, load_json  # noqa: E402

CBRE_ORG = "CBRE"


def _needs_attendees(ln: dict) -> bool:
    p = ln.get("proposed") or {}
    if p.get("needsAttendees"):
        return True
    # receipt-only meal/drink lines that were never auto-typed
    return (ln.get("type") or "").lower() in ("meal", "drinks", "meal+drinks")


def meals_needing_attendees(data: dict) -> list[dict]:
    return [ln for ln in data["lines"]
            if ln.get("claimGuess") != "personal" and _needs_attendees(ln)]


def cmd_list(data: dict) -> None:
    ms = meals_needing_attendees(data)
    if not ms:
        print("No meals/drinks need attendees.")
        return
    print(f"{len(ms)} meal/drink line(s) need attendees. For EACH line ask the operator:")
    print("  - how many people total?  how many CBRE?  how many client?")
    print("  - each person's name in 'Surname,First' format and their organisation (CBRE or client co).")
    print("-" * 84)
    for ln in ms:
        print(f"{ln['id']:<6}{(ln.get('date') or '??'):<12}{(ln.get('merchant') or '')[:36]:<37}"
              f"{ln.get('amount', 0):>10,.2f} {ln.get('currency', '')}")
    print("-" * 84)
    print("Build answers.json keyed by line id, then: attendees.py apply <classified.json> --answers answers.json")


def apply_answers(data: dict, answers: dict) -> int:
    applied = 0
    for ln in data["lines"]:
        a = answers.get(ln["id"])
        if not a:
            continue
        atts = a.get("attendees", [])
        people = [{"name": p["name"],
                   "company": (p.get("org") or p.get("company") or ""),
                   "title": p.get("title", "")} for p in atts]
        clients = [p for p in people if (p["company"] or "").upper() != CBRE_ORG]
        prop = ln.setdefault("proposed", {})
        prop["attendees"] = people
        prop["needsAttendees"] = True
        prop["isClientMeal"] = bool(clients)
        prop["split"] = bool(clients)
        if clients:
            prop["splitAccounts"] = [ACCT_EMPLOYEE, ACCT_CLIENT]
        ln.setdefault("flags", []).append(
            f"attendees set: {len(people)} total, {len(people) - len(clients)} CBRE, {len(clients)} client"
            + (" -> client meal, 50/50 split" if clients else ""))
        applied += 1
    return applied


def main() -> None:
    ap = argparse.ArgumentParser(description="Per-meal attendee interview step.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list", help="show meals/drinks needing attendees")
    pl.add_argument("classified")
    pa = sub.add_parser("apply", help="apply an answers file to populate attendees + split")
    pa.add_argument("classified")
    pa.add_argument("--answers", required=True)
    pa.add_argument("--out", help="output JSON (default: stdout)")
    args = ap.parse_args()

    data = load_json(args.classified)
    if isinstance(data, list):
        data = {"lines": data}

    if args.cmd == "list":
        cmd_list(data)
        return

    answers = load_json(args.answers)
    n = apply_answers(data, answers)
    if args.out:
        dump_json(data, args.out)
        print(f"Applied attendees to {n} line(s) -> {args.out}")
    else:
        import json
        print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
