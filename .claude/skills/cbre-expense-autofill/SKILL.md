---
name: cbre-expense-autofill
description: >
  Auto-fill a CBRE PeopleSoft expense report from a bank statement (+ optional receipts and an
  attendee roster). Parses and classifies offline, shows a review table to approve (GATE 1), then
  drives the live PeopleSoft form via the Claude-in-Chrome browser extension and STOPS at
  Summary-and-Submit (GATE 2) for the user to submit. Use when the user wants to enter / create /
  fill a CBRE expense report, or mentions PeopleSoft expenses, myhcm, "My Wallet", or an expense run.
---

# CBRE expense auto-fill

End-to-end orchestrator that turns a bank statement into a populated (but **not submitted**) CBRE
PeopleSoft expense report. Read `RUNBOOK.md` for the underlying rules and field IDs, and
`peoplesoft-toolkit.js` for the `PS` browser helpers this skill drives.

## Hard rules (never break)
- **Never click "Summary and Submit" / never submit.** Stop at GATE 2 and hand control to the user.
- **Two approval gates.** Do not enter anything into PeopleSoft until the user approves GATE 1.
- **Bank statement is the source of truth.** Receipts and My-Wallet only corroborate. Never claim a
  receipt that has no matching bank line.
- **Govt Exp = No on every line** (CBRE rule). Default Location = a CBRE **office** code.
- **Save after every line / meal** — the session times out in ~15 min and loses unsaved lines.
- PII (client attendee names) lives only in gitignored `personal/`. Never write it to tracked files.

## Paths
- Repo root: the `cbre-expenses` working copy (e.g. `C:\Users\jacks\cbre-expenses`).
- Python: `C:\Users\jacks\AppData\Local\Programs\Python\Python313\python.exe` (call it `$PY`).
- Roster (PII, gitignored): `personal/attendees.json`. Run working dir: `personal/runs/<run>/`.

---

## Stage 0 — Gather inputs
Ask the user for / locate:
1. **Bank statement** (CSV or PDF) — primary. Put under `personal/runs/<run>/`.
2. **Receipts** (images/PDFs) — optional secondary. Extract them with **Claude-native vision**: open
   each image with the Read tool and write the data to `personal/runs/<run>/receipts.json` as a list
   under a `receipts` key — `[{file, merchant, date "DD/MM/YYYY", currency, total, type, items[], pay, note}]`
   (type ∈ meal/drinks/taxi/hotel/…). No external API key. receipts not on the statement are still
   claimed (reconcile promotes them to lines).
3. **Roster** `personal/attendees.json` and a **run-config** (`clientKey`, `defaultLocation`,
   `businessPurpose`, `reportDescription`). Copy `samples/run-config.example.json`. Per-user recurring
   merchants go in `personal/triage.json` (copy `samples/triage.example.json`).

If a bank profile is needed (auto-detect misses columns), create one from `samples/bank-config.example.json`.

## Stage 1 — Offline pipeline (no PeopleSoft; safe to run anytime)
**One-shot (preferred):**
```
$PY tools/run_pipeline.py --statement personal/runs/<run>/statement.pdf \
    --run-config personal/runs/<run>/run-config.json --roster personal/attendees.json \
    --triage personal/triage.json --receipts personal/runs/<run>/receipts.json \
    --outdir personal/runs/<run>
```
This runs parse → reconcile → classify → preview and writes lines/reconciled/classified/approved.json.
(Or run the stages individually: `parse_statement.py` → `reconcile.py` → `classify.py` → `preview.py`.)

**Easy mode (operator prefers Excel):** instead of editing JSON, generate a spreadsheet with dropdowns,
have the operator fill it, and read it back:
```
$PY tools/excel_template.py personal/runs/<run>/classified.json --out personal/runs/<run>/review.xlsx
# ... operator fills review.xlsx (Claim, ExpenseType, Attendees, Split5050) ...
$PY tools/excel_read.py     personal/runs/<run>/review.xlsx --out personal/runs/<run>/approved.json
```

## GATE 1 — Pre-entry review (REQUIRED)
Show the user the `preview.py` table. Walk through every **FLAG** (unknown types, accommodation→CTM,
meals needing attendees/split, unparseable dates, wallet duplicates, receipt-only lines, uncertain
triage). Let the user move lines between business/personal and fix types.

**Attendee interview (for every meal/drink):** list the meals that need attendees and ask the operator,
per line: how many people, how many CBRE, how many client, and names in `Surname,First` with each
person's org. Then apply:
```
$PY tools/attendees.py list  personal/runs/<run>/classified.json
$PY tools/attendees.py apply personal/runs/<run>/classified.json --answers answers.json --out personal/runs/<run>/approved.json
```
Anyone whose org ≠ CBRE makes it a client meal → attendees + 50/50 split set automatically.

**Get explicit approval before Stage 2.** The approved `lines[]` (each with `proposed`) is what you enter.

---

