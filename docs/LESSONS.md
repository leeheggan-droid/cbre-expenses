# Lessons learned - auditor send-backs and what they changed

Every entry here came from a real rejection or a real trap. Each rule has an executable guard
in `tools/presubmit_checks.py` (tested in `tests/test_presubmit_checks.py`); a rule without a
guard is a wish, not a control. Run the checks on a **dump of the live report** before the
employee presses Summary and Submit - the auditor reads what is in PeopleSoft, not the plan.

No amounts, report IDs, names or receipts in this file; the repo is public.

## Send-back, September 2026 (HK entity, four comments on one report)

| Auditor comment (paraphrased) | Rule now enforced | Guard |
|---|---|---|
| "Incomplete taxi details - please indicate the destination (start point - end point) or purpose of travel." | Every ground-transport line states the route or the purpose in its description. Ride e-receipts carry pickup and drop-off; copy them in. "Grab - City" is not a description. | Rule 1 |
| "The document provided is only a credit card slip, which is not considered an official receipt/invoice. Provide the official supporting document, or the special approval for a missing receipt." | A card terminal slip never counts as evidence. Hotel bars and restaurants paid at the till need an itemised tax invoice - ask the outlet on the night, or request one from the hotel afterwards. Record the evidence type per line. | Rule 2 |
| "If this expense relates to a meal, revise the expense type to Meal Expense." | A bar or restaurant charge is a meal type even when the merchant is the hotel. Lodging is for room nights only. | Rule 3 |
| "Accommodation and meal expenses were combined in the bill and should be split accordingly. Create a new expense line." | A hotel folio is split into room (Lodging) and food & drink (meal type) BEFORE filing. Allocate the settled card amount pro rata at the card's own rate (settled amount / folio total) so the two lines sum exactly to the charge. Record `folio_fb` on every lodging line, zero when the folio is clean. | Rule 4 |

What it cost: one full review cycle (five days), a second pass through PeopleSoft, and a
chase to the hotel for an invoice that could have been requested at checkout.

## Operational traps met while fixing it (PeopleSoft, Claude-in-Chrome)

- **The send-back email quotes the displayed line number**, which is neither the UI row index
  nor the position in the plan. Map by date + amount + currency + merchant before editing.
- **A date change is a postback.** Setting several fields on a new row in one script loses
  everything after the date. Set the date, wait, verify, then the rest one field at a time.
- **Committing the attendee dialog blanks the line's merchant** (and can reset currency).
  Re-read and re-set both after OK, then save.
- **Changing a line's expense type resets its Government Expense radio.** Expand the line and
  re-select No after every type change; a saved total proves nothing about that flag.
- **The totals figure is transient mid-edit.** A total read between a type change and the
  currency re-set was thousands off; the same total read after Save was exact. Only trust a
  total read after a completed Save.
- **`Page.captureScreenshot` times out while PeopleSoft re-renders.** Verify through DOM reads
  and never re-click a control because a screenshot failed - that is how duplicate rows appear.
- **Anchor buttons (attendee +, dialog OK, insert line, Save for Later) need a real mouse click**
  at coordinates resolved from `getBoundingClientRect` immediately beforehand. JS `.click()` on
  them does nothing; JS value + `change` event works for text inputs and selects.
- **The modal iframe lives in the TOP document**, not inside the target-content frame. Look in
  both, take the last visible `ptModFrame_*`.
- **Save regularly** - the component times out at roughly fifteen minutes.
- **The attachment dialog is cross-origin.** The portal page is on one host and the expense
  component, its attendee dialogs and the File Attachment dialog are served from another. The
  page script can reach the form only while the tool's execution context sits inside that
  frame; after a hung call the context re-binds to the top page and every frame reads as
  `contentDocument === null`. A synthesized click on the file input does not open the native
  chooser, a localhost fetch is blocked by the private-network permission prompt, and opening
  the component host top-level lands on a raw sign-in page. Re-entering the portal URL in the
  same tab can trip the access-policy gate ("evaluation already in progress" then a logout).
  **Do all line edits first and save.** Then, on a FRESH portal load (the injected script reaches
  the cross-origin frames until a call hangs), upload with the clipboard route below: it worked
  end to end and the attachment persisted after Save for Later.
- **Clipboard paste moves bytes into a page without passing them through the model.** Put the
  base64 on the OS clipboard, focus a scratch textarea inside the target frame and send a real
  Ctrl+V; 460 KB arrived intact. Useful whenever a same-origin file input is reachable.

## Evidence rules that survive every entity

- Ride-hailing and hotel lines: the emailed e-receipt or folio, always. Photos are for meals
  and bars only, and a photo of a card slip is still a card slip.
- Bank FX fees: one line per report, evidence = the full card statements with every claimed fee
  highlighted and a cover table that adds up to the line. See `tools/` for the builder.
- One folio can settle several card charges; one PDF can evidence many lines. Coverage is
  every line mapped to appropriate evidence, not file count = line count.
