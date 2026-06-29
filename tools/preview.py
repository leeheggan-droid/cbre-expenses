"""
preview — render the GATE 1 table for human review before anything is entered into PeopleSoft.

Prints a readable table of every proposed line (type, amount, attendees, split, flags) plus a
summary, and writes the plan to an `approved.json` the orchestrator consumes. Review/edit that
file (or the classified JSON) before approving — NOTHING is entered until you do.

Usage:
    python tools/preview.py classified.json [--out approved.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbre_lib import dump_json, load_json  # noqa: E402


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "~"


def render(data: dict) -> str:
    lines = data["lines"]
    rc = data.get("runConfig", {})
    out: list[str] = []
    out.append("=" * 100)
    out.append("GATE 1 - PRE-ENTRY REVIEW   (nothing is entered into PeopleSoft until you approve)")
    out.append("=" * 100)
    if rc:
        out.append(f"Client: {rc.get('clientKey','-')}   Default Location: {rc.get('defaultLocation','-')}   "
                   f"Purpose: {rc.get('businessPurpose','-')}")
        out.append(f"Report: {rc.get('reportDescription','-')}")
        out.append("-" * 100)

    hdr = f"{'#':<5}{'DATE':<12}{'MERCHANT':<26}{'AMOUNT':>12} {'CCY':<5}{'TYPE':<9}{'ATT':<4}{'SPLIT':<6}{'RCPT':<5}"
    out.append(hdr)
    out.append("-" * 100)
    for ln in lines:
        p = ln.get("proposed", {})
        att = str(len(p.get("attendees", []))) if p.get("needsAttendees") else "-"
        split = "50/50" if p.get("split") else "-"
        rcpt = "Y" if ln.get("receiptMatch") else "-"
        out.append(
            f"{ln['id']:<5}{(ln.get('date') or '??'):<12}{_clip(ln.get('merchant',''),25):<26}"
            f"{ln.get('amount',0):>12,.2f} {(ln.get('currency') or ''):<5}"
            f"{(p.get('typeCode') or '?'):<9}{att:<4}{split:<6}{rcpt:<5}"
        )

    # flags block
    flagged = [(ln["id"], ln["flags"]) for ln in lines if ln.get("flags")]
    if flagged:
        out.append("-" * 100)
        out.append("FLAGS (review these):")
        for lid, fl in flagged:
            for f in fl:
                out.append(f"  {lid}: {f}")

    s = data.get("summary", {})
    totals = s.get("totalByCurrency") or {}
    totals_str = "  ".join(f"{ccy} {amt:,.2f}" for ccy, amt in totals.items()) or "n/a"
    out.append("=" * 100)
    out.append(f"TOTALS: {totals_str}   Lines: {s.get('lineCount', len(lines))}   "
               f"Foreign: {s.get('foreignLines', 0)}   Flagged: {s.get('flaggedLines', len(flagged))}")
    out.append(f"by type: {s.get('byType', {})}")
    out.append("Foreign lines convert to AUD in PeopleSoft at entry (RUNBOOK 6) - totals shown per currency.")
    out.append("Govt Exp = No on every line (CBRE rule). Tool STOPS at Summary-and-Submit - you submit.")
    out.append("=" * 100)
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render the GATE-1 review table and emit the approved plan.")
    ap.add_argument("classified", help="classified JSON (from classify.py / reconcile.py)")
    ap.add_argument("--out", help="approved plan JSON path (default: alongside input as approved.json)")
    args = ap.parse_args()

    data = load_json(args.classified)
    if isinstance(data, list):  # raw lines list -> wrap
        data = {"lines": data, "summary": {}, "runConfig": {}}
    print(render(data))

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.classified)), "approved.json")
    dump_json(data, out)
    print(f"\nPlan written to {out} - edit if needed, then approve to proceed to entry.")


if __name__ == "__main__":
    main()
