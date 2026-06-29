"""Unit tests for cbre_lib money/date parsing, the 50/50 split, and merchant classification.

Run with pytest, or standalone:  python tests/test_cbre_lib.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import cbre_lib as L  # noqa: E402


def test_parse_amount():
    assert L.parse_amount("2,000.00") == 2000.0          # RUNBOOK §5 comma gotcha
    assert L.parse_amount("$1,234.56") == 1234.56
    assert L.parse_amount("(12.50)") == -12.50           # parenthesised negative
    assert L.parse_amount("12.50 AUD") == 12.50
    assert L.parse_amount("1,250,000.00") == 1250000.0
    assert L.parse_amount("") == 0.0
    assert L.parse_amount(None) == 0.0


def test_halves():
    assert L.halves(34.51) == (17.26, 17.25)
    assert round(sum(L.halves(34.51)), 2) == 34.51
    assert L.halves(100.00) == (50.00, 50.00)
    assert round(sum(L.halves(0.01)), 2) == 0.01


def test_parse_date():
    assert L.parse_date("05/06/2026") == "05/06/2026"
    assert L.parse_date("2026-06-05") == "05/06/2026"    # ISO -> DD/MM/YYYY
    assert L.parse_date("5 Jun 2026") == "05/06/2026"
    assert L.parse_date("garbage") is None
    assert L.parse_date("") is None


def test_classify_merchant():
    assert L.classify_merchant("UBER *TRIP", "", False, True)[0] == "TAXIBU"
    assert L.classify_merchant("GRAB *RIDE JAKARTA", "", True, True)[0] == "TAXIINT"
    assert L.classify_merchant("THE HARBOUR RESTAURANT", "", False, True)[0] == "MEALCLI"
    assert L.classify_merchant("WARUNG MAKAN", "", True, True)[0] == "MEALINC"
    assert L.classify_merchant("THE HARBOUR RESTAURANT", "", False, False)[0] == "SUBSIST"
    assert L.classify_merchant("HILTON HOTEL", "", False, True)[0] == "ACCDOM"
    code, flags = L.classify_merchant("ACME HARDWARE STORE", "", False, True)
    assert code == "TRAVOTH" and flags  # unknown -> flagged


def test_build_proposed_client_meal_split():
    ln = L.Line(id="L1", date="05/06/2026", merchant="THE HARBOUR RESTAURANT",
                description="", amount=142.0, currency="AUD")
    roster = {"AcmeCorp": [{"name": "Smith,John", "company": "AcmeCorp", "title": "Director"}]}
    p = L.build_proposed(ln, True, roster, "AcmeCorp")
    assert p.typeCode == "MEALCLI"
    assert p.split is True
    assert p.splitAccounts == [L.ACCT_EMPLOYEE, L.ACCT_CLIENT]
    assert p.needsAttendees is True
    assert len(p.attendees) == 1


def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")


if __name__ == "__main__":
    _run_standalone()
