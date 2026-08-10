"""Tests for the entity expense-type charts (AU default / HK) used by excel_read.py.

Lee files under the Hong Kong entity, whose 28-type chart shares almost no display
strings with the AU chart. Before `--chart`, an HK sheet read with the (only) AU map
resolved every ExpenseType to None and the PeopleSoft run silently lost the type.

Workbook fixtures are built programmatically with openpyxl in a temp dir - no binary
fixtures in a public repo.

Run with pytest, or standalone:  python tests/test_expense_charts.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)

import openpyxl  # noqa: E402

import cbre_lib as L  # noqa: E402
import excel_read as ER  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="cbre_chart_test_")

HEADERS = ["ID", "Date", "Merchant", "Amount", "Currency", "Claim",
           "ExpenseType", "Attendees", "Split5050", "Notes"]


def _sheet(name: str, rows: list[dict], header: dict | None = None) -> str:
    """Build a minimal Review workbook from [{'ID':..., 'ExpenseType':...}, ...].

    `header` adds a Waypoint-style label/value `Header` sheet, e.g. {"Chart": "hk"}.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Review"
    if header is not None:
        # Deliberately the FIRST (and so the active) sheet, as Waypoint exports it.
        hs = wb.create_sheet("Header", 0)
        for label, value in header.items():
            hs.append([label, value])
    ws.append(HEADERS)
    for i, r in enumerate(rows, start=1):
        defaults = {"ID": f"L{i:03d}", "Date": "05/06/2026", "Merchant": "TEST MERCHANT",
                    "Amount": 10.0, "Currency": "HKD", "Claim": "Yes",
                    "ExpenseType": "", "Attendees": "", "Split5050": "No", "Notes": ""}
        defaults.update(r)
        ws.append([defaults[h] for h in HEADERS])
    path = os.path.join(_TMP, name)
    wb.save(path)
    return path


# --------------------------------------------------------------------------- #
# The chart helper itself
# --------------------------------------------------------------------------- #
def test_hk_chart_resolves_hk_displays():
    hk = L.load_chart("hk")
    assert hk.display_to_code["Lodging"] == "LODGING"
    assert hk.display_to_code["Taxi/Parking/Ground Transport"] == "GRNDTRN"
    assert hk.base_currency == "HKD"
    assert len(hk.expense_types) == 28


def test_au_chart_is_the_default():
    au = L.load_chart()
    assert au.name == "au"
    assert au.display_to_code["Taxis - Business Use"] == "TAXIBU"
    assert au.base_currency == "AUD"
    assert au.expense_types == L.EXPENSE_TYPES


def test_same_display_maps_to_a_different_code_per_chart():
    # The one display string both charts share - and it is NOT the same code.
    display = "Meals & Ent'mnt - Client"
    assert L.load_chart("au").display_to_code[display] == "MEALCLI"
    assert L.load_chart("hk").display_to_code[display] == "MEAL50"


def test_meal_types_need_attendees_differ_between_charts():
    au = L.load_chart("au")
    hk = L.load_chart("hk")
    assert au.meal_types_need_attendees == {"MEALCLI", "MEALINC", "MEALINT"}
    assert hk.meal_types_need_attendees == {"MEAL50", "MEAL100"}
    assert au.meal_types_need_attendees.isdisjoint(hk.meal_types_need_attendees)
    # AU splits client meals 50/50; the HK re-file does not (docs/HK-MODULE.md 1).
    assert au.meal_types_need_split == {"MEALCLI", "MEALINC"}
    assert hk.meal_types_need_split == set()


def test_unknown_chart_name_is_rejected():
    try:
        L.load_chart("nz")
    except ValueError as exc:
        assert "nz" in str(exc) and "hk" in str(exc)
    else:
        raise AssertionError("load_chart('nz') should raise")


# --------------------------------------------------------------------------- #
# excel_read --chart
# --------------------------------------------------------------------------- #
def test_read_workbook_chart_hk_resolves_codes():
    path = _sheet("hk.xlsx", [
        {"ExpenseType": "Lodging"},
        {"ExpenseType": "Taxi/Parking/Ground Transport"},
        {"ExpenseType": "Meals & Ent'mnt - Employee", "Attendees": "Heggan,Lee"},
    ])
    by_id = {ln["id"]: ln for ln in ER.read_workbook(path, chart="hk")}
    assert by_id["L001"]["proposed"]["typeCode"] == "LODGING"
    assert by_id["L002"]["proposed"]["typeCode"] == "GRNDTRN"
    assert by_id["L003"]["proposed"]["typeCode"] == "MEAL100"
    # HK meal types drive needsAttendees off the HK chart, not the AU set.
    assert by_id["L003"]["proposed"]["needsAttendees"] is True
    assert by_id["L001"]["proposed"]["needsAttendees"] is False


