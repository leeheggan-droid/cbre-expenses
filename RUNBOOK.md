# CBRE PeopleSoft Expense Report — Runbook

How to create/fill an expense report in CBRE's PeopleSoft (myhcm.cbre.com) **fast and correctly**.
Employee ID and entry point: see `personal/my-details.md`.

---

## 0. TL;DR — the "better way" that actually works

Driving this form by **pixel-clicking is slow and error-prone** (native dropdowns ignore option
clicks, amount fields garble, the page scroll-traps, every change posts back to the server).

**The reliable method is JavaScript** run against the page (Chrome DevTools console, or the
`javascript_tool` when automating). The form lives in an iframe; once you know the field IDs you can
set values directly and let PeopleSoft's own postbacks build the accounting. See
[`peoplesoft-toolkit.js`](./peoplesoft-toolkit.js) for ready-made helpers.

Golden rules of the JS approach:
- All line fields are in `iframe[name="TargetContent"]`. Modals are in `iframe[name="ptModFrame_N"]`
  (N increments each time a modal opens — find it dynamically).
- **Plain fields** (date, description, merchant, amount, account, dist amount): set `.value` directly —
  PeopleSoft reads the DOM on save. Clean, no garble.
- **Things that trigger a server postback** (changing Expense Type, adding a line/row, Govt Exp,
  Save): fire them, then **wait ~2 s** before the next action.
- **Selection checkboxes & buttons** (wallet "Select", "Done", add-row, Save): a bare `.value`/`.checked`
  is NOT enough — dispatch a real click: `el.dispatchEvent(new MouseEvent('click',{bubbles:true}))`
  or `el.click()`, so PeopleSoft's handler fires.
- After **Expense Type** change the **Merchant field is wiped** — re-set it afterward.
- If the page won't scroll (header/Save trapped above viewport): run
  `iframe.contentWindow.scrollTo(0,0)` / `el.scrollIntoView({block:'center'})`.

---

## 1. Business rules (CBRE-specific — get these right)

1. **Govt Exp = "No" on EVERY line.** ("non-gov expense" — applies to everything.)
   Required field; the form blocks save without it. Manually-added lines do NOT default it.
2. **Default Location = a CBRE OFFICE code, NOT the trip destination.** e.g. `363 George St-SYD`,
   `360 Collins St`. Use the lookup; free text like "Bali" fails.
