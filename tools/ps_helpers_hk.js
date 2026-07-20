/* ============================================================================
 * CBRE PeopleSoft — HK-module supplementary helpers
 * ----------------------------------------------------------------------------
 * Inject AFTER peoplesoft-toolkit.js (it uses that file's `window.PS`). These
 * helpers encode the quirks documented in docs/HK-MODULE.md §3:
 *   - postback completion via ICStateNum (partial/Ajax postbacks; spinner never
 *     goes "quiet", so a MutationObserver approach fails)
 *   - reliable blank-line add (new line inserts at index 1; select renders late)
 *   - newest-VISIBLE attendee modal frame (stale ptModFrames accumulate & fool
 *     a naive PS.modal())
 *   - content-based line lookup (line $indexes reshuffle on save)
 *
 * HARD-WON RULES (can't be coded around; the driver must obey):
 *   - PeopleSoft ANCHOR BUTTONS (modal OK `PSFT_CLOSE_MODAL$0`, attendee "+"/"-")
 *     ignore JS .click(). Press them with a REAL mouse click (computer tool).
 *     Setting field .value via JS works fine.
 *   - Committing attendees RESETS that line's currency + merchant. Re-set both
 *     right before PS.save().
 *   - A JS eval killed at 45s KEEPS RUNNING in-page -> make bulk ops idempotent
 *     (skip a line whose amount+merchant already exists) and poll to quiescence
 *     before the next action, or you get DUPLICATE lines.
 *   - Save often: the component times out ~15 min; each save persists lines and
 *     keeps the session alive. Recover a timeout via the page's
 *     "return to your most recent active page" link (the draft survives).
 * ============================================================================ */
(function () {
  const D = () => PS.doc();
  window.sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  window.setF = (doc, id, v) => {
    const e = doc.getElementById(id); if (!e) return false;
    e.value = v; ['input', 'change', 'blur'].forEach((t) => e.dispatchEvent(new Event(t, { bubbles: true })));
    return true;
  };

  /* ICStateNum increments once per completed server postback. */
  window.stateNum = () => {
    const d = D();
    const e = d.getElementById('ICStateNum') || d.querySelector('input[name="ICStateNum"]');
    return e ? e.value : null;
  };
  /* Fire a postback, resolve when ICStateNum ticks (or maxMs). Returns ms, or -1 on timeout. */
  window.postback = async (fireFn, maxMs = 8000) => {
    const s0 = stateNum(); fireFn(); const t0 = Date.now();
    while (Date.now() - t0 < maxMs) {
      await sleep(90);
      const s = stateNum();
      if (s !== null && s !== s0) { await sleep(150); return Date.now() - t0; }
    }
    return -1;
  };

  /* Add a blank expense line and return its (freshly-rendered) $index, or -1. */
  window.addBlank = async () => {
    const before = PS.audit().lineCount;
    await postback(() => PS.addLine());
    for (let w = 0; w < 25; w++) {
      const d = D();
      if (PS.audit().lineCount > before) {
        for (let i = 0; i < 120; i++) { const s = d.getElementById('EXPENSE_TYPE$' + i); if (s && s.value === '') return i; }
      }
      await sleep(150);
    }
    return -1;
  };

  /* Find a line by transaction amount (+ optional merchant prefix); returns {i,type,ccy,merch,date}. */
  window.findLine = (amount, merchant) => {
    const d = D(); const want = parseFloat(String(amount));
    for (let i = 0; i < 120; i++) {
      const a = d.getElementById('TRANS_AMT1$' + i); if (!a) continue;
      if (Math.abs(parseFloat(String(a.value).replace(/,/g, '')) - want) < 0.005) {
        const m = d.getElementById('MERCHANT$' + i)?.value || '';
        const pre = String(merchant || '').toLowerCase().slice(0, 5);
        if (!merchant || m.toLowerCase().startsWith(pre) || m === '') {
          return { i, type: d.getElementById('EXPENSE_TYPE$' + i)?.value, ccy: d.getElementById('EX_SHEET_LINE_TXN_CURRENCY_CD$' + i)?.value, merch: m, date: d.getElementById('TRANS_DATE$' + i)?.value };
        }
      }
    }
    return null;
  };

  /* Newest VISIBLE attendee modal document (ignores stale/hidden ptModFrames). */
  window.vmodal = () => {
    let found = null;
    for (const f of document.querySelectorAll('iframe')) {
      try {
        if (!f.offsetParent) continue;
        const cd = f.contentDocument;
        const ok = cd.getElementById('PSFT_CLOSE_MODAL$0');
        if (ok && ok.offsetParent && [...cd.querySelectorAll('input')].some((e) => /EX_SHEET_ATT_NAME/i.test(e.id))) found = cd;
      } catch (e) { /* cross-origin/detached */ }
    }
    return found;
  };
  window.vframe = () => { const m = vmodal(); for (const f of document.querySelectorAll('iframe')) { try { if (f.offsetParent && f.contentDocument === m) return f; } catch (e) {} } return null; };

  /* Remove orphan attendee modal frames (call between meals when NO real modal should be open). */
  window.cleanAttFrames = () => {
    let n = 0;
    document.querySelectorAll('iframe').forEach((f) => {
      try {
        const cd = f.contentDocument;
        if (cd && [...cd.querySelectorAll('input')].some((e) => /EX_SHEET_ATT_NAME/i.test(e.id))) {
          (f.closest('div[id^="ptModContainer"]') || f.parentElement || f).remove(); n++;
        }
      } catch (e) {}
    });
    return n;
  };

  /* Fill blank attendee rows in the current modal (JS is fine for fields).
     people = [{name:"Surname,First", company, title}]. Add the rows FIRST with real "+" clicks. */
  window.fillAttendeeRows = (people) => {
    const m = vmodal(); if (!m) return 'no visible modal';
    const blanks = [...m.querySelectorAll('input[id^="EX_SHEET_ATT_NAME$"]')].filter((n) => !n.value).map((n) => n.id.match(/\$(\d+)$/)[1]);
    people.forEach((p, k) => { const i = blanks[k]; if (i == null) return; setF(m, 'EX_SHEET_ATT_NAME$' + i, p.name); setF(m, 'EX_SHEET_ATT_ATTENDEE_COMPANY$' + i, p.company); setF(m, 'EX_SHEET_ATT_TITLE$' + i, p.title || ''); });
    return [...m.querySelectorAll('input[id^="EX_SHEET_ATT_NAME$"]')].map((n) => n.value);
  };

  /* Is the BU-36120 permission error dialog showing? (dismiss with a real click on its OK) */
  window.hasBuError = () => {
    for (const f of document.querySelectorAll('iframe')) {
      try { const cd = f.contentDocument; if (cd && f.offsetParent && [...cd.querySelectorAll('*')].some((e) => /36120|permission list|Error statement/i.test(e.textContent || ''))) return true; } catch (e) {}
    }
    return false;
  };

  console.log('ps_helpers_hk loaded: postback(), addBlank(), findLine(), vmodal(), fillAttendeeRows(), hasBuError(), cleanAttFrames(). See docs/HK-MODULE.md.');
})();
