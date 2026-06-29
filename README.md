# CBRE Expenses — tools & notes

Tools and runbook for entering CBRE PeopleSoft expense reports fast and correctly.
Personal details (employee ID, client contacts) live in `personal/` — gitignored, never committed.

| File | What it is |
|---|---|
| **RUNBOOK.md** | The rules + step-by-step procedure + every field ID + gotchas. **Start here.** |
| **peoplesoft-toolkit.js** | Pasteable `PS` JavaScript helpers (run in the page console / automation). |

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
