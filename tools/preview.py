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


def _row(ln: dict) -> str:
    p = ln.get("proposed", {})
    att = str(len(p.get("attendees", []))) if p.get("needsAttendees") else "-"
    split = "50/50" if p.get("split") else "-"
    rcpt = "Y" if ln.get("receiptMatch") else "-"
    return (
        f"{ln['id']:<5}{(ln.get('date') or '??'):<12}{_clip(ln.get('merchant',''),27):<28}"
        f"{ln.get('amount',0):>10,.2f} {(p.get('typeCode') or '-'):<9}{att:<4}{split:<6}{rcpt:<5}"
    )


def render(data: dict) -> str:
    lines = data["lines"]
    rc = data.get("runConfig", {})
    groups = {"business": [], "uncertain": [], "personal": []}
    for ln in lines:
        groups.get(ln.get("claimGuess") or "uncertain", groups["uncertain"]).append(ln)

    out: list[str] = []
    out.append("=" * 96)
    out.append("GATE 1 - PRE-ENTRY REVIEW   (confirm personal vs business; nothing is entered until you approve)")
    out.append("=" * 96)
    if data.get("tripWindows"):
        out.append("Detected trip windows: " + ", ".join(f"{a}..{b}" for a, b in data["tripWindows"]))
    if rc:
        out.append(f"Client: {rc.get('clientKey','-')}   Location: {rc.get('defaultLocation','-')}   "
                   f"Purpose: {rc.get('businessPurpose','-')}")
    hdr = f"{'#':<5}{'DATE':<12}{'MERCHANT':<28}{'AMOUNT':>10} {'TYPE':<9}{'ATT':<4}{'SPLIT':<6}{'RCPT':<5}"

    for key, title in [("business", "BUSINESS - proposed to CLAIM"),
                       ("uncertain", "UNCERTAIN - please decide (claim or drop?)"),
                       ("personal", "PERSONAL - excluded (not claimed)")]:
        g = groups[key]
        sub = round(sum(x.get("amount", 0) for x in g), 2)
        out.append("")
        out.append(f"--- {title}   [{len(g)} lines, AUD {sub:,.2f}] " + "-" * 20)
        if not g:
            out.append("  (none)")
            continue
        if key == "personal":
            for ln in g:   # compact: personal items don't need the full grid
                out.append(f"  {ln['id']} {(ln.get('date') or '??'):<11}{_clip(ln.get('merchant',''),34):<35}{ln.get('amount',0):>9,.2f}")
            continue
        out.append(hdr)
        for ln in g:
            out.append(_row(ln))

    # flags for claimable lines
    flagged = [(ln["id"], ln["flags"]) for ln in lines
               if ln.get("flags") and (ln.get("claimGuess") != "personal")]
    if flagged:
        out.append("")
        out.append("FLAGS (claimable lines):")
        for lid, fl in flagged:
            for f in fl:
                out.append(f"  {lid}: {f}")

    s = data.get("summary", {})
    t = s.get("totalsAUD", {})
    out.append("=" * 96)
    out.append(f"CLAIMABLE (business+uncertain): AUD {s.get('claimTotalAUD', 0):,.2f}   "
               f"[business {t.get('business',0):,.2f} | uncertain {t.get('uncertain',0):,.2f} | "
               f"personal excluded {t.get('personal',0):,.2f}]")
    out.append(f"by type: {s.get('byType', {})}")
    out.append("Confirm the UNCERTAIN lines and any flagged meals (attendees + 50/50 split) before approval.")
    out.append("Govt Exp = No on every line. Tool STOPS at Summary-and-Submit - you submit.")
    out.append("=" * 96)
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