## Stage 2 — Drive PeopleSoft (Claude-in-Chrome)

### Setup
1. Load browser tools in ONE call:
   `ToolSearch select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__tabs_create_mcp`
2. `tabs_context_mcp` to find the tab on **myhcm.cbre.com** at the **Create/Modify Expense Report** page.
   If absent, ask the user to log in (SSO) and open that page — do NOT try to log in for them.
3. **Inject the toolkit:** read `peoplesoft-toolkit.js` and run its full contents via `javascript_tool`.
   It sets `window.PS`. Verify with `PS.audit()`.
4. **Inject attendee templates** from `personal/attendees.json`:
   `window.PS.TEMPLATES = <contents of personal/attendees.json, minus the _comment key>;`
5. **Header**: ensure Business Purpose, Report Description and Default Location (office code) are set.
   The toolkit has no header setters — either the user set them when creating the report, or set them
   via the form fields directly. Confirm before adding lines.

### Postback discipline (critical)
Anything that re-renders the page needs a wait before the next action. After calling any of
`PS.addLine, PS.setType, PS.fillBlankLine, PS.setCurrency, PS.expandAccounting, PS.addDistRow,
PS.openAttendees, PS.addAttendeeRow, PS.attendeeOK, PS.openWallet, PS.walletDone, PS.save`
**wait ~2s** (3s for wallet/save) before the next `javascript_tool` call. Plain setters
(date/desc/merchant/amount/account) are instant. Each `PS.*` returns a status string — read it; if it
reports a missing field, stop and report rather than pushing on.

### Entry procedure (per approved plan)
1. **My Wallet first** (corporate-card items carry FX conversion): `PS.openWallet()` → wait →
   `PS.walletSelectAll()` (real clicks) — but only tick **claimable/receipted** items; skip
   personal/non-reimbursable → `PS.walletDone()` → wait 3s. Reconcile told you which approved lines are
   `source:"wallet"` (already in system) vs out-of-pocket to add.
2. **Out-of-pocket lines** (e.g. the separate Uber account): for each approved line not from wallet:
   - `PS.addLine()` → wait 2s. (If it doesn't register while lines are expanded, Collapse All first.)
   - `PS.fillBlankLine({date, type: proposed.typeCode, amount, desc, merchant})` → wait 2s.
   - `PS.applyPendingMerchant()` (the type postback wipes Merchant).
   - **Foreign line** (`proposed.foreignCcy`): `PS.setCurrency(idx, foreignCcy)` → wait 2s →
     re-apply merchant. (Set currency AFTER the type postback or it resets to AUD — RUNBOOK §6.)
   - **`PS.save()` → wait 3s** (every line).
3. **Govt Exp = No on all**: Expand All, then `PS.govtNoAll()`; check the returned counts.
4. **Client meals** (`proposed.split` / `needsAttendees`):
   - Attendees: `PS.openAttendees(idx)` → wait → add rows to the needed count (`PS.addAttendeeRow()`
     each → wait), then `PS.fillAttendeeBlanks(proposed.attendees)` (include the CBRE employee +
     the client reps) → `PS.attendeeOK()` → wait. Identify the meal by **merchant**, not modal number
     (modal numbering is off-by-one — RUNBOOK §5).
   - 50/50 split: `PS.expandAccounting(idx)` → wait → `PS.addDistRow(idx, fullAUD)` → wait →
     `[a,b] = PS.halves(fullAUD); PS.setSplit(idx, fullAUD, a, b)` (keeps 50% on 529200, moves 50% to
     529300). For foreign lines split the **AUD** distribution amount, not the foreign amount.
   - `PS.save()` → wait 3s.
5. **Audit**: `PS.audit()` — verify line count, each amount/type, and that totals match the approved
   plan. Re-open a couple of attendee modals to confirm they stuck.

## GATE 2 — Final review (REQUIRED, STOP HERE)
Summarise what was entered (lines, per-currency totals, attendees, splits, Govt Exp all-No) vs the
approved plan. **Do not submit.** Tell the user to attach receipts (below) and click **Summary and
Submit** themselves.

## Receipts (manual — extension not authorised on myfin.cbre.com)
The Chrome extension is authorised on `myhcm` but **not** `myfin` (where the receipt file-input lives,
in nested iframes). So: prepare the receipt **bundle** (`tools/receipt_bundle.py`: shrink image-PDFs,
one image per claim, named to the claim), then instruct the user to download + attach manually. Verify
**#receipts == #lines** before the user submits.

## Troubleshooting
- `PS` undefined on the next call → re-inject the toolkit (window.PS was lost / page navigated).
- "Page no longer available" / SSO bounce → session timed out; reload, re-inject, resume from last
  saved line (you saved after each, so little is lost).
- A `PS.*` call returns "… not found" → the field id drifted or the page isn't ready; re-check the
  page state, don't blindly retry.
- Add-line won't register → Collapse All, then `PS.addLine()`.
