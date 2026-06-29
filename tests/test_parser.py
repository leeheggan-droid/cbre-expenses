"""Unit tests for parse_statement (PDF-text + CSV parsing).

Run with pytest, or standalone:  python tests/test_parser.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import parse_statement as P  # noqa: E402

_SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "samples")


def test_parse_pdf_text_hsbc():
    # Synthetic HSBC-style card statement text: one real overseas transaction with an
    # ORIGINAL TRANSACTION AMOUNT + OVERSEAS TRANSACTION FEE follow-on, plus a balance
    # line and a payment line that must both be skipped.
    text = "\n".join([
        "16/04/26 9844 Some Merchant $378.52",
        "ORIGINAL TRANSACTION AMOUNT HKD 2,109.40",
        "OVERSEAS TRANSACTION FEE $11.36",
        "21/04/26 OPENING BALANCE $9,798.99",
        "29/04/26 9844 HSBC BANK PAYMENT -$3,000.00",
    ])
    lines = P.parse_pdf_text(text, "AUD")

    # Only the one genuine purchase survives (balance + payment skipped).
    assert len(lines) == 1, f"expected 1 transaction, got {len(lines)}"
    ln = lines[0]
    assert ln.merchant == "Some Merchant"
    assert ln.date == "16/04/2026"
    # FX fee folded into the line amount: 378.52 + 11.36 == 389.88
    assert ln.amount == 389.88, f"expected 389.88, got {ln.amount}"
    assert ln.fxFee == 11.36
    # Foreign origin recorded from the ORIGINAL TRANSACTION AMOUNT follow-on line.
    assert ln.foreignOrigin == "HKD"
    assert ln.currency == "AUD"


def test_parse_csv_sample():
    path = os.path.join(_SAMPLES, "bank-sample.csv")
    lines = P.parse_csv(path, None, "AUD")

    # Seven data rows, all non-zero amounts -> seven lines.
    assert len(lines) == 7, f"expected 7 lines, got {len(lines)}"

    by_merchant = {ln.merchant: ln for ln in lines}
    # Known merchant/amount: the Hilton Sydney row at 320.00 AUD.
    assert "HILTON HOTEL SYDNEY" in by_merchant
    assert by_merchant["HILTON HOTEL SYDNEY"].amount == 320.00
    assert by_merchant["HILTON HOTEL SYDNEY"].currency == "AUD"
    # IDR foreign row keeps its currency and comma-parsed amount.
    assert by_merchant["WARUNG MAKAN BALI"].amount == 1250000.00
    assert by_merchant["WARUNG MAKAN BALI"].currency == "IDR"


def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")


if __name__ == "__main__":
    _run_standalone()
