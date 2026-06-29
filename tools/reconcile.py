"""
reconcile — bank statement is the source of truth; receipts and My-Wallet only corroborate.

Two jobs (RUNBOOK §1.8 + the My-Wallet step in §4):
  1. Match receipts (secondary) to bank lines by amount + date proximity + fuzzy merchant.
     A receipt with no matching bank line is SURFACED, never auto-claimed.
  2. Dedupe bank lines against My-Wallet items already in PeopleSoft, so we only ADD genuine
     out-of-pocket lines and don't double-enter corporate-card items.

Usage:
    python tools/reconcile.py lines.json [--receipts receipts.json] [--wallet wallet.json] [--out reconciled.json]

receipts.json: [{ "file": "r1.jpg", "merchant": "...", "date": "DD/MM/YYYY", "amount": 12.5, "currency": "AUD" }]
wallet.json:   [{ "merchant": "...", "date": "DD/MM/YYYY", "amount": 12.5 }]  (already-in-system card items)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbre_lib import dump_json, load_json  # noqa: E402

AMOUNT_TOL = 0.02         # cents of rounding tolerance
DATE_TOL_DAYS = 3         # card post date can lag the transaction date


def _date(d: str | None):
    try:
        return datetime.strptime(d, "%d/%m/%Y") if d else None
    except (ValueError, TypeError):
        return None


def _merch_tokens(s: str) -> set[str]:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in (s or "")).split() if len(t) > 2}


def _score(line: dict, other: dict) -> float:
    """0..1 match confidence between a bank line and a receipt/wallet item."""
    if abs(line["amount"] - abs(other.get("amount", 0))) > AMOUNT_TOL:
        return 0.0
    score = 0.6  # amount matches
    ld, od = _date(line.get("date")), _date(other.get("date"))
    if ld and od:
        gap = abs((ld - od).days)
        if gap > DATE_TOL_DAYS:
            return 0.0
        score += 0.2 * (1 - gap / (DATE_TOL_DAYS + 1))
    lt, ot = _merch_tokens(line.get("merchant", "")), _merch_tokens(other.get("merchant", ""))
    if lt and ot:
        overlap = len(lt & ot) / len(lt | ot)
        score += 0.2 * overlap
    return round(min(score, 1.0), 3)


def _best_match(line: dict, candidates: list[dict]) -> tuple[int, float]:
    best_i, best_s = -1, 0.0
    for i, c in enumerate(candidates):
        s = _score(line, c)
        if s > best_s:
            best_i, best_s = i, s
    return best_i, best_s


def reconcile(lines: list[dict], receipts: list[dict], wallet: list[dict]) -> dict:
    used_receipts: set[int] = set()
    wallet_unmatched = list(range(len(wallet)))

    for ln in lines:
        # 1. receipt corroboration
        if receipts:
            i, s = _best_match(ln, receipts)
            if i >= 0 and s >= 0.6 and i not in used_receipts:
                used_receipts.add(i)
                ln["receiptMatch"] = {"file": receipts[i].get("file"), "confidence": s}

        # 2. wallet dedupe
        wi, ws = _best_match(ln, [wallet[j] for j in wallet_unmatched]) if wallet_unmatched else (-1, 0.0)
        if wi >= 0 and ws >= 0.7:
            real_idx = wallet_unmatched.pop(wi)
            ln["source"] = "wallet"
            ln.setdefault("flags", []).append(
                f"matches a My-Wallet item ({ws}) — already in PeopleSoft; do NOT re-add as out-of-pocket")

    orphan_receipts = [receipts[i] for i in range(len(receipts)) if i not in used_receipts]
    return {
        "lines": lines,
        "orphanReceipts": orphan_receipts,        # receipts with no bank line — surfaced, not claimed
        "walletNotOnStatement": [wallet[j] for j in wallet_unmatched],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Reconcile bank lines vs receipts (secondary) and My-Wallet.")
    ap.add_argument("lines", help="normalized lines JSON")
    ap.add_argument("--receipts", help="receipts JSON (secondary corroboration)")
    ap.add_argument("--wallet", help="My-Wallet items JSON (already in PeopleSoft)")
    ap.add_argument("--out", help="output JSON path (default: stdout)")
    args = ap.parse_args()

    lines = load_json(args.lines)
    if isinstance(lines, dict):       # accept classify.py output too
        lines = lines["lines"]
    receipts = load_json(args.receipts) if args.receipts and os.path.exists(args.receipts) else []
    wallet = load_json(args.wallet) if args.wallet and os.path.exists(args.wallet) else []

    result = reconcile(lines, receipts, wallet)
    matched = sum(1 for ln in result["lines"] if ln.get("receiptMatch"))
    print(f"{len(result['lines'])} lines | {matched} receipt-matched | "
          f"{len(result['orphanReceipts'])} orphan receipts | "
          f"{len(result['walletNotOnStatement'])} wallet items not on statement", file=sys.stderr)
    if args.out:
        dump_json(result, args.out)
        print(f"-> {args.out}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
