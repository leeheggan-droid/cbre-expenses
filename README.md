# CBRE Expenses - tools & notes

Tools, rules, and an automation pipeline for entering CBRE PeopleSoft expense reports fast and
correctly. You feed it a bank statement (the source of truth) plus optional receipts and an attendee
roster; it parses, triages business vs personal, classifies expense types, shows a review table you
approve, and then drives the live PeopleSoft form - stopping at "Summary and Submit" so **you** submit.

Personal details (employee ID, client attendee names, real statements, receipts) live in `personal/`,
which is gitignored and never committed.

---

## What's in here

| Path | What it is |
|---|---|
| **RUNBOOK.md** | The CBRE rules + step-by-step manual procedure + every PeopleSoft field ID + gotchas. The authority for how the form behaves. |
| **README.md** | This overview. |
| **docs/USAGE.md** | Step-by-step walk-through of both operator modes. |
| **peoplesoft-toolkit.js** | Pasteable `PS` JavaScript helpers run against the form (console / `javascript_tool`). |
| **.claude/skills/cbre-expense-autofill/** | The `cbre-expense-autofill` skill - the end-to-end orchestrator that runs the pipeline and drives PeopleSoft. |
| **tools/** | The offline Python pipeline (no PeopleSoft; safe to run anytime). See below. |
| **schema/** | `expenses.schema.json` - the data contract every pipeline stage passes along. |
| **samples/** | Synthetic, no-PII example inputs (statement, roster, run-config, bank-mapping, triage). |
| **personal/** | **Gitignored.** Your real inputs and outputs: `attendees.json`, `triage.json`, and per-run working dirs under `personal/runs/<run>/`. |
| **tests/** | `python tests/test_cbre_lib.py` - unit tests for the shared library. |

### tools/
| Script | Job |
|---|---|
| `parse_statement.py` | Bank statement (CSV or PDF) -> normalized `lines.json`. |
| `reconcile.py` | Match receipts + dedupe My-Wallet items against the bank lines. |
| `classify.py` | Triage business/personal and propose an expense type, attendees and split per line. |
| `preview.py` | Render the GATE 1 review table and write the `approved.json` plan. |
| `cbre_lib.py` | Shared helpers + the CBRE rules (expense-type codes, money/date parsing, triage, the 50/50 split) in one place. |
| `excel_template.py` | (Easy mode) generate the fill-in Excel template with dropdowns. |
| `excel_read.py` | (Easy mode) read a filled-in Excel template back into the entry plan. |
| `receipt_bundle.py` | Shrink + per-claim-name receipt images for attachment, and verify #receipts == #lines. (The receipts JSON itself is produced by Claude-native vision - no external API key.) |
| `attendees.py` | The per-meal attendee interview: `list` meals needing attendees, `apply` answers to set attendees + 50/50 split. |
| `run_pipeline.py` | One-shot: parse -> reconcile -> classify -> preview (GATE 1) into a run dir. |

---

## Two ways to run it

**(a) The "hard way" - automatic parse + triage + review.** Point the tool at a bank statement; it
auto-detects the columns, triages each transaction, proposes expense types, and prints the GATE 1
table for you to approve. This is the offline pipeline below.

**(b) The "easy way" - an Excel template.** `excel_template.py` generates a spreadsheet with
dropdowns (expense type, business/personal, etc.); you fill it in by hand, and `excel_read.py` reads
it back to build the same entry plan. Use this when you'd rather eyeball and tick boxes than review a
generated table.

Either way, the plan feeds the same Stage 2: the skill drives PeopleSoft and **stops at Summary and
Submit**.

---

## The offline pipeline (hard way)

No PeopleSoft, no network, safe to run anytime. Stages pass JSON conforming to
`schema/expenses.schema.json`. The skill calls Python by absolute path; the examples below do too.

```
# $PY = the interpreter
$PY = C:\Users\jacks\AppData\Local\Programs\Python\Python313\python.exe

# 1. Parse the statement into normalized lines
& $PY tools\parse_statement.py samples\bank-sample.csv --out run\lines.json

# 2. Reconcile: match receipts (secondary) + dedupe My-Wallet items (optional inputs)
& $PY tools\reconcile.py run\lines.json --receipts run\receipts.json --wallet run\wallet.json --out run\reconciled.json

# 3. Classify: triage business/personal + propose type/attendees/split
& $PY tools\classify.py run\lines.json --run-config samples\run-config.example.json --roster personal\attendees.json --triage personal\triage.json --out run\classified.json

# 4. Preview: the GATE 1 review table + write the approved plan
& $PY tools\preview.py run\classified.json --out run\approved.json
```

Notes:
- `parse_statement.py` reads **CSV** (auto-detects common column names; override with
  `--config bank.json`, see `samples/bank-config.example.json`) and **PDF**. PDF parsing tries, in
  order: table extraction, a **text-regex** parser for card statements (e.g. HSBC), then a
  **coordinate/column** parser for paid-out/paid-in/balance bank-account layouts. Overseas FX fees on
  a card line are folded into that line's amount so you claim the true cost.
- `reconcile.py`'s inputs are optional - omit `--receipts` / `--wallet` until you have them. The bank
  statement is always the source of truth; a receipt with no matching bank line is surfaced, not
  silently claimed.
- `classify.py` proposes only - nothing is final until you approve GATE 1. It reads the normalized
  lines from `parse_statement.py`. `--roster` and `--triage` are optional.
- Real runs work under `personal/runs/<run>/` (gitignored). The commands above use a throwaway `run\`
  dir and the synthetic `samples\` inputs so you can try the whole chain with no PII.
- Receipts: the receipts JSON consumed by `--receipts` is produced by reading the receipt images with
  Claude-native vision (the operator/agent looks at the images directly - there is no external API
  key or OCR service). See `parse_receipts.py`.

### personal/ setup
Copy the samples, then edit your private copies (these stay gitignored):

| Sample | Copy to | What it holds |
|---|---|---|
| `samples/roster.example.json` | `personal/attendees.json` | Your recurring client reps, one key per client (`clientKey`). PII - never commit. |
| `samples/triage.example.json` | `personal/triage.json` | Your per-user merchant overrides: `personalMerchants` (always excluded) and `businessMerchants` (treated as business travel). Keeps your local merchant names out of the public repo. |
| `samples/run-config.example.json` | `personal/runs/<run>/run-config.json` | Per-report settings: `clientKey`, `defaultLocation`, `businessPurpose`, `reportDescription`. |

---

## Non-negotiable CBRE rules (summary - full detail in RUNBOOK §1)

- **Govt Exp = "No" on EVERY line.** Required; the form blocks save without it. Manually-added lines
  don't default it.
- **Default Location = a CBRE OFFICE code** (e.g. `363 George St-SYD`), not the trip destination.
- **Client meals** (`Meals & Ent'mnt - Client`) need **attendees** (you + client reps) AND a
  **50/50 accounting split**: 50% stays on account `529200`, 50% moves to `529300`. Split the AUD
  amount 50/50.
- **Accommodation** should be booked through **CTM**; out-of-pocket accom needs approval - flag it.
- **Relocation** = `Employee Relocation` type; needs the authorising contract attached.
- **Receipts**: itemised receipts are expected (especially meals & entertainment); a card-statement
  line is not a substitute.
- **Never auto-submit** - the tool stops at "Summary and Submit" and the user clicks it.

---

## Why JavaScript-drive the form?

The form is server-postback heavy and fights pixel-clicking (native dropdowns ignore option clicks,
amount fields garble, the page scroll-traps). Setting field `.value` directly and letting PeopleSoft's
postbacks build the accounting is far faster and more reliable. See RUNBOOK §0 and
`peoplesoft-toolkit.js`. A bulk import/API would be faster still, but CBRE doesn't expose one to
employees and "My Wallet" only holds corporate-card-fed items - so JS-driving the form is the
practical optimum.