def test_read_workbook_default_chart_is_au():
    path = _sheet("au.xlsx", [
        {"ExpenseType": "Taxis - Business Use"},
        {"ExpenseType": "Meals & Ent'mnt - Client", "Attendees": "Smith,John"},
    ])
    default = {ln["id"]: ln for ln in ER.read_workbook(path)}
    explicit = {ln["id"]: ln for ln in ER.read_workbook(path, chart="au")}
    assert default["L001"]["proposed"]["typeCode"] == "TAXIBU"
    assert explicit["L001"]["proposed"]["typeCode"] == "TAXIBU"
    assert default["L002"]["proposed"]["typeCode"] == "MEALCLI"
    assert default["L002"]["proposed"]["needsAttendees"] is True


def test_hk_display_does_not_resolve_under_the_au_chart():
    """The bug: HK displays are absent from the AU map. It must NOT pass silently."""
    path = _sheet("hk_under_au.xlsx", [
        {"ExpenseType": "Lodging"},
        {"ExpenseType": "Taxi/Parking/Ground Transport"},
    ])
    try:
        ER.read_workbook(path, chart="au")
    except ER.UnknownExpenseTypeError as exc:
        assert [u["value"] for u in exc.unknown] == [
            "Lodging", "Taxi/Parking/Ground Transport"]
        assert [u["row"] for u in exc.unknown] == [2, 3]          # real sheet rows
        assert [u["id"] for u in exc.unknown] == ["L001", "L002"]
        assert "au" in str(exc) and "Lodging" in str(exc)
    else:
        raise AssertionError("HK displays must not resolve silently under the AU chart")

    # The old, silent behaviour is still reachable - but only if asked for explicitly.
    lenient = ER.read_workbook(path, chart="au", allow_unknown=True)
    assert [ln["proposed"]["typeCode"] for ln in lenient] == [None, None]


def test_blank_expense_type_is_not_an_unknown():
    """A blank cell means 'not set' (and personal lines never have one) - not a typo."""
    path = _sheet("blank.xlsx", [
        {"ExpenseType": "", "Claim": "No"},
        {"ExpenseType": "Taxis - Business Use"},
    ])
    lines = ER.read_workbook(path, chart="au")
    assert lines[0]["proposed"]["typeCode"] is None
    assert lines[0]["proposed"]["typeDisplay"] is None
    assert lines[1]["proposed"]["typeCode"] == "TAXIBU"


# --------------------------------------------------------------------------- #
# The Header sheet declares its own chart (Waypoint exports)
#
# The strict unknown-type check can't catch the two displays the charts SHARE:
# "Meals & Ent'mnt - Client" (AU MEALCLI / HK MEAL50) and "Employee Relocation"
# (AU EMPRELO / HK EMPRELC). Those resolve happily to the wrong code under the wrong
# chart - and meals are the most common line in a pack. So the sheet states its chart.
# --------------------------------------------------------------------------- #
SHARED_DISPLAYS = {"Meals & Ent'mnt - Client": ("MEALCLI", "MEAL50"),
                   "Employee Relocation": ("EMPRELO", "EMPRELC")}


def test_only_two_displays_are_shared_between_the_charts():
    """Guards the assumption above: if a chart gains an overlap, this test says so."""
    au = L.load_chart("au").display_to_code
    hk = L.load_chart("hk").display_to_code
    assert set(au) & set(hk) == set(SHARED_DISPLAYS)
    for display, (au_code, hk_code) in SHARED_DISPLAYS.items():
        assert (au[display], hk[display]) == (au_code, hk_code)
        assert au_code != hk_code          # same words, different code = silent mis-file


def test_header_sheet_chart_is_used_when_no_flag_is_passed():
    """The regression that matters: a shared display must follow the SHEET's chart."""
    path = _sheet("hdr_hk.xlsx",
                  [{"ExpenseType": "Meals & Ent'mnt - Client", "Attendees": "Smith,John"},
                   {"ExpenseType": "Employee Relocation"},
                   {"ExpenseType": "Lodging"}],
                  header={"Entity": "HK", "Business Unit": "36120", "Chart": "hk"})
    plan = ER.read_plan(path)                       # no chart argument at all
    assert plan["chart"] == "hk"
    codes = [ln["proposed"]["typeCode"] for ln in plan["lines"]]
    assert codes == ["MEAL50", "EMPRELC", "LODGING"]
    # ...and the HK meal rule, not the AU one, drives attendees.
    assert plan["lines"][0]["proposed"]["needsAttendees"] is True
    assert ER.read_workbook(path)[0]["proposed"]["typeCode"] == "MEAL50"


