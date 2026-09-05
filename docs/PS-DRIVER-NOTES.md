# Driving the PeopleSoft expense form — measured notes

Everything here was MEASURED against the live HK form (2026-09-05). It supplements
`RUNBOOK.md`, `docs/HK-MODULE.md` and `peoplesoft-toolkit.js`. No amounts, names or
report contents — those live in gitignored `personal/`.

## Two domains, two permissions
- T&E dashboard: **`myfin.cbre.com`** (`PT_FLDASHBOARD` … `DB=CB_TE_DASHBOARD`).
- The expense report itself: **`myhcm.cbre.com`** (`ADMINISTER_EXPENSE_FUNCTIONS.TE_EXPENSE_SHEET.GBL`).
- The Chrome extension must be authorised on **both**. The dashboard tile needs two clicks,
  and the second one lands *after* the hop to `myhcm` — so without that permission it fails
  with "Permission denied for this action on this domain" while screenshots still work.

## Reaching the fields
- The form renders inside `iframe#ptifrmtgtframe` (name `TargetContent`). **`find` and
  `read_page` cannot see any of it** — go through `contentDocument`.
- `javascript_tool` **refuses to return a result that looks like a query string**. Never build
  output as `key=value`; use ` is ` or similar.

## Field ids
Header: `EX_SHEET_HDR_BUSINESS_PURPOSE` (CLBUS · CONF · INT · TRAIN), `EX_SHEET_HDR_SHEET_NAME`
(Report Description), `EX_LOCATION_VW2_DESCR` (Default Location), `EX_SHEET_HDR_REFERENCE_ID`.
Per line `$n`: `TRANS_DATE$n`, `EXPENSE_TYPE$n`, `DESCR$n`, `TRANS_AMT1$n`,
`EX_SHEET_LINE_TXN_CURRENCY_CD$n`, `MERCHANT$n`, `EX_LOCATION_VW6_DESCR$n`,
`PAYMENT_TYPE$n`, `EX_SHEET_LINE_BILL_CODE_EX$n`.

## Adding lines
- The row `+` is the anchor `EX_LINE_WRK_EX_INSERT_LNPB$0`. Calling the page's own
  `submitAction_win0(win0,'EX_LINE_WRK_EX_INSERT_LNPB$0')` works — no real mouse click needed
  (unlike the modal/attendee anchors, which do need one).
- **A new row is inserted at `$1`**; everything else shifts down, so ids reshuffle. Find the
  blank row by scanning for the first empty `EXPENSE_TYPE$n`, never by remembering an index.
- **⚠ Empty added rows are DISCARDED on save.** Pre-adding N blank rows and filling them later
  loses all of them. Add ONE row, fill it, save; repeat.

## Getting values to stick (the expensive lesson)
- On a **brand-new row**, values written only by script are dropped on save. The row has to be
  made dirty by something PeopleSoft trusts: either real typing into one field, or the
  **expense-type change**, which fires its own postback and does commit the row.
- Working order per line: set date + description + amount by script → set `EXPENSE_TYPE`
  (postback, wait) → **then** set currency and merchant, because the type postback wipes them
  (`RUNBOOK` §6 and `applyPendingMerchant` in the toolkit) → save.
- Dates are **DD/MM/YYYY**. Verify with a day above 12 before trusting a whole batch.
- Amounts are entered in the transaction currency; PeopleSoft converts to the HKD base itself.
  Do not pre-convert.

## The modal that stops everything
- Saving a report that holds a meal line with no attendees **auto-opens the Attendees modal**,
  and while it is open every other action silently no-ops — including row inserts, which just
  return "adding" and change nothing. If inserts stop working, screenshot before retrying.
- The modal pre-fills the employee's own attendee row, so it can be accepted to unblock and the
  full roster added later.
- Its OK / `+` / `-` anchors need REAL mouse clicks.

## Sequence that works
1. Dashboard → Create Expense Report (two clicks) → Add.
2. Set the header fields, then save once to mint the report id.
3. Per line: insert → fill date/desc/amount → set type (wait) → set currency + merchant → save.
4. Leave meal lines until last, or expect the attendee modal mid-run.
5. Never click Summary and Submit — that is the user's.
