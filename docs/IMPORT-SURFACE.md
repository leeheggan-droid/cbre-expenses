# The import surface: what PeopleSoft Expenses will actually accept

Mapped by walking the live **Travel & Expense Tools** dashboard end to end. Every claim below was
observed in the UI, not inferred from Oracle documentation.

**No amounts, IDs, names or report numbers appear in this file.** See the gitignored `personal/`
for anything real.

---

## 1. There is NO file import of expense data. Stop looking for one.

This is the headline, and it kills a whole class of design ideas before they cost time.

`Create Expense Report` → **Quick Start "…Populate From"** offers exactly four options, and every
one of them is an internal PeopleSoft object:

| Populate From | What it does |
|---|---|
| A Template | admin-defined per Business Unit |
| A Travel Authorization | copies an *approved* pre-trip authorization |
| An Existing Report | copies a prior claim |
| Entries from My Wallet | pulls unassigned wallet transactions |

The line-level `Add:` row offers only **My Wallet** and **Quick-Fill**.

**File upload exists only for images and documents** — the header `Attachments` link, the header
`myReceipts` link, and a per-line attach icon. None of it carries transaction *data*.

> **Consequence for tooling:** a CSV/Excel export from a bank or card is worth nothing on the
> *output* side of this pipeline. It remains useful as pipeline *input*, but nothing in
> PeopleSoft ingests it. Do not build an exporter expecting to upload it.

---

## 2. The only data path into a claim

```
myReceipts (mobile app)
    → auto-parsed into structured fields
        → "Move to Wallet"   (OOP receipts only)
            → My Wallet
                → report:  Populate From "Entries from My Wallet"   (or the Add: My Wallet link)
```

**`myReceipts` is a parsing stage, not an attachment store.** A staged receipt arrives with
Trans Date, Payment Type, Billing Type, Empl ID, **Expense Type, Merchant, Amount, Currency and
Description** already extracted from the image.

The page states the routing rule verbatim:

> *"Only OOP Receipts can be moved to the wallet using the below action. Corporate Card images can
> be attached to Corporate Card transactions inside My Wallet or directly attached to a
> transaction line on an expense report."*

So **OOP (out-of-pocket) is the personal-card path, and it works** without a corporate card.

### Traps on this path

- **The `myReceipts` web page has no upload control** — only `Reassign`, `Move to Wallet`,
  `Delete`, `Save`. Receipts enter via the **mobile app** (QR on the dashboard tile). Email-in is
  **unconfirmed**. Treat receipt capture as a phone-side step that desktop automation cannot
  perform; automation picks up from *Move to Wallet* onward.
- **`Move to Wallet` LOSES the expense type.** A receipt parsed with a concrete expense type
  arrives in the wallet with the type **blank**, and shows as `<Unspecified>` in the report
  picker. Whatever the parser worked out is discarded — re-assert it downstream.
- **My Wallet has no manual-add and no import control.** It is fed by the corporate-card feed or
  by `Move to Wallet`. Nothing else.
- **The wallet picker will not open when the wallet is empty.** A zero wallet makes both the
  `Add: My Wallet` link and the `Entries from My Wallet` option silently inert — that is not a
  failure, just an empty set.
- **FX is computed for you.** A foreign-currency wallet entry carries an **Exchange Rate** field
  and derives the base-currency amount. Do not convert upstream and pass a converted figure.
- **The wallet ages entries** and labels them `N Days Overdue`. Useful as a free backlog signal.

---

## 3. Quick-Fill is the right skeleton. Copy-from-existing is a trap.

Both build a starting document. They are not equivalent, and the difference is a financial
control, not a preference.

### Quick-Fill — SAFE, use this

`Add: | Quick-Fill` opens a modal that states its own contract:

> *"Enter the date range you want applied to the expenses you will be adding to the report. Then
> choose the expense types and whether you want to add one instance of the expense type or have an
> entry of that expense type for each day within the date range."*

- A **date range**, then every expense type with **two** checkbox columns: **One Day** | **All Days**.
- Generates lines with the **correct expense type and correct date, and an empty amount**.
- Trip pattern: airfare as *One Day*; lodging, meals and ground transport as *All Days* across the
  trip dates. The whole grid appears in one action.

