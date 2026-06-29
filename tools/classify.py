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
from cbre_lib import Line, build_proposed, dump_json, load_json, triage  # noqa: E402


def _line_from_dict(d: dict) -> Line:
    ln = Line(
        id=d["id"], date=d.get("date"), merchant=d.get("merchant", ""),
        description=d.get("description", ""), amount=d.get("amount", 0.0),
        currency=d.get("currency", "AUD"), source=d.get("source", "bank"),
        fxFee=d.get("fxFee", 0.0), foreignOrigin=d.get("foreignOrigin"),
        claimGuess=d.get("claimGuess"),
        receiptMatch=d.get("receiptMatch"), flags=list(d.get("flags", [])),
    )
    return ln


def classify(lines: list[Line], run_config: dict, roster: dict | None,
             triage_cfg: dict | None = None) -> list[tuple]:
    """Triage business/personal, then propose a type for everything that isn't personal.
    Returns the detected trip windows."""
    triage_cfg = triage_cfg or {}
    windows = triage(lines, triage_cfg.get("personalMerchants"), triage_cfg.get("businessMerchants"))
    client_key = run_config.get("clientKey")
    has_client_roster = bool(roster and client_key and client_key in roster)
    if client_key and not has_client_roster and lines:
        lines[0].flags.append(
            f"run-config clientKey '{client_key}' not found in roster - meals proposed without attendees")
    for ln in lines:
        if ln.claimGuess == "personal":
            continue  # excluded from the claim; no expense type proposed
        ln.proposed = build_proposed(ln, has_client_roster, roster, client_key)
        if ln.receiptMatch is None:
            ln.flags.append("no receipt match (secondary source) - primary bank line still valid")
    return windows


def summarize(lines: list[Line]) -> dict:
    totals = {"business": 0.0, "personal": 0.0, "uncertain": 0.0}
    counts = {"business": 0, "personal": 0, "uncertain": 0}
    by_type: dict[str, int] = {}
    for ln in lines:
        k = ln.claimGuess or "uncertain"
        totals[k] = round(totals.get(k, 0.0) + ln.amount, 2)
        counts[k] = counts.get(k, 0) + 1
        if k != "personal" and ln.proposed.typeCode:
            by_type[ln.proposed.typeCode] = by_type.get(ln.proposed.typeCode, 0) + 1
    return {
        "lineCount": len(lines),
        "counts": counts,
        "totalsAUD": totals,
        "claimTotalAUD": round(totals["business"] + totals["uncertain"], 2),
        "byType": by_type,
        "flaggedLines": sum(1 for ln in lines if ln.flags and ln.claimGuess != "personal"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Classify normalized lines per CBRE rules (propose-only).")
    ap.add_argument("lines", help="normalized lines JSON (from parse_statement.py)")
    ap.add_argument("--run-config", required=True, help="run-config JSON")
    ap.add_argument("--roster", help="attendee roster JSON (gitignored personal/attendees.json)")
    ap.add_argument("--triage", help="per-user triage overrides JSON (gitignored personal/triage.json)")
    ap.add_argument("--out", help="output JSON path (default: stdout)")
    args = ap.parse_args()

    raw = load_json(args.lines)
    lines = [_line_from_dict(d) for d in raw]
    run_config = load_json(args.run_config)
    roster = load_json(args.roster) if args.roster and os.path.exists(args.roster) else None
    if roster:
        roster = {k: v for k, v in roster.items() if not k.startswith("_")}  # drop _comment
    triage_cfg = load_json(args.triage) if args.triage and os.path.exists(args.triage) else None

    windows = classify(lines, run_config, roster, triage_cfg)
    out = {
        "runConfig": run_config,
        "tripWindows": [[s.strftime("%d/%m/%Y"), e.strftime("%d/%m/%Y")] for s, e in windows],
        "summary": summarize(lines),
        "lines": [ln.to_dict() for ln in lines],
    }
    if args.out:
        dump_json(out, args.out)
        s = out["summary"]
        print(f"Triaged {s['lineCount']} lines: {s['counts']} | "
              f"claimable total AUD {s['claimTotalAUD']:,.2f} | trips {out['tripWindows']} -> {args.out}")
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
