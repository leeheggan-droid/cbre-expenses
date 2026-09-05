# Driving the PeopleSoft expense form - measured notes

Observed on the HK form on 2026-09-05. This is operational guidance, not a universal
expense policy. Confirm the employee's entity, approved plan and live controls.
Keep report IDs, names, card details, statements and receipts in gitignored `personal/`.
Read this before `RUNBOOK.md`'s older console examples or `docs/HK-MODULE.md` helpers.

## Choose the browser adapter before touching the form

The dashboard and expense form use both `myhcm.cbre.com` and `myfin.cbre.com`.
The main content is `iframe#ptifrmtgtframe`, name `TargetContent`; its document can
be on a different origin from the outer page. Authorize the browser integration on
both hosts when required. An accessible screenshot does not prove DOM access.

- With CUA/Playwright locators, use `frameLocator('iframe[name="TargetContent"]')`.
  Use supported `fill`, `selectOption`, `check`, `click` and file-chooser actions.
  Evaluate is for reading DOM-backed values only when the adapter restricts it to
  read-only work. Do not inject `PS`, assign `.value`, call page postback functions,
  or work around that restriction through another browser transport.
- The console / Claude-in-Chrome toolkit is an alternative only when that adapter
  permits script mutations. Its historical `contentDocument` access is not a
  cross-origin solution and does not work in every browser environment.
- Read the adapter's supplied API documentation. A method available in ordinary
  Playwright is not necessarily exposed by a restricted integration.

## Report and row identity

Header IDs: `EX_SHEET_HDR_BUSINESS_PURPOSE`, `EX_SHEET_HDR_SHEET_NAME`,
`EX_LOCATION_VW2_DESCR`, `EX_SHEET_HDR_REFERENCE_ID`.
Per-row IDs end in `$n`: `TRANS_DATE`, `EXPENSE_TYPE`, `DESCR`, `TRANS_AMT1`,
`EX_SHEET_LINE_TXN_CURRENCY_CD`, `MERCHANT`, `PAYMENT_TYPE`,
`EX_SHEET_LINE_BILL_CODE_EX`. Treat these IDs as observed hints; inspect the live page.

**The suffix is a current UI position, not a stable expense identifier.** Inserts
shift rows; reopening a saved report can reorder them again. Before every mutation,
match date + amount + currency + merchant + type against the approved source line.
If that tuple is ambiguous, inspect further before writing. Refresh the private
source-ID-to-UI-position map after inserts and reloads. Never resume by old index
or by re-adding every source line. The displayed expense line number may differ
from both the UI suffix and the attendee prompt's line number.

## Add one complete line at a time

1. Save the header and record the assigned report ID privately.
2. Insert once (`EX_LINE_WRK_EX_INSERT_LNPB$n`), then find the newly blank row.
   Blank rows can be discarded on save; do not pre-add an entire batch.
3. Fill date, description and amount using supported input actions. Select the
   expense type and allow its postback/attendee dialog to finish.
4. Read and, if necessary, reapply currency and merchant **after** the type change
   and attendee dialog. These fields can reset during those transitions.
5. Save for Later (`ER_TOOLBAR#SAVE`) and inspect the resulting values and errors.

The observed date format was DD/MM/YYYY; verify the locale with a day above 12.
Enter the bank-settled transaction amount in its own currency. PeopleSoft converts
to the report currency; do not pre-convert. Reconcile each currency separately.
Use the approved payment/billing types for this employee, not another user's defaults.

## Postbacks, timeouts and false success

A successful click or helper status does not prove the requested change completed.
A subsequent click while Save is processing can silently do nothing. A timed-out
call may already have changed the form. Before retrying a write:

1. Take a fresh UI read and inspect visible modals.
2. Verify the expected result: new row, saved field, attachment entry, or modal close.
3. Continue only after the transition has completed. If incomplete, retry only
   the missing action, not the whole batch.

Fixed two-second sleeps alone are insufficient. A Processing indicator can be
transient; verify the resulting controls as well. Long loops of radio changes or
modal operations can exhaust the browser call time limit and reset the session.
Use small batches, verify each outcome, save, and rebind the tab/frame after a reset.
Do not assume requested timeout options override a provider's shorter action limit.

## Attendees and entity-specific accounting

HK `MEAL50` and `MEAL100` open/require attendees. A meal-type change or save may open
a modal automatically. While it is open, main-form actions can silently do nothing.
The employee is prefilled; accepting that alone can unblock a draft, but does not
mean the full attendee roster is complete.

Discover the visible `iframe[name^="ptModFrame_"]` after each transition. Its suffix
changes; it is not the expense row. Distinguish Attendees, report Attachments and
the nested File Attachment dialog by their visible contents.

