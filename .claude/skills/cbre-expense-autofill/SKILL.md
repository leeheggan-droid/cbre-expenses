---
name: cbre-expense-autofill
description: >
  Auto-fill a CBRE PeopleSoft expense report from a bank statement (+ optional receipts and an
  attendee roster). Parses and classifies offline, shows a review table to approve (GATE 1), then
  drives the live PeopleSoft form through the available supported browser integration and STOPS at
  Summary-and-Submit (GATE 2) for the user to submit. Use when the user wants to enter / create /
  fill a CBRE expense report, or mentions PeopleSoft expenses, myhcm, "My Wallet", or an expense run.
---

# CBRE expense auto-fill

End-to-end orchestrator that turns a bank statement into a populated (but **not submitted**) CBRE
PeopleSoft expense report. Read `RUNBOOK.md` for the underlying rules and field IDs, and
`docs/PS-DRIVER-NOTES.md` for measured browser behaviour and adapter selection.
The `PS` helpers in `peoplesoft-toolkit.js` are for environments that permit script mutations;
use supported UI locators instead when browser evaluation is read-only.

## Hard rules (never break)
- **Never click "Summary and Submit" / never submit.** Stop at GATE 2 and hand control to the user.
- **Two approval gates.** Do not enter anything into PeopleSoft until the user approves GATE 1.
- **Bank statement is the source of truth.** Receipts and My-Wallet only corroborate. Never claim a
  receipt that has no matching bank line.
- Verify Government Expense and billing classifications against the approved plan and applicable
  entity rules. For non-government expenses, explicitly verify No on every line after saving.
  Default Location = the employee's CBRE **office** code.
- **Save after every line / meal** — the session times out in ~15 min and loses unsaved lines.
- PII (client attendee names) lives only in gitignored `personal/`. Never write it to tracked files.

## Paths
- Repo root: the local `cbre-expenses` working copy.
- Python: discover the local Python interpreter and use its path (called `$PY` below).
- Roster (PII, gitignored): `personal/attendees.json`. Run working dir: `personal/runs/<run>/`.

---

## Stage 0 — Gather inputs

**0a. Resolve the entity and required company configuration.** Read the approved plan, workbook
header and `personal/company.json` if present. Confirm the employee's office and expense chart
against the live form. Reuse values already supplied or verified in this session; ask only for
missing information needed for the current action.

Collect `defaultOffice`. Collect `selfAccount` and `clientAccount` only when the applicable entity
rules and approved plan require an accounting split. Do not block an HK attendees-only plan on
unused AU split accounts, or infer a 50/50 split from the `MEAL50` code alone. See
`docs/HK-MODULE.md`; previous no-split runs do not establish a universal HK policy. Save per-user
configuration under gitignored `personal/` (shape in `samples/company.example.json`). When a
split is required, resolve its accounts before that step; the toolkit adapter uses
`PS.ACCT = {employee:<selfAccount>, client:<clientAccount>}`.

Then gather / locate:
1. **Bank statement** (CSV or PDF) — primary. Put under `personal/runs/<run>/`.
2. **Receipts** (images/PDFs) — optional secondary. Extract them with **Claude-native vision**: open
   each image with the Read tool and write the data to `personal/runs/<run>/receipts.json` as a list
   under a `receipts` key — `[{file, merchant, date "DD/MM/YYYY", currency, total, type, items[], pay, note}]`
   (type ∈ meal/drinks/taxi/hotel/…). No external API key. A receipt without a matching bank
   line is a review candidate; do not automatically promote it into a claim.
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
Filing under the **HK** entity: add `--chart hk` to `excel_read.py` (HK has a different 28-type chart —
docs/HK-MODULE.md §2). A sheet that declares `Chart | hk` in a `Header` sheet (e.g. a Waypoint export)
needs no flag; passing a *different* `--chart` than the sheet declares aborts the read naming both.
An ExpenseType missing from the chosen chart also aborts, with the offending rows listed. Never file a
line with no type — and check the run's "using the … expense chart" line matches the entity.

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
Non-CBRE attendees require review as a client meal. The offline helper can propose an AU
50/50 split; verify the entity and approved plan before applying it to the live report.

**Get approval before Stage 2.** An explicit instruction to enter an already prepared/approved
plan supplies that authorization; do not ask again for unchanged scope. Resolve outstanding
uncertainties without re-requesting approval for confirmed lines. The approved `lines[]`
(each with `proposed`) is what you enter.

---

## Stage 2 — Drive PeopleSoft

