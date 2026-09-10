"""Each rule in presubmit_checks fails on the shape the auditor rejected, then passes once fixed."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from presubmit_checks import check_lines  # noqa: E402


def _line(**kw):
    base = {"line": "1", "date": "05/07/2026", "type": "GRNDTRN", "amount": 12.0, "currency": "AUD",
            "merchant": "Grab", "descr": "Grab - Hotel A to Office B, return from meeting",
            "attendees": [], "evidence": "e-receipt"}
    base.update(kw)
    return base


def test_taxi_needs_route_or_purpose():
    bad = _line(descr="Grab - Singapore")
    assert any("route or purpose" in f for f in check_lines([bad])[0])
    good = _line(descr="Grab - The Urban Rose Pub to Andaz Singapore (hotel), return to hotel")
    assert check_lines([good])[0] == []


def test_card_slip_is_not_a_receipt():
    bad = _line(type="MEAL100", merchant="Andaz Bar", attendees=["Heggan,Lee / CBRE"], evidence="card_slip")
    assert any("official receipt" in f for f in check_lines([bad])[0])
    good = dict(bad, evidence="tax_invoice")
    assert check_lines([good])[0] == []


def test_bar_charge_is_not_lodging():
    bad = _line(type="LODGING", merchant="ANDAZ SINGAPORE-BAR SQUAR", descr="separate bar charge", folio_fb=0)
    fails = check_lines([bad])[0]
    assert any("use a meal type" in f for f in fails)
    good = _line(type="MEAL100", merchant="ANDAZ SINGAPORE-BAR SQUAR", descr="bar", attendees=["Heggan,Lee / CBRE"])
    assert check_lines([good])[0] == []


def test_folio_with_food_must_be_split():
    bad = _line(type="LODGING", merchant="ANDAZ SG-FRONT OFFICE", descr="4-night stay, full folio", folio_fb=503.02)
    assert any("split it" in f for f in check_lines([bad])[0])
    good = dict(bad, folio_fb=0)
    assert check_lines([good])[0] == []
    unknown = dict(bad)
    del unknown["folio_fb"]
    fails, warns = check_lines([unknown])
    assert fails == [] and any("folio_fb not recorded" in w for w in warns)


def test_meal_needs_attendees():
    bad = _line(type="MEAL100", merchant="Luna Sea", descr="team dinner", attendees=[])
    assert any("no attendees" in f for f in check_lines([bad])[0])
    good = dict(bad, attendees=["Heggan,Lee / CBRE"])
    assert check_lines([good])[0] == []