def test_header_sheet_chart_conflicting_with_an_explicit_chart_errors():
    path = _sheet("hdr_conflict.xlsx", [{"ExpenseType": "Meals & Ent'mnt - Client"}],
                  header={"Chart": "hk"})
    try:
        ER.read_plan(path, chart="au")
    except ER.ChartConflictError as exc:
        assert exc.requested == "au" and exc.declared == "hk"
        assert "au" in str(exc) and "hk" in str(exc)
    else:
        raise AssertionError("an explicit --chart that contradicts the sheet must error")


def test_header_sheet_chart_agreeing_with_an_explicit_chart_is_fine():
    path = _sheet("hdr_agree.xlsx", [{"ExpenseType": "Meals & Ent'mnt - Client"}],
                  header={"Chart": "hk"})
    plan = ER.read_plan(path, chart="hk")
    assert plan["chart"] == "hk"
    assert plan["lines"][0]["proposed"]["typeCode"] == "MEAL50"


def test_no_header_sheet_keeps_the_au_default():
    path = _sheet("hdr_none.xlsx", [{"ExpenseType": "Meals & Ent'mnt - Client"}])
    plan = ER.read_plan(path)
    assert plan["chart"] == "au"
    assert plan["lines"][0]["proposed"]["typeCode"] == "MEALCLI"


def test_header_sheet_without_a_chart_row_keeps_the_au_default():
    path = _sheet("hdr_nochart.xlsx", [{"ExpenseType": "Meals & Ent'mnt - Client"}],
                  header={"Entity": "AU", "Report": "EXC4500"})
    plan = ER.read_plan(path)
    assert plan["chart"] == "au"
    assert plan["lines"][0]["proposed"]["typeCode"] == "MEALCLI"


def test_unrecognised_chart_in_the_header_sheet_errors():
    path = _sheet("hdr_bad.xlsx", [{"ExpenseType": "Lodging"}], header={"Chart": "nz"})
    try:
        ER.read_plan(path)
    except ER.SheetChartError as exc:
        assert "nz" in str(exc)
    else:
        raise AssertionError("an unknown Chart value must error, not fall back to AU")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cli(*args):
    return subprocess.run([sys.executable, os.path.join(TOOLS, "excel_read.py"), *args],
                          capture_output=True, text=True)


def test_cli_chart_hk_writes_hk_codes():
    path = _sheet("cli_hk.xlsx", [{"ExpenseType": "Lodging"}])
    out = os.path.join(_TMP, "approved_hk.json")
    r = _cli(path, "--chart", "hk", "--out", out)
    assert r.returncode == 0, r.stderr
    plan = json.load(open(out, encoding="utf-8"))
    assert plan["chart"] == "hk"
    assert plan["lines"][0]["proposed"]["typeCode"] == "LODGING"


def test_cli_unknown_type_exits_nonzero_and_names_the_rows():
    path = _sheet("cli_bad.xlsx", [
        {"ExpenseType": "Taxis - Business Use"},
        {"ExpenseType": "Taxi/Parking/Ground Transport"},
    ])
    out = os.path.join(_TMP, "approved_bad.json")
    r = _cli(path, "--out", out)          # default AU chart
    assert r.returncode != 0
    assert "Taxi/Parking/Ground Transport" in r.stderr
    assert "row 3" in r.stderr and "L002" in r.stderr
    assert not os.path.exists(out), "no plan may be written when a type is unresolved"


def test_cli_uses_the_header_sheet_chart_and_says_so():
    path = _sheet("cli_hdr.xlsx", [{"ExpenseType": "Meals & Ent'mnt - Client"}],
                  header={"Entity": "HK", "Chart": "hk"})
    out = os.path.join(_TMP, "approved_hdr.json")
    r = _cli(path, "--out", out)                    # no --chart
    assert r.returncode == 0, r.stderr
    assert "hk" in r.stdout                         # the run must show the chart used
    plan = json.load(open(out, encoding="utf-8"))
    assert plan["chart"] == "hk"
    assert plan["lines"][0]["proposed"]["typeCode"] == "MEAL50"


def test_cli_chart_conflict_exits_nonzero_names_both_and_writes_nothing():
    path = _sheet("cli_conflict.xlsx", [{"ExpenseType": "Meals & Ent'mnt - Client"}],
                  header={"Chart": "hk"})
    out = os.path.join(_TMP, "approved_conflict.json")
    r = _cli(path, "--chart", "au", "--out", out)
    assert r.returncode != 0
    assert "au" in r.stderr and "hk" in r.stderr
    assert not os.path.exists(out), "no plan may be written on a chart conflict"


def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")


if __name__ == "__main__":
    _run_standalone()
