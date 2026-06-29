"""Unit tests for cbre_lib triage (business/personal) + trip-window detection.

Run with pytest, or standalone:  python tests/test_triage.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from cbre_lib import Line  # noqa: E402
import cbre_lib as L  # noqa: E402


def _trip_lines():
    """A small KL trip + some non-trip noise."""
    return [
        Line(id="L001", date="10/05/2026", merchant="GRAND HYATT KUALA LUMPUR",
             description="", amount=540.00, currency="AUD", foreignOrigin="MYR"),
        Line(id="L002", date="11/05/2026", merchant="GRAB *RIDE KL",
             description="", amount=22.00, currency="AUD", foreignOrigin="MYR"),
        Line(id="L003", date="12/05/2026", merchant="NETFLIX.COM",
             description="", amount=22.99, currency="AUD"),
        Line(id="L004", date="03/03/2026", merchant="ACME HARDWARE STORE",
             description="", amount=49.99, currency="AUD"),
    ]


def test_triage_business_vs_personal():
    lines = _trip_lines()
    L.triage(lines)
    guess = {ln.id: ln.claimGuess for ln in lines}

    # Travel-currency (MYR) lines -> business.
    assert guess["L001"] == "business", f"hotel got {guess['L001']}"
    assert guess["L002"] == "business", f"grab got {guess['L002']}"
    # Netflix -> personal (generic personal merchant).
    assert guess["L003"] == "personal", f"netflix got {guess['L003']}"


def test_trip_windows_span_myr_dates():
    lines = _trip_lines()
    windows = L.trip_windows(lines)
    assert len(windows) >= 1, "expected at least one trip window"

    start, end = windows[0]
    # Window must span the two MYR transaction dates (10 & 11 May 2026), with the +/-1 day buffer.
    from datetime import datetime
    d10 = datetime.strptime("10/05/2026", "%d/%m/%Y")
    d11 = datetime.strptime("11/05/2026", "%d/%m/%Y")
    assert start <= d10 <= end
    assert start <= d11 <= end


def test_triage_extra_personal_override():
    # A user-specific local merchant not covered by the generic PERSONAL_RE.
    def fresh():
        return [Line(id="L001", date="03/03/2026", merchant="ACME BAKERY",
                     description="", amount=8.50, currency="AUD")]

    # With the per-user override the ACME BAKERY line is marked personal.
    overridden = fresh()
    L.triage(overridden, extra_personal=["acme bakery"])
    assert overridden[0].claimGuess == "personal", f"got {overridden[0].claimGuess}"

    # The override genuinely drives the decision: a merchant the base regex does not know
    # is "uncertain" without the override, "personal" with it.
    base = [Line(id="L001", date="03/03/2026", merchant="ACME PROVEDORE",
                 description="", amount=8.50, currency="AUD")]
    L.triage(base)
    assert base[0].claimGuess == "uncertain"
    over2 = [Line(id="L001", date="03/03/2026", merchant="ACME PROVEDORE",
                  description="", amount=8.50, currency="AUD")]
    L.triage(over2, extra_personal=["acme provedore"])
    assert over2[0].claimGuess == "personal"


def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")


if __name__ == "__main__":
    _run_standalone()
