"""
classify — propose an expense type, attendees, client-meal split and currency for each line.

Applies the CBRE rules from cbre_lib (which mirror RUNBOOK.md). Everything here is a
*proposal*: the user confirms/edits at GATE 1 (preview.py) before anything is entered.

Usage:
    python tools/classify.py lines.json --run-config run.json [--roster personal/attendees.json] [--out classified.json]

run-config.json (example in samples/run-config.example.json):
    { "clientKey": "AcmeCorp", "defaultLocation": "363 George St-SYD",
      "businessPurpose": "Client-Business Meeting", "reportDescription": "Site visit" }
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbre_lib import Line, Proposed, build_proposed, dump_json, load_json  # noqa: E402


def _line_from_dict(d: dict) -> Line:
    ln = Line(
        id=d["id"], date=d.get("date"), merchant=d.get("merchant", ""),
        description=d.get("description", ""), amount=d.get("amount", 0.0),
        currency=d.get("currency", "AUD"), source=d.get("source", "bank"),
        receiptMatch=d.get("receiptMatch"), flags=list(d.get("flags", [])),
    )
    return ln


def classify(lines: list[Line], run_config: dict, roster: dict | None) -> list[Line]:
    client_key = run_config.get("clientKey")
    has_client_roster = bool(roster and client_key and client_key in roster)
    if client_key and not has_client_roster:
        # warn once via a report-level flag on the first line
        if lines:
            lines[0].flags.append(
                f"run-config clientKey '{client_key}' not found in roster - meals proposed without attendees")
    for ln in lines:
        ln.proposed = build_proposed(ln, has_client_roster, roster, client_key)
        if ln.receiptMatch is None:
            ln.flags.append("no receipt match (secondary source) - primary bank line still valid")
    return lines


def summarize(lines: list[Line]) -> dict:
    # Never sum across currencies — foreign lines are converted to AUD by PeopleSoft at entry.
    total_by_ccy: dict[str, float] = {}
    by_type: dict[str, int] = {}
    for ln in lines:
        ccy = (ln.currency or "AUD").upper()
        total_by_ccy[ccy] = round(total_by_ccy.get(ccy, 0.0) + ln.amount, 2)
        by_type[ln.proposed.typeCode] = by_type.get(ln.proposed.typeCode, 0) + 1
    return {
        "lineCount": len(lines),
        "totalByCurrency": total_by_ccy,
        "foreignLines": sum(1 for ln in lines if (ln.currency or "AUD").upper() != "AUD"),
        "byType": by_type,
        "flaggedLines": sum(1 for ln in lines if ln.flags),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Classify normalized lines per CBRE rules (propose-only).")
    ap.add_argument("lines", help="normalized lines JSON (from parse_statement.py)")
    ap.add_argument("--run-config", required=True, help="run-config JSON")
    ap.add_argument("--roster", help="attendee roster JSON (gitignored personal/attendees.json)")
    ap.add_argument("--out", help="output JSON path (default: stdout)")
    args = ap.parse_args()

    raw = load_json(args.lines)
    lines = [_line_from_dict(d) for d in raw]
    run_config = load_json(args.run_config)
    roster = load_json(args.roster) if args.roster and os.path.exists(args.roster) else None
    if roster:
        roster = {k: v for k, v in roster.items() if not k.startswith("_")}  # drop _comment

    classified = classify(lines, run_config, roster)
    out = {
        "runConfig": run_config,
        "summary": summarize(classified),
        "lines": [ln.to_dict() for ln in classified],
    }
    if args.out:
        dump_json(out, args.out)
        print(f"Classified {out['summary']['lineCount']} lines "
              f"(totals {out['summary']['totalByCurrency']}, {out['summary']['flaggedLines']} flagged) -> {args.out}")
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