### Select the adapter
Read `docs/PS-DRIVER-NOTES.md` first. With CUA or an integration that restricts evaluation to
read-only use, drive inputs through its documented locator methods and cross-origin
`frameLocator`. Do not inject the toolkit or call page mutation functions through evaluate.
Use the measured entry/save/modal/upload procedure in that document. Inspect supported APIs;
do not assume all ordinary Playwright methods exist. Reuse existing authenticated SSO when
available; hand off login/MFA only when user interaction is actually needed.

The setup and `PS.*` examples below are the **legacy toolkit adapter**, for integrations that
permit script mutations. They are not required for the locator workflow.

### Legacy toolkit setup
1. Load browser tools in ONE call:
   `ToolSearch select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__tabs_create_mcp`
2. `tabs_context_mcp` to find the tab on **myhcm.cbre.com** at the **Create/Modify Expense Report** page.
   If absent, open the known expense entry page and reuse an authenticated session when available.
   Ask the user to complete sign-in/MFA only if required; never request credentials in chat.
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
reports a missing field, inspect the current UI before continuing.

Those delays are historical starting points, not proof a postback completed. Verify the expected
row/modal/result before the next mutation. A click after save may silently no-op, and a timeout
may have already applied the write. Read back before retrying. Use small batches for repeated
postback actions. After insert/reload, rediscover row indices from date, amount, currency,
merchant and type; never reuse a previous UI suffix as a stable source identifier.

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
3. **Government Expense**: for approved non-government lines, Expand All and use the adapter
   to set No (toolkit: `PS.govtNoAll()`); verify checked values, not only helper counts.
4. **Client meals** (`proposed.split` / `needsAttendees`):
   - Attendees: `PS.openAttendees(idx)` → wait → add rows to the needed count (`PS.addAttendeeRow()`
     each → wait), then `PS.fillAttendeeBlanks(proposed.attendees)` (include the CBRE employee +
     the client reps) → `PS.attendeeOK()` → wait. Identify the meal by **merchant**, not modal number
     (modal numbering is off-by-one — RUNBOOK §5).
   - Only if the entity and approved plan require a 50/50 split: `PS.expandAccounting(idx)` → wait → `PS.addDistRow(idx, fullAUD)` → wait →
     `[a,b] = PS.halves(fullAUD); PS.setSplit(idx, fullAUD, a, b)` (keeps 50% on your self account,
     moves 50% to the client account — from `PS.ACCT`, set in Stage 0a). The toolkit example uses AU
     **AUD** distribution amounts. For another entity, verify its base currency and supported
     accounting workflow before using these AU-oriented helpers.
   - `PS.save()` → wait 3s.
5. **Audit**: `PS.audit()` — verify line count, each amount/type, and that totals match the approved
   plan. Re-open changed attendee modals to confirm they stuck. Inspect every `ERROR_ICON$n`;
   a draft can save with validation errors. For lodging, verify `NBR_NIGHTS$n` from the folio;
   do not invent nights to bypass validation. Reconcile source totals per currency and verify
   report receipt coverage after upload/save.

## Receipts — complete before handover
Use the supported upload API when available. Missing permission in a previous browser session
is not a permanent limitation of PeopleSoft. `docs/PS-DRIVER-NOTES.md` documents the verified
header Attachments → Add Attachment → file chooser → Upload → OK → Save for Later route.
Read current upload limits: the measured HK form requires **less than 10 MB total per report**,
short filenames using letters/numbers/underscores, and a save after attaching.

A combined indexed PDF is valid when each claim maps to the relevant evidence; a shared folio
may support several reconciled payments. File count need not equal line count. The existing
`tools/receipt_bundle.py` uses per-line file checks, so verify coverage separately for shared
folios or indexed packs. Preserve original receipt content and references. Flag uncertain
matches and record the employee's resolution; do not silently treat equal amounts as proof.
Verify the uploaded filename/size, save, then reopen Attachments to confirm persistence.
If the integration genuinely cannot upload, explain that specific limitation and hand off only
that remaining action, with a prepared pack and index.

## GATE 2 — Final review (REQUIRED, STOP HERE)
Summarise saved report status, line count, per-currency source totals, reimbursement total,
attendee/split completion, government flags, validation errors, receipt coverage and unresolved
decisions. Update the private run state with the current mapping to prevent duplicate entry.
**Do not submit.** Leave final review and Summary and Submit to the employee.

## Troubleshooting
- `PS` undefined on the next call → re-inject the toolkit (window.PS was lost / page navigated).
- "Page no longer available" / SSO bounce → session timed out; reload, re-inject, resume from last
  saved line (you saved after each, so little is lost).
- A `PS.*` call returns "… not found" → the field id drifted or the page isn't ready; re-check the
  page state, don't blindly retry.
- Add-line won't register → Collapse All, then `PS.addLine()`.