3. **Client meals** (`Meals & Ent'mnt - Client`) need TWO things:
   - **Attendees** — yourself (CBRE) + the client reps. Save blocks without attendees.
   - **50/50 accounting split** — duplicate the distribution row; **50% stays account `529200`
     (CBRE/employee), 50% changes to `529300` (client)**. i.e. "where there's a 2, make it a 3"
     = the 4th digit `529200 → 529300`. Split the dollar amount 50/50 too.
   - The split is NOT enforced by save (it's policy), but always do it.
4. **Employee/internal meals**: attendees fine, **no split**.
5. **Taxis & most single-use expenses**: no attendees, no split — leave the single 529200 line.
6. **Accommodation** should be booked through **CTM** (CBRE's travel company). Claiming accom
   out-of-pocket "will require approval" (form warns on the line). Flag to approver.
7. **Relocation** = `Employee Relocation` type. Check your employment contract for the approved
   allowance amount and conditions. Attach the authorising contract as documentation.
8. **Receipts**: itemised receipts are expected, especially for meals & entertainment — a card
   statement line is not a substitute for those. Attach per line / via "myReceipts".

### Saved attendee templates
Store your recurring client reps in `personal/my-details.md`.
(Template auto-populate by typing the name is unreliable; just re-enter the 1–2 rows — it's quick.)

---

## 2. Expense Type codes (the `<select>` values)

| Type (display)                | Code     |
|-------------------------------|----------|
| Taxis - Business Use          | `TAXIBU` |
| Taxis -Business(International) | `TAXIINT`|
| Employee Relocation           | `EMPRELO`|
| Meals & Ent'mnt - Client      | `MEALCLI`|
| Subsistence                   | `SUBSIST`|
| Light Refreshment             | `LIGHTRE`|
| Accomodation - Domestic       | `ACCDOM` |
| Accomodation - International   | `ACCINT` |
| Travel - Other                | `TRAVOTH`|

Get any others live: read the options of `EXPENSE_TYPE$0` (see toolkit `dumpExpenseTypes()`).
Date format: **DD/MM/YYYY**. Out of Pocket / NonBill-NonProducer are the right defaults.

---

## 3. Key field IDs (inside `iframe[name="TargetContent"]`)

| Purpose | ID pattern |
|---|---|
| Expense type (select) | `EXPENSE_TYPE$N` |
| Date | `TRANS_DATE$N` |
| Amount | `TRANS_AMT1$N` |
| Description | `DESCR$N` |
| Merchant | `MERCHANT$N` |
| **Add a new expense line** (anchor around img) | `EX_LINE_WRK_EX_INSERT_LNPB$IMG$N` |
| Line display number | `EX_SHEET_LINE_LINE_NBR$N` |
| Govt Exp — **No** radio (Yes = `$636`) | `CB_EX_LINE_WRK_CB_GOVT_EXP$637$$N` |
| Expand a line's **Accounting Details** | `EX_LINE_WRK_EXPAND_SECTIONS2$N` |
| Distribution account | `EX_SHEET_DIST_ACCOUNT$M` |
| Distribution amount | `EX_SHEET_DIST_TXN_AMOUNT$M` |
| **Add a distribution (split) row** | `EX_SHEET_DIST$new$M$$N`  (M=dist idx, N=line idx) |
| Attendees link (per line) | `EX_LINE_WRK_PB_ATTENDEES$N` |
| Attendee name / company / title (in modal frame) | `EX_SHEET_ATT_NAME$K` / `EX_SHEET_ATT_ATTENDEE_COMPANY$K` / `EX_SHEET_ATT_TITLE$K` |
| **Add an attendee row** (in modal frame) | `EX_SHEET_ATT$new$K$$0` |
| Save for Later | `ER_TOOLBAR#SAVE` |
| My Wallet link | `ADD#MYWALLET` |
| Wallet "Select" checkbox | `EX_TRANS_RECEIPT_VERIFIED$N` |
| Wallet "Personal/Non-Reimbursable" checkbox | `EX_TRANS_PERSONAL_EXPENSE$N` |
| Wallet "Done" | `EX_ICLIENT_WRK_OK_LEVEL1_PB` |

Note: `$N` on **line** controls (date/type/govt/expand/attendees) is the **line index** and is stable.
`$M` on **distribution** controls is a separate, ever-increasing index — find a line's dist row by
matching its account+amount, not by assuming M=N.

---

## 4. Procedure (per report)

1. **Header**: Business Purpose (Conference / Client-Business Meeting / Internal / Training),
   Report Description, Default Location (office code via lookup).
2. **Pull card items from My Wallet** if present (they carry the AUD/foreign conversion):
   open `ADD#MYWALLET`, tick the `RECEIPT_VERIFIED` boxes **with real click events**, `Done`.
   Only pull receipted/claimable items.
3. **Add out-of-pocket lines** (Ubers etc.) via `EX_LINE_WRK_EX_INSERT_LNPB`, then set
   date/desc/amount and change Expense Type (fires postback). Re-set merchant after.
4. **Fix any `<Unspecified>` wallet items** — set their Expense Type.
5. **Govt Exp = No on all** — Expand All, then set every `CB_..._GOVT_EXP$637$$N` checked.
6. **Client meals**: add attendees (modal) + 50/50 `529200`/`529300` split (expand accounting,
   add dist row, split amount, change 2nd account).
7. **Save** (`ER_TOOLBAR#SAVE`). Save prompts attendee modals for any client meal still missing them.
8. **Verify**: read all lines + total; re-open a couple of attendee modals to confirm they stuck.
9. **Attach receipts**, then **you** click **Summary and Submit** (never auto-submit).

---

## 5. Gotchas / lessons learned

- Modal "line N" numbering is **off-by-one** vs `EX_SHEET_LINE_LINE_NBR` (modal line = nbr − 1).
  Identify the meal by **merchant**, not the modal's number.
- Amount of a **foreign-currency** line: the **distribution** amount is in **AUD** (the reimburse
  amount), not the foreign txn amount. Split the AUD figure 50/50 (round so halves sum exactly).
- `parseFloat("2,000.00")` → `2` (stops at the comma). Strip commas before summing in JS audits.
- Saving needs Govt Exp on every line + attendees on every client meal, or it re-prompts.
- Don't trust blind entry — **verify each amount** (a couple silently dropped to 0.00 during manual
  entry). The JS `.value` method is reliable; still audit the running total.

---

## 6. Session-2 learnings (2026-06-28) — after submitting #0005154958 (42 lines, A$10,592.18)

**Foreign-currency lines (IDR/MYR) — the working recipe:**
1. Add line; set `TRANS_DATE`, `DESCR`, `TRANS_AMT1` (the *foreign* amount), `MERCHANT`, then change `EXPENSE_TYPE` (postback).
2. **Then** set `EX_SHEET_LINE_TXN_CURRENCY_CD$N` = `'IDR'`/`'MYR'` and fire change — its **own** postback. Setting currency *before* the type postback resets it to AUD. PeopleSoft converts at the corporate rate (a few cents under the card — normal).
3. The type change **wipes Merchant** — re-set it after.
- Int'l codes: `TAXIINT` (Taxis-Business Intl), `MEALINC` (Meals&Ent Client-Int'l), `MEALINT` (Meals&Ent Empl-Int'l).

**Attendees:** **employee int'l meals (`MEALINT`) ALSO require attendees**, not just client meals. Modal auto-pops on the meal type change / on save. Reliable flow: **check row count before each add**, add exactly to N, then fill blanks, then OK (avoids an off-by-one extra row). Delete a stray row via `frameWin.submitAction_win0(frameWin.document.win0,'EX_SHEET_ATT$delete$K$$0')` — plain `.click()`/`DeleteCheck2` do nothing.

**SESSION TIMEOUT ≈ 15–20 min** silently kills the page ("This page is no longer available" / SSO bounce), losing ALL unsaved lines. **Save after every line or meal.**

**Add-line quirk:** `EX_LINE_WRK_EX_INSERT_LNPB$IMG$0` often won't register when lines are **expanded** → click **Collapse All** first, then add.

**Receipts:** per-line attach = `ATTACHMENT_PB$N`; view link = `VIEWBUTTON$N` (opens the file in a new tab on **`myfin.cbre.com`** — different domain). Delete control = `PAYMENT_ATT$delete$0$$0`. The Chrome extension is authorised on `myhcm` but **NOT `myfin`**, and the upload file-input is unreachable in nested iframes → **the user does download + upload manually**. To shrink image-PDF receipts with no fitz/ghostscript: use **pdfplumber** to pull the embedded image (`page.images[0]['stream']`; DCTDecode `rawdata` = JPEG bytes) + **PIL** resize ~1300px/q72. Build one bundle, one image per claim, named to the claim; verify **#receipts == #lines**.
