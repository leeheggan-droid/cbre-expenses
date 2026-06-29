"""
cbre_lib — shared helpers + CBRE business rules for the expense auto-fill pipeline.

Everything PeopleSoft/CBRE-specific that the stage scripts (parse_statement, reconcile,
classify, preview) need lives here, so the rules are encoded in exactly one place and stay
in sync with RUNBOOK.md and peoplesoft-toolkit.js.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

# --------------------------------------------------------------------------- #
# Expense type codes — mirror RUNBOOK.md §2 + §6 and PS.CODES in the toolkit.
# --------------------------------------------------------------------------- #
EXPENSE_TYPES = {
    "TAXIBU":  "Taxis - Business Use",
    "TAXIINT": "Taxis - Business (International)",
    "EMPRELO": "Employee Relocation",
    "MEALCLI": "Meals & Ent'mnt - Client",
    "MEALINC": "Meals & Ent Client - Int'l",
    "MEALINT": "Meals & Ent Empl - Int'l",
    "SUBSIST": "Subsistence",
    "LIGHTRE": "Light Refreshment",
    "ACCDOM":  "Accommodation - Domestic",
    "ACCINT":  "Accommodation - International",
    "TRAVOTH": "Travel - Other",
}

# Client-meal 50/50 accounting split (RUNBOOK §1.3) — mirror PS.ACCT.
ACCT_EMPLOYEE = "529200"
ACCT_CLIENT = "529300"

# Meal types that require attendees (RUNBOOK §1.3 + §6: int'l employee meals too).
MEAL_TYPES_NEED_ATTENDEES = {"MEALCLI", "MEALINC", "MEALINT"}
# Meal types that get the 50/50 client split (client meals only — not employee meals).
MEAL_TYPES_NEED_SPLIT = {"MEALCLI", "MEALINC"}

DOMESTIC_CCY = "AUD"


# --------------------------------------------------------------------------- #
# Money + date parsing — comma-safe (RUNBOOK §5: parseFloat("2,000.00") -> 2).
# --------------------------------------------------------------------------- #
def parse_amount(s) -> float:
    """Parse a money string to float, stripping thousands separators and currency symbols.

    Handles "2,000.00", "$1,234.56", "(12.50)" (parenthesised negative), "12.50 AUD".
    Returns 0.0 for unparseable input.
    """
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip()
    if not t:
        return 0.0
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[^\d.\-]", "", t.replace(",", ""))
    if t in ("", "-", ".", "-."):
        return 0.0
    try:
        val = float(t)
    except ValueError:
        return 0.0
    return -abs(val) if neg else val


_DATE_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d",
    "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%d %B %Y",
    "%d-%b-%Y", "%d-%b-%y", "%b %d, %Y", "%d %b %y",
]


def parse_date(s) -> Optional[str]:
    """Normalise a date string to PeopleSoft's DD/MM/YYYY (RUNBOOK §2).

    Australian convention: ambiguous numeric dates are read as day-first. Returns None
    if no known format matches (caller should flag the line for manual review).
    """
    if not s:
        return None
    t = str(s).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return None


def halves(amount: float) -> tuple[float, float]:
    """Split an AUD amount 50/50 so the halves sum exactly — mirrors PS.halves().

    e.g. halves(34.51) -> (17.26, 17.25)
    """
    cents = round(amount * 100)
    a = -(-cents // 2)  # ceil division
    b = cents - a
    return (a / 100, b / 100)


# --------------------------------------------------------------------------- #
# Normalized line model — the contract between every stage (see schema/expenses.schema.json)
# --------------------------------------------------------------------------- #
@dataclass
class Proposed:
    typeCode: Optional[str] = None
    typeDisplay: Optional[str] = None
    govtExp: str = "No"                  # RUNBOOK §1.1: always No
    isClientMeal: bool = False
    needsAttendees: bool = False
    attendees: list = field(default_factory=list)   # [{name, company, title}]
    split: bool = False
    splitAccounts: list = field(default_factory=list)
    foreignCcy: Optional[str] = None


@dataclass
class Line:
    id: str
    date: Optional[str]                  # DD/MM/YYYY
    merchant: str
    description: str
    amount: float
    currency: str = DOMESTIC_CCY
    source: str = "bank"                 # "bank" | "wallet"
    receiptMatch: Optional[dict] = None  # {file, confidence} | None
    proposed: Proposed = field(default_factory=Proposed)
    flags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# --------------------------------------------------------------------------- #
# Merchant classification heuristics (RUNBOOK §1–§2). Propose-only; user confirms.
# --------------------------------------------------------------------------- #
_TAXI = re.compile(r"\b(uber(?!\s*eats)|ola|didi|lyft|taxi|cab|13cabs|gocatch|grab)\b", re.I)
_MEAL = re.compile(
    r"\b(restaurant|cafe|café|coffee|bar|grill|kitchen|dining|eatery|resto|"
    r"bistro|brasserie|pizz|sushi|ramen|thai|bbq|steak|food|uber\s*eats|deliveroo|"
    r"menulog|doordash|tavern|pub|brewery|wine|"
    # common SE-Asian food terms (user travels Bali/Jakarta/KL — RUNBOOK 6):
    r"warung|makan|restoran|nasi|mie|kopi|padang|mamak|kedai|satay|rumah\s*makan)\b",
    re.I,
)
_HOTEL = re.compile(r"\b(hotel|inn|resort|lodg|accommodat|motel|hostel|airbnb|marriott|hilton|hyatt|accor|ibis)\b", re.I)
_LIGHT = re.compile(r"\b(starbucks|coffee club|gloria jean|cafe\b)", re.I)


def classify_merchant(merchant: str, description: str, is_foreign: bool,
                      has_client_roster: bool) -> tuple[str, list[str]]:
    """Return (typeCode, flags) proposed for a line. Conservative + flags anything uncertain."""
    text = f"{merchant} {description}".strip()
    flags: list[str] = []

    if _TAXI.search(text):
        return ("TAXIINT" if is_foreign else "TAXIBU", flags)

    if _HOTEL.search(text):
        flags.append("accommodation: should be booked via CTM - confirm/needs approval (RUNBOOK 1.6)")
        return ("ACCINT" if is_foreign else "ACCDOM", flags)

    if _MEAL.search(text):
        if has_client_roster:
            # Trip with a client roster: propose as a client meal (attendees + 50/50 split),
            # but always flag for confirmation since a bank line can't prove who attended.
            flags.append("meal: proposed as CLIENT meal - confirm attendees + 50/50 split (RUNBOOK 1.3)")
            return ("MEALINC" if is_foreign else "MEALCLI", flags)
        # No client roster -> treat as an employee meal.
        flags.append("meal: proposed as employee meal — confirm")
        return ("MEALINT" if is_foreign else "SUBSIST", flags)

    flags.append("unknown merchant: confirm expense type")
    return ("TRAVOTH", flags)


def build_proposed(line: Line, has_client_roster: bool, roster: Optional[dict],
                   client_key: Optional[str]) -> Proposed:
    """Fill a line's `proposed` block from the heuristics + CBRE rules."""
    is_foreign = (line.currency or DOMESTIC_CCY).upper() != DOMESTIC_CCY
    code, flags = classify_merchant(line.merchant, line.description, is_foreign, has_client_roster)
    line.flags.extend(flags)

    p = Proposed(
        typeCode=code,
        typeDisplay=EXPENSE_TYPES.get(code, code),
        govtExp="No",
        foreignCcy=(line.currency.upper() if is_foreign else None),
    )
    if code in MEAL_TYPES_NEED_ATTENDEES:
        p.needsAttendees = True
        if roster and client_key and client_key in roster:
            # Propose: you (filled at entry time from personal/my-details) + all client reps.
            p.attendees = list(roster[client_key])
    if code in MEAL_TYPES_NEED_SPLIT:
        p.isClientMeal = True
        p.split = True
        p.splitAccounts = [ACCT_EMPLOYEE, ACCT_CLIENT]
    return p


# --------------------------------------------------------------------------- #
# Small IO helpers
# --------------------------------------------------------------------------- #
def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(obj, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
