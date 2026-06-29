"""
run_pipeline - one-shot offline pipeline (the "hard way", no PeopleSoft):
parse statement -> reconcile (receipts/wallet) -> classify (triage) -> preview (GATE 1).
Writes lines/reconciled/classified/approved.json into the run dir and prints the review table.

  python tools/run_pipeline.py --statement personal/runs/<run>/statement.pdf \
      --run-config personal/runs/<run>/run-config.json \
      --roster personal/attendees.json --triage personal/triage.json \
      --receipts personal/runs/<run>/receipts.json --outdir personal/runs/<run>
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbre_lib import dump_json, load_json  # noqa: E402
import parse_statement as ps  # noqa: E402
import reconcile as rec  # noqa: E402
import classify as clf  # noqa: E402
import preview as pv  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline pipeline: parse -> reconcile -> classify -> preview.")
    ap.add_argument("--statement", required=True, help="bank statement .csv or .pdf")
    ap.add_argument("--run-config", required=True)
    ap.add_argument("--roster")
    ap.add_argument("--triage")
    ap.add_argument("--receipts", help="receipts JSON (Claude-native extracted)")
    ap.add_argument("--wallet", help="My-Wallet items JSON")
    ap.add_argument("--bank-config", help="per-bank column mapping JSON")
    ap.add_argument("--default-ccy", default="AUD")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    j = lambda name: os.path.join(args.outdir, name)  # noqa: E731

    # 1. parse
    override = None
    if args.bank_config and os.path.exists(args.bank_config):
        override = load_json(args.bank_config).get("columns")
    ext = os.path.splitext(args.statement)[1].lower()
    if ext == ".csv":
        lines = ps.parse_csv(args.statement, override, args.default_ccy)
    elif ext == ".pdf":
        lines = ps.parse_pdf(args.statement, override, args.default_ccy)
    else:
        raise SystemExit("statement must be .csv or .pdf")
    line_dicts = [ln.to_dict() for ln in lines]
    dump_json(line_dicts, j("lines.json"))

    # 2. receipts + reconcile (promotes receipt-only items to claimable candidate lines)
    receipts = []
    if args.receipts and os.path.exists(args.receipts):
        rj = load_json(args.receipts)
        receipts = rj.get("receipts", []) if isinstance(rj, dict) else rj
    wallet = load_json(args.wallet) if args.wallet and os.path.exists(args.wallet) else []
    recon = rec.reconcile(line_dicts, receipts, wallet)
    dump_json(recon, j("reconciled.json"))

    # 3. classify (triage business/personal + propose types/attendees/split)
    run_config = load_json(args.run_config)
    roster = load_json(args.roster) if args.roster and os.path.exists(args.roster) else None
    if roster:
        roster = {k: v for k, v in roster.items() if not k.startswith("_")}
    triage_cfg = load_json(args.triage) if args.triage and os.path.exists(args.triage) else None
    clines = [clf._line_from_dict(d) for d in recon["lines"]]
    windows = clf.classify(clines, run_config, roster, triage_cfg)
    out = {
        "runConfig": run_config,
        "tripWindows": [[s.strftime("%d/%m/%Y"), e.strftime("%d/%m/%Y")] for s, e in windows],
        "summary": clf.summarize(clines),
        "lines": [ln.to_dict() for ln in clines],
    }
    dump_json(out, j("classified.json"))

    # 4. preview (GATE 1) + approved plan
    print(pv.render(out))
    dump_json(out, j("approved.json"))
    print(f"\nWrote lines/reconciled/classified/approved.json to {args.outdir}")
    print("Next: run the attendee interview for flagged meals, then drive PeopleSoft via the skill (GATE 2).")


if __name__ == "__main__":
    main()
