# Usage - running an expense report end to end

Two operator modes lead to the same place: an approved entry plan that the
`cbre-expense-autofill` skill types into PeopleSoft, stopping at "Summary and Submit" for you.

- **Hard way** - the automatic parse + triage + review pipeline.
- **Easy way** - an Excel template you fill in by hand.

Throughout, `$PY` is the interpreter:

```
$PY = C:\Users\jacks\AppData\Local\Programs\Python\Python313\python.exe
```

Real inputs and outputs live under gitignored `personal/runs/<run>/`. The examples here use the
synthetic, no-PII files in `samples/` and a throwaway `run\` directory, so you can rehearse the whole
chain safely.

---

## One-time setup

Copy the samples to your private (gitignored) copies and edit them:

```
copy samples\roster.example.json     personal\attendees.json
copy samples\triage.example.json     personal\triage.json
```

- `personal/attendees.json` - your recurring client reps, one key per client. The key you reference
  as `clientKey` in a run-config must exist here, or meals are proposed without attendees.
- `personal/triage.json` - your `personalMerchants` (always excluded) and `businessMerchants`
  (treated as business travel even without a foreign currency). Keeps your local merchant names out of
  the public repo.

Per report, also make a run-config:

```
mkdir personal\runs\2026-06-bali
copy samples\run-config.example.json personal\runs\2026-06-bali\run-config.json
# edit clientKey, defaultLocation (a CBRE OFFICE code), businessPurpose, reportDescription
```

---

## Mode A - the hard way (automatic pipeline)

### Stage 0 - gather inputs
Put the bank statement (CSV or PDF) in your run dir. Optionally add a receipts JSON and/or a
My-Wallet JSON. Receipt images are read with Claude-native vision (no external API key) to produce
the receipts JSON - see `tools/parse_receipts.py`.

### Stage 1 - run the offline pipeline
Each stage writes JSON conforming to `schema/expenses.schema.json`.

```
# 1. Statement -> normalized lines
& $PY tools\parse_statement.py samples\bank-sample.csv --out run\lines.json
```
`parse_statement.py` auto-detects common CSV columns; if it misses one, pass
`--config samples\bank-config.example.json` with the exact header names. For PDFs it tries table
extraction, then a text-regex parser (card statements like HSBC), then a coordinate/column parser
(paid-out/paid-in/balance bank-account layouts). Overseas FX fees are folded into the line amount.

```
# 2. (optional) Reconcile receipts + My-Wallet against the bank lines
& $PY tools\reconcile.py run\lines.json --receipts run\receipts.json --wallet run\wallet.json --out run\reconciled.json
```
Omit `--receipts` / `--wallet` if you don't have them yet. The bank statement is the source of truth;
a receipt with no matching bank line is surfaced, not silently claimed, and matched wallet items are
flagged so you don't double-enter corporate-card items.

```
# 3. Triage + propose types/attendees/split
& $PY tools\classify.py run\lines.json --run-config personal\runs\2026-06-bali\run-config.json --roster personal\attendees.json --triage personal\triage.json --out run\classified.json
```
`classify.py` reads the normalized lines. It triages each line into business / personal / uncertain
(using foreign-trip date windows + merchant patterns, with your `personal/triage.json` overrides),
proposes an expense type, and flags client meals that need attendees + the 50/50 `529200`/`529300`
split. `--roster` and `--triage` are optional.

```
# 4. GATE 1 review table + the approved plan
& $PY tools\preview.py run\classified.json --out run\approved.json
```

### GATE 1 - review (required)
`preview.py` prints a grouped table (BUSINESS / UNCERTAIN / PERSONAL), the per-line flags, and the
claimable total, and writes `approved.json`. Walk every flag (unknown types, accommodation -> CTM,
meals needing attendees/split, unparseable dates, wallet duplicates), decide the UNCERTAIN lines, and
edit `approved.json` (or tell the orchestrator the corrections). **Nothing is entered until you
approve.** Example (run on the sample statement):

```
--- BUSINESS - proposed to CLAIM   [3 lines, AUD 85,344.50] ----
#    DATE        MERCHANT                        AMOUNT TYPE     ATT SPLIT RCPT
L001 05/06/2026  UBER *TRIP HELP.UBER.COM         24.50 TAXIBU   -   -     -
L003 06/06/2026  HILTON HOTEL SYDNEY             320.00 ACCDOM   -   -     -
L005 07/06/2026  GRAB *RIDE JAKARTA           85,000.00 TAXIINT  -   -     -
...
```

### Stage 2 - drive PeopleSoft (GATE 2)
Hand the approved plan to the `cbre-expense-autofill` skill. It injects `peoplesoft-toolkit.js`,
pulls My-Wallet items, adds out-of-pocket lines, sets Govt Exp = No on all, adds attendees + the
50/50 split on client meals, and saves after each line. It then **stops at "Summary and Submit"**:
you attach receipts and submit. See `SKILL.md` for the entry procedure and `RUNBOOK.md` for the rules
and field IDs.

---

## Mode B - the easy way (Excel template)

Prefer ticking boxes to reading a generated table? Generate a spreadsheet with dropdowns, fill it in,
and read it back into the same plan.

```
# 1. Generate the template (dropdowns for expense type, business/personal, etc.)
& $PY tools\excel_template.py --out personal\runs\2026-06-bali\plan.xlsx
# (or seed it from parsed lines, e.g. --lines run\lines.json - see the script's --help)

# 2. Fill it in by hand in Excel: confirm each line, pick types, mark personal, add attendees.

# 3. Read it back into the entry plan
& $PY tools\excel_read.py personal\runs\2026-06-bali\plan.xlsx --out run\approved.json
```

The resulting `approved.json` is the same contract Stage 2 consumes, so GATE 2 is identical: the skill
drives PeopleSoft and stops at "Summary and Submit".

---

## Receipts (manual attach)
The Chrome extension is authorised on `myhcm` but **not** `myfin` (where the receipt file-input lives,
in nested iframes), so the tool cannot upload receipts for you. Prepare the receipt bundle
(`parse_receipts.py`: shrink image-PDFs, one image per claim, named to the claim), then download +
attach manually. Verify `#receipts == #lines` before you submit.

## Tests
```
& $PY tests\test_cbre_lib.py
```
