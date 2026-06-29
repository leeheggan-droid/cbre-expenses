# CBRE Expenses — tools & notes

Tools and runbook for entering CBRE PeopleSoft expense reports fast and correctly.
Personal details (employee ID, client contacts) live in `personal/` — gitignored, never committed.

| File | What it is |
|---|---|
| **RUNBOOK.md** | The rules + step-by-step procedure + every field ID + gotchas. **Start here.** |
| **peoplesoft-toolkit.js** | Pasteable `PS` JavaScript helpers (run in the page console / automation). |
| **tools/** | Offline Python pipeline: bank statement -> normalized -> classified -> review table. |
| **schema/** | `expenses.schema.json` — the data contract passed between pipeline stages. |
| **samples/** | Synthetic (no-PII) example statement, roster, run-config, bank-mapping. |

## Automated flow (the tool)

Feed it a bank statement (primary) ± receipts (secondary) ± an attendee roster; it parses,
classifies per the CBRE rules, shows a **GATE 1** review table, and (once you approve) drives the live
PeopleSoft form via the Claude-in-Chrome session, stopping at **GATE 2** (Summary and Submit) for you.

Offline pipeline (no PeopleSoft, safe to run anytime):

```
python tools/parse_statement.py samples/bank-sample.csv --out run/lines.json
python tools/classify.py       run/lines.json --run-config samples/run-config.example.json \
                               --roster personal/attendees.json --out run/classified.json
python tools/reconcile.py      run/classified.json --receipts run/receipts.json --out run/reconciled.json
python tools/preview.py        run/classified.json --out run/approved.json   # GATE 1 table
```

Real inputs (bank exports, receipts, your roster) go under gitignored `personal/`. Tests: `python tests/test_cbre_lib.py`.

## The short version

- **Why JS:** the form is server-postback heavy and fights pixel-clicking. Driving it with
  JavaScript (set field `.value`, let PeopleSoft's postbacks build the accounting) is ~10× faster
  and reliable. See RUNBOOK §0.
- **Non-negotiable CBRE rules:** Govt Exp = **No** on every line; Default Location = a CBRE **office**
  code; client meals need **attendees + a 50/50 `529200`/`529300` split**; accommodation via CTM;
  relocation = `Employee Relocation` (needs approval + receipts). Full list in RUNBOOK §1.
- **Never auto-submit** — the user clicks "Summary and Submit".

## Related data (local only — gitignored)
- Your reconciliation spreadsheet, receipt images, and supporting documents live locally.
  See `.gitignore` for the full exclusion list.

## Could it be even better?
The genuinely faster path would be a bulk import / API, but CBRE doesn't expose one to employees, and
"My Wallet" only holds corporate-card-fed items (not the separate Uber account). So **JS-driving the
form is the practical optimum**. If CBRE ever enables a spreadsheet/Quick-Fill import, revisit.