**Nothing is pre-filled with money, so there is nothing to accidentally re-claim.**

### Copy from an Existing Report — DANGEROUS

`Quick Start → An Existing Report → GO` opens **"Copy from Existing Expense Report"** with a
date-range search over prior claims.

**It is a full clone, not a skeleton.** Verified live: it carries the header **Business Purpose**
and **Report Description**, reproduces the source's **exact line count and total**, and per line
carries **Date, Expense Type, Description, Payment Type, Billing Type, Amount, Currency and
Merchant**.

> ⚠️ **A copied report is a valid duplicate claim until every line is edited.** Any line left
> untouched silently re-claims an expense that was already reimbursed.
>
> **Any tool built on Copy MUST diff every line against its source and fail loudly on an unchanged
> `amount + date` pair.** This is a hard gate, not a warning in a preview table — a preview built
> to catch *parsing* errors will not catch *clone residue*, because clone residue looks correct.

**Attachments do NOT copy.** Receipts must be re-attached to the new report.

Copy retains one narrow legitimate use: looking up which expense types a past trip used. Never as
the starting document.

---

## 4. Quick-Fill and My Wallet compose

Verified live: running Quick-Fill and then adding wallet entries on the **same** report yields the
sum of both. **The second population does not overwrite the first.**

That makes the intended monthly shape:

1. Receipts into the myReceipts app at the point of spend
2. `Move to Wallet`
3. New report → **Quick-Fill** the trip's date range and expense types → correctly-typed empty grid
4. **Entries from My Wallet** for the real transactions
5. Re-assert expense types lost in the move, re-attach receipts
6. Summary and Submit — the human gate

---

## 5. The `Actions` menu (populated report only)

Once a report has lines, `Quick Start` is replaced by **`Actions`**:

`Export to Excel` · `Adjustment Cash Advance` · `Apply/View Cash Advance(s)` ·
`Associate Travel Authorization` · `Copy Expense Lines` · `Default Accounting For Report` ·
`Expense Report Project Summary` · `User Defaults`

**`Export to Excel` is the only good data-OUT path** and is far better than scraping the grid.
Note `Copy Expense Lines` is a second line-level clone mechanism and carries the same duplicate
risk as §3.

---

## 6. Automation gotchas specific to these screens

These cost real time. They are additive to the gotchas in `RUNBOOK.md` and `docs/HK-MODULE.md`.

- **Dashboard tiles need TWO real clicks.** The first only focuses the tile.
- **Dashboard tile counts are STALE.** A tile read `0 Wallet Transactions` while the wallet
  actually held an item. **Never branch on a tile count — open the component and read it.**
- **The page reflows between renders** (it alternates between viewport widths), so coordinates go
  stale within a single session. **Resolve each element's centre via `getBoundingClientRect()`
  plus the frame offset immediately before every real mouse click.** Hard-coded coordinates from
  an earlier screenshot will miss.
- **Selecting a `Quick Start` option by mouse does not stick** — the select silently reverts to
  `…Populate From`. Set `selectedIndex` in JS and dispatch a bubbling `change`, *then* click GO
  with a real mouse click.
- **Heavy operations block the renderer.** Copying a large report, loading receipts and committing
  wallet entries all make `Page.captureScreenshot` time out, and script injection can time out
  mid-navigation. **Wait and retry. Do NOT re-click** — the underlying request is still running
  and a second click duplicates lines.
- **Read state via JS, not screenshots, while the renderer is busy.** Walk the frames and take the
  largest `innerText`; guard on a string you expect to be present before trusting what you read.
- **The in-app menu search is useless here.** Searching "receipt" or "expense" returns Purchasing
  items (Receive Items, Receipt Accrual) and the dropdown goes stale between queries. Navigate the
  T&E dashboard tiles instead.
- **The `find`-by-description tool cannot see these controls** — they live in a nested frame.

### Safe to explore

**Opening `Create Expense Report`, running Quick-Fill, copying a report and adding wallet entries
do NOT persist anything.** Confirmed by `0 Unsubmitted Reports` before and after. A report exists
only once explicitly saved.

**`Move to Wallet` DOES persist** — it is a real state change on a real receipt. It is the one
action in this document that is not free.
