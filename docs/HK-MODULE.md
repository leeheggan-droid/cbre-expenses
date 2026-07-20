# HK module — filing a CBRE expense report under the Hong Kong entity

This module captures everything specific to filing an expense report against the **Hong Kong
business unit** (SetID 36000 / BU 36120) in CBRE PeopleSoft (`myhcm.cbre.com`). It exists because
the HK entity behaves differently from the AU entity the base RUNBOOK was written for, and because
the browser automation needs several HK-/PeopleSoft-specific tricks that were learned the hard way.

Companion files:
- `schema/hk_expense_types.json` — the full HK expense-type chart + the AU→HK type mapping.
- `tools/ps_helpers_hk.js` — battle-tested `PS`-toolkit helpers (postback detection, blank-line add,
  attendee modal handling) tuned for the quirks below. Inject alongside `peoplesoft-toolkit.js`.

First proven end-to-end: 2026-07-20, re-filing report EXC4500 (AUD 10,592.18, 42 lines) under the HK
office as a HKD draft.

---

## 1. What's different about the HK entity

| Thing | AU (base RUNBOOK) | **HK** |
|---|---|---|
| Default Location (office) | `363 George St-SYD` etc. | **`ZZ010` — "Hong Kong Office"** (the only `ZZ…` code; SetID 36000) |
| Base / report currency | AUD | **HKD** — so **every** line is a "foreign" line; set each line's transaction currency (AUD/IDR/MYR) and PeopleSoft converts to HKD |
| Expense-type chart | TAXIBU, MEALCLI, SUBSIST, LIGHTRE, ACCDOM, TRAVOTH, EMPRELO, … | **A completely different 28-type chart** — none of the AU codes exist. See §2. |
| Meal attendees | prompted at save | **meal type auto-opens the attendee modal on type-set**; the employee (you) is auto-added as row 0 |
| Client-meal 50/50 split | required | **not used** for this re-file (Lee's call 2026-07-20) — attendees only, no GL split |
| Business unit access | — | **The killer: your primary permission list must include BU 36120.** See §4. |

### Header values that worked
- **Business Purpose:** `CONF` (Conference) — options are CLBUS / CONF / INT / TRAIN.
- **Report Description** (`EX_SHEET_HDR_SHEET_NAME`): free text.
- **Default Location** (`EX_LOCATION_VW2_DESCR`): set via the lookup → search `ZZ` → single result `ZZ010`.

---

## 2. HK expense-type chart & AU→HK mapping

The HK `EXPENSE_TYPE$N` dropdown has **28** options. Full list + codes in
`schema/hk_expense_types.json`. The mapping used for the EXC4500 re-file (confirmed by Lee):

| AU source type | → HK type (code) | Notes |
|---|---|---|
| Taxis – Business Use | **GRNDTRN** — Taxi/Parking/Ground Transport | |
| Taxis – Business (Int'l) | **GRNDTRN** | no int'l taxi variant in HK |
| Meals & Ent'mnt – Client (+ Int'l Client) | **MEAL50** — Meals & Ent'mnt - Client | client meals |
| Meals & Ent (Empl) – Int'l | **MEAL100** — Meals & Ent'mnt - Employee | employee/team meals |
| Subsistence (solo travel meals) | **MEAL100** | HK has no "subsistence" type |
| Light Refreshment | **MEAL100** (or OTHTAX if it's really a fee) | judgement call |
| Accommodation – Domestic | **LODGING** | |
| Travel – Other / Visa / tourist levy | **OTHTAX** — Other Taxes, Licenses & Fees | `TRVL` exists but is "GWS ONLY", usually invalid for non-GWS staff |
| Employee Relocation | **EMPRELC** | needs authorising contract attached |

**Attendee rules under HK:**
- `MEAL50` (client) and `MEAL100` (employee) both require ≥1 attendee. You are auto-added, so a
  **solo employee meal saves fine with just you** — no extra action needed beyond OK-ing the modal.
- Client meals: add the client reps (plus any CBRE colleagues) into the modal (§3).

---

## 3. PeopleSoft browser-automation quirks (HK re-file, learned 2026-07-20)

These bit hard; `tools/ps_helpers_hk.js` encodes the fixes.

1. **PeopleSoft anchor buttons don't respond to JS `.click()`** — the modal **OK** (`PSFT_CLOSE_MODAL$0`)
   and the attendee **"+"/"-"** row buttons only fire on a **real mouse click** (computer tool).
   *Setting field values via JS works fine* (`el.value=…; dispatch input/change/blur`). So the fast,
   reliable pattern is: **JS to fill, real mouse-click to press buttons.**
   - The "+" is tiny; computed coordinates run ~1.5% high vs the screenshot (`click ≈ computed × 0.985`),
     and screenshot width varies (1522/1536/1568) so no fixed scale is perfect. **Screenshot before
     each button click, or have a human click the "+" N times** (human-in-the-loop was fastest for the
     10-person DDSP meal: "click + nine times", then JS fills the nine names).
2. **Postbacks are partial (Ajax)** — the `TargetContent` iframe document is *not* replaced, and a
   spinner animation means "wait for DOM quiet" never settles. Detect completion via the hidden
   **`ICStateNum`** field, which increments once per completed server round-trip. (~2–4s each on CBRE's
   server; a call doing >~4 postbacks can exceed the 45s CDP eval cap — see quirk 6.)
3. **`addLine()` inserts the new line at index 1** (after the focused line), not at the end, and the
   new row's `<select>` renders a moment after the postback. Poll for a blank `EXPENSE_TYPE$i` after
   adding. **Empty lines are dropped on save**, so strays self-clean.
4. **Stale attendee `ptModFrame` iframes accumulate** — old modal frames linger invisibly (and
   sometimes visibly) and fool a naive `PS.modal()`. Always target the **newest** frame with a
   **visible** OK button. Remove orphan att-frames between meals.
5. **Committing attendees resets that line's currency & merchant** back to base/blank. **Re-set
   currency + merchant right before the save**, and verify after.
6. **The 45s CDP eval cap + background execution** — a JS call that runs long is killed at 45s by the
   tool, **but the in-page async keeps running to completion**. This causes **duplicate lines** if you
   fire another mutating call over the top. Make bulk operations **idempotent** (skip a line whose
   amount+merchant already exists) and **poll to quiescence** (`ICStateNum` + lineCount stable) before
   the next action.
7. **Component/session times out ~15 min** → "This page is no longer available." Recover via *"return
   to your most recent active page"* — the draft (all saved lines) survives. **Save after every
   line/meal**; it both persists and keeps the session alive. (Injected `window.PS`/helpers survive the
   inner-frame reload; only re-inject if the whole page reloaded.)

### The reliable per-meal sequence
1. `addBlank()` → set date/desc/amount (JS) → set type MEAL50/100 (JS, postback) → attendee modal
   auto-opens with you as row 0.
2. **Group meal:** real-click "+" once per extra attendee (or ask the human), then JS-fill the blank
   rows, then **real-click OK**. **Solo meal:** just real-click OK.
3. JS: set currency + merchant on the line, then `PS.save()`.
4. If a save re-prompts the attendee modal, real-click OK; then **dismiss the BU-36120 error** (§4)
   with a real click.
5. Re-verify the line (currency/merchant/attendees) by content.

---

## 4. The BU-36120 permission wall (blocks submission)

On save, building the HK accounting throws:

> *Current 'Primary permission list: CB_BU_APAC_AUS don't have access to 'Business Unit: 36120, kindly
> raise a SOX request or email to Global Peoplesoft security team … 'myFINSecurity@cbre.com'.*

- The employee's primary permission list (here **CB_BU_APAC_AUS** — Australia) lacks access to the HK
  business unit **36120**. The error is **dismissable and the draft still saves**, but the report
  **cannot be submitted** (and final accounting can't build) until access is granted.
- **Action for the employee:** raise a SOX request / email **myFINSecurity@cbre.com** for BU 36120
  access, *then* complete Govt-Exp + receipts + Summary and Submit.

---

## 5. Employee's manual finish-up (things automation can't/shouldn't do)
- **Attach receipts** on `myfin` (the Chrome extension isn't authorised there).
- **Govt Exp = No** on every line (Expand All → set each). Doesn't block the draft; enforced at submit.
- **Relocation contracts** attached to each `EMPRELC` line.
- **Summary and Submit** — only after BU-36120 access is granted. *Never auto-submit.*