Attendee fields: `EX_SHEET_ATT_NAME$n`, `EX_SHEET_ATT_ATTENDEE_COMPANY$n`, optional
`EX_SHEET_ATT_TITLE$n`. Fill a row, click its observed Add button, wait for the new
row, then fill it. Use the modal's `PSFT_CLOSE_MODAL$0` OK action to return. Save and
reopen the same expense's attendee dialog to verify persistence. Do not infer an
unknown company from a name; use source records or ask the employee.

Client attendance does **not** imply an AU 50/50 split for every entity. Apply a
split only when required by the employee's applicable rules and approved plan.
Request self/client GL accounts only for a split that is actually needed. Existing
HK no-split runs are examples, not an exemption for every HK employee.

## Required fields and validation

- HK lodging uses `NBR_NIGHTS$n`. Save for Later can preserve a draft with missing
  values and show `ERROR_ICON$n`: open it and read the actual error. A saved total
  is not evidence of a validation-clean report.
- Derive nights from the folio's arrival/departure dates. Separate payments toward
  one folio must reconcile to that folio and explicitly identify the same stay.
  Do not invent extra nights or change a bar/meal to lodging to clear a field.
  If an ancillary charge's approved category makes the nights field ambiguous,
  resolve the category/field meaning rather than entering an arbitrary count.
- For the approved non-government expenses, expand the rows and set Government
  Expense No, then verify checked values on every line after saving. Do not blindly
  reuse a previous employee's government/billing classification.
- Check errors after save, amounts/currencies, held exclusions, duplicate claims,
  the full attendee roster and receipt coverage before calling a draft complete.

## Receipt reconciliation is evidence, not filename counting

Match bank amount/original currency, merchant, date, payment card and reference to
the original receipt. A receipt-only item is a review candidate, not a new claim.
When references differ, record both without changing the original document. Inspect
the original email/receipt, check for competing charges, and ask the employee to
resolve uncertain matches. A plausible timezone explanation is not proof of how
the bank assigns dates. Preserve user-confirmed exceptions in a private audit and
in an attachment note; do not turn an exception into a global matching rule.

One folio can support several payments, and one indexed PDF can support many lines.
Coverage means every claimed line maps to appropriate evidence, not that the number
of physical files equals the number of lines. Bank fees can use the original bank
fee entries. Keep settled fee amounts consistent with the plan and avoid claiming
fees both inside a converted charge and again as a separate line.

## Uploads work through the supported file chooser

Header Attachments (`EX_HDR_WRK_ATTACHMENTS_PB`) opens Expense Report Attachments.
Its tips specify **less than 10 MB total per report**, simple short filenames with
letters, numbers and underscores, and **Save for Later after uploading**. Check the
live limit for other entities/versions. Use a clear source-line/page index in a
combined PDF; keep receipt content legible, uncropped and unaltered.

Measured CUA upload sequence (use current discovered frames, not fixed suffixes):

1. Open header Attachments, then Add Attachment (`ATT_PNLS_WRK_ATTACHADD`).
2. Inspect the new File Attachment frame. Its genuine file input was
   `input[type="file"][name="#ICOrigFileName"]`.
3. Register the tab's filechooser wait **before** clicking that input:

   ```js
   const pending = tab.playwright.waitForEvent('filechooser', { timeoutMs: 10000 });
   await uploadFrame.locator('input[type="file"]').click();
   const chooser = await pending;
   await chooser.setFiles([absolutePdfPath]);
   await uploadFrame.getByRole('button', { name: 'Upload', exact: true }).click();
   ```

4. Wait for the upload to return to the attachment list. Verify the filename and
   displayed size. Fill `ATTACH_DESCR$n`, choose that dialog's OK, then Save for Later.
5. Reopen Attachments to confirm the file and description persisted. File-chooser
   success alone is not proof of upload or save. `setInputFiles` and reading
   `input.files` were not supported by the measured adapter; use the documented API.
6. When replacing a pack, upload and verify the replacement before removing the old
   one (provided both fit under the total limit). Delete confirmation says removal
   occurs when saved. Save and recheck that only the intended final file remains.

An old session's missing permission on `myfin` does not make uploads universally
manual. Check the current integration; use its upload troubleshooting documentation
if needed. If the environment blocks the chooser or access, hand off that specific
step without attempting another transport around the restriction.

## Handover

Save, then report draft ID, status, line count, source-currency totals, displayed
reimbursement total, attachment coverage and any unresolved decisions. Update the
private run state so the next assistant does not duplicate lines or rely on stale
indices. Leave final submission to the employee; do not click Summary and Submit.
