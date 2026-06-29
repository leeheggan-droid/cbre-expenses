/* ============================================================================
 * CBRE PeopleSoft Expense Report — automation toolkit
 * ----------------------------------------------------------------------------
 * Paste this whole file into the browser DevTools console while on the
 * Create/Modify Expense Report page (or run via an automation javascript_tool).
 * It defines a global `PS` with helpers. See RUNBOOK.md for the full procedure.
 *
 * IMPORTANT timing rule: anything that triggers a PeopleSoft postback
 * (PS.addLine, PS.setType, PS.addDistRow, PS.govtNoAll after expand,
 *  PS.expandAccounting, PS.openWallet/Done, PS.save, attendee add-row/OK)
 * re-renders the page. WAIT ~2 seconds before the next call.
 * Plain-field setters (date/desc/merchant/amount/account) are instant & safe.
 * ============================================================================ */
const PS = (() => {
  const D = () => document.querySelector('iframe[name="TargetContent"]').contentDocument;

  // current open modal (attendees) document, or null
  const MODAL = () => {
    for (const f of document.querySelectorAll('iframe')) {
      try { if ([...f.contentDocument.querySelectorAll('input')]
                 .some(e => /EX_SHEET_ATT_NAME/i.test(e.id))) return f.contentDocument; } catch (e) {}
    }
    return null;
  };

  const fire = el => ['input','change','blur'].forEach(t => el.dispatchEvent(new Event(t,{bubbles:true})));
  const realClick = el => el.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));

  const set = (doc, id, v) => { const e = doc.getElementById(id); if (!e) return false; e.value = v; fire(e); return true; };
  const num = s => parseFloat(String(s||'0').replace(/,/g,'')) || 0;
  // guarded getById: warns instead of throwing when a field/button id is missing
  // (PeopleSoft ids drift between releases; a clear console warning beats a cryptic crash mid-report)
  const G = (doc, id) => { const e = doc.getElementById(id); if (!e) console.warn('[PS] field/button not found: #' + id); return e; };

  return {
    doc: D, modal: MODAL,

    /* ---- discovery ---- */
    dumpExpenseTypes() {
      const sel = G(D(),'EXPENSE_TYPE$0'); if(!sel) return 'no expense-type select on page';
      return [...sel.options].filter(o=>o.text.trim()).map(o=>o.value+' : '+o.text);
    },

    /* ---- whole-report audit (run anytime) ---- */
    audit() {
      const d = D(), lines = [];
      for (let i=0;i<60;i++){ const s=d.getElementById('EXPENSE_TYPE$'+i); if(!s) continue;
        lines.push({ i,
          nbr: d.getElementById('EX_SHEET_LINE_LINE_NBR$'+i)?.textContent.trim(),
          type: s.value,
          date: d.getElementById('TRANS_DATE$'+i)?.value,
          amt:  d.getElementById('TRANS_AMT1$'+i)?.value,
          merch:d.getElementById('MERCHANT$'+i)?.value });
      }
      const dists=[]; for(let n=0;n<60;n++){const a=d.getElementById('EX_SHEET_DIST_ACCOUNT$'+n); if(a) dists.push(a.value+'='+d.getElementById('EX_SHEET_DIST_TXN_AMOUNT$'+n)?.value);}
      return { lineCount: lines.length, lines, dists };
    },

    /* ---- add a blank expense line (POSTBACK, wait 2s) ---- */
    addLine() { const img=G(D(),'EX_LINE_WRK_EX_INSERT_LNPB$IMG$0'); if(!img) return 'add-line button missing (try Collapse All first)'; (img.closest('a')||img).click(); return 'added — wait 2s'; },

    /* ---- fill the newest blank line, then fire the type change (POSTBACK, wait 2s).
       Merchant gets wiped by the type postback — call setMerchantOnBlank() after the wait. ---- */
    fillBlankLine({date, type, amount, desc, merchant}) {
      const d = D();
      let idx=null; for(let i=0;i<60;i++){const s=d.getElementById('EXPENSE_TYPE$'+i); if(s&&s.value===''){idx=i;break;}}
      if(idx===null) return 'no blank line — call addLine() first';
      if(date)   set(d,'TRANS_DATE$'+idx,date);
      if(desc)   set(d,'DESCR$'+idx,desc);
      if(amount) set(d,'TRANS_AMT1$'+idx,String(amount));
      this._pendingMerchant = merchant || null;
      const et=d.getElementById('EXPENSE_TYPE$'+idx); et.value=type; et.dispatchEvent(new Event('change',{bubbles:true}));
      return 'filled line '+idx+' as '+type+' — wait 2s, then PS.applyPendingMerchant()';
    },
    applyPendingMerchant() {
      const d=D(); if(!this._pendingMerchant) return 'none';
      // newest line that has a type but blank merchant
      for(let i=59;i>=0;i--){const s=d.getElementById('EXPENSE_TYPE$'+i); const m=d.getElementById('MERCHANT$'+i);
        if(s&&s.value&&m&&!m.value){ m.value=this._pendingMerchant; fire(m); this._pendingMerchant=null; return 'merchant set on line '+i; }}
      return 'no blank-merchant line found';
    },

    /* ---- change an existing line's type (POSTBACK, wait 2s); re-set merchant after ---- */
    setType(lineIdx, code){ const et=G(D(),'EXPENSE_TYPE$'+lineIdx); if(!et) return 'no expense-type field on line '+lineIdx; et.value=code; et.dispatchEvent(new Event('change',{bubbles:true})); return 'wait 2s'; },
    setMerchant(lineIdx, name){ return set(D(),'MERCHANT$'+lineIdx,name)?'ok':'no field'; },

    /* ---- set a line's transaction currency (POSTBACK, wait 2s). MUST be called AFTER the
       Expense Type change postback — setting it before resets it back to AUD (RUNBOOK §6).
       The type change also wipes Merchant, so re-set merchant after this too. ---- */
    setCurrency(lineIdx, code){ const el=G(D(),'EX_SHEET_LINE_TXN_CURRENCY_CD$'+lineIdx); if(!el) return 'no currency field on line '+lineIdx; el.value=code; el.dispatchEvent(new Event('change',{bubbles:true})); return 'currency '+code+' set on line '+lineIdx+' — wait 2s (own postback)'; },

    /* ---- Govt Exp = No on every line. Run AFTER "Expand All" so the radios are rendered.
       Reads DOM on save; no per-line postback needed. ---- */
    govtNoAll() {
      const d=D(); let setN=0, had=0;
      for(let i=0;i<60;i++){ const no=d.getElementById('CB_EX_LINE_WRK_CB_GOVT_EXP$637$$'+i),
                                   yes=d.getElementById('CB_EX_LINE_WRK_CB_GOVT_EXP$636$$'+i);
        if(!no) continue; if(no.checked){had++;continue;} if(yes) yes.checked=false; no.checked=true; setN++; }
      return {newlyNo:setN, alreadyNo:had};
    },

    /* ---- expand one line's Accounting Details (POSTBACK, wait 2s) ---- */
    expandAccounting(lineIdx){ const el=G(D(),'EX_LINE_WRK_EXPAND_SECTIONS2$'+lineIdx); if(!el) return 'no expand control on line '+lineIdx; el.click(); return 'wait 2s'; },

    /* ---- client-meal 50/50 split. Accounting must be expanded first.
       Step A: addDistRow(lineIdx, fullAmount) -> POSTBACK, wait 2s
       Step B: setSplit(lineIdx, fullAmount, halfA, halfB) ---- */
    addDistRow(lineIdx, fullAmount){
      const d=D(); let distN=null;
      for(let n=0;n<60;n++){const a=d.getElementById('EX_SHEET_DIST_ACCOUNT$'+n); if(!a)continue;
        if(a.value==='529200' && num(d.getElementById('EX_SHEET_DIST_TXN_AMOUNT$'+n)?.value)===num(fullAmount)) distN=n;}
      if(distN===null) return 'dist not found (is accounting expanded? amount '+fullAmount+'?)';
      const btn=d.getElementById('EX_SHEET_DIST$new$'+distN+'$$'+lineIdx);
      if(!btn) return 'add btn EX_SHEET_DIST$new$'+distN+'$$'+lineIdx+' missing';
      btn.click(); this._splitDistN=distN; return 'added on dist '+distN+' — wait 2s, then setSplit()';
    },
    setSplit(lineIdx, fullAmount, halfA, halfB){
      const d=D(); const origN=this._splitDistN;
      let newN=null; for(let n=0;n<60;n++){const a=d.getElementById('EX_SHEET_DIST_ACCOUNT$'+n); if(!a)continue;
        const amt=d.getElementById('EX_SHEET_DIST_TXN_AMOUNT$'+n)?.value;
        if(a.value==='529200' && (amt===''||amt==='0.00') && n>4) newN=n;}
      if(origN==null||newN==null) return 'could not locate rows';
      set(d,'EX_SHEET_DIST_TXN_AMOUNT$'+origN, String(halfA));
      set(d,'EX_SHEET_DIST_TXN_AMOUNT$'+newN,  String(halfB));
      set(d,'EX_SHEET_DIST_ACCOUNT$'+newN, '529300');
      return {keep529200:origN+'='+halfA, client529300:newN+'='+halfB};
    },

    /* ---- attendees. open(lineIdx) POSTBACK->modal. Then addAttendeeRows([...]) then attendeeOK().
       Pattern that survives postbacks: add ALL rows first, fill them, then OK. ---- */
    openAttendees(lineIdx){ const el=G(D(),'EX_LINE_WRK_PB_ATTENDEES$'+lineIdx); if(!el) return 'no attendees link on line '+lineIdx; el.click(); return 'wait 2s'; },
    addAttendeeRow(){ const d=MODAL(); if(!d) return 'no attendee modal open'; const btns=[...d.querySelectorAll('a[id^="EX_SHEET_ATT$new"]')]; if(!btns.length) return 'no add-attendee button in modal'; btns[btns.length-1].click(); return 'wait 2s'; },
    fillAttendeeBlanks(people){ // people: [{name,company,title}]
      const d=MODAL(); if(!d) return 'no attendee modal open'; const blanks=[...d.querySelectorAll('input[id^="EX_SHEET_ATT_NAME$"]')].filter(n=>!n.value).map(n=>n.id.match(/\$(\d+)$/)[1]);
      people.forEach((p,k)=>{ const i=blanks[k]; if(i==null) return;
        set(d,'EX_SHEET_ATT_NAME$'+i,p.name); set(d,'EX_SHEET_ATT_ATTENDEE_COMPANY$'+i,p.company); set(d,'EX_SHEET_ATT_TITLE$'+i,p.title||''); });
      return [...d.querySelectorAll('input[id^="EX_SHEET_ATT_NAME$"]')].map(n=>n.value);
    },
    attendeeOK(){ const d=MODAL(); if(!d) return 'no attendee modal open'; const b=[...d.querySelectorAll('a,input[type=button]')].find(e=>/^\s*OK\s*$/.test(e.textContent||e.value||'')); if(!b) return 'no OK button in modal'; b.click(); return 'wait 2s'; },
    attendeeReturn(){ const d=MODAL(); if(!d) return 'no attendee modal open'; const b=[...d.querySelectorAll('a,input[type=button]')].find(e=>/^\s*Return\s*$/.test(e.textContent||e.value||'')); if(!b) return 'no Return button in modal'; b.click(); return 'wait 2s'; },
    readAttendees(){ const d=MODAL(); if(!d) return 'no attendee modal open'; return [...d.querySelectorAll('input[id^="EX_SHEET_ATT_NAME$"]')].map(n=>{const i=n.id.match(/\$(\d+)$/)[1];return n.value+' / '+(d.getElementById('EX_SHEET_ATT_ATTENDEE_COMPANY$'+i)?.value||'')+' / '+(d.getElementById('EX_SHEET_ATT_TITLE$'+i)?.value||'');}); },

    /* ---- My Wallet. open() POSTBACK. selectAll uses REAL clicks (required). done() POSTBACK. ---- */
    openWallet(){ const w=G(D(),'ADD#MYWALLET'); if(!w) return 'My Wallet link missing'; (w.closest('a')||w).click(); return 'wait 2s'; },
    walletSelectAll(){ let n=0; [...D().querySelectorAll('input[type=checkbox]')].forEach(c=>{ if(/RECEIPT_VERIFIED/i.test(c.id)&&!c.checked){ realClick(c); n++; } }); return 'real-clicked '+n+' select boxes'; },
    walletDone(){ const el=G(D(),'EX_ICLIENT_WRK_OK_LEVEL1_PB'); if(!el) return 'wallet Done button missing'; el.click(); return 'wait 3s'; },

    /* ---- scrolling fix (when header/Save trapped) ---- */
    toTop(){ document.querySelector('iframe[name="TargetContent"]').contentWindow.scrollTo(0,0); },

    /* ---- save (POSTBACK; prompts attendee modals for any client meal missing them) ---- */
    save(){ const el=G(D(),'ER_TOOLBAR#SAVE'); if(!el) return 'Save button missing'; el.click(); return 'wait 3s'; },
  };
})();

/* ---- reference data ----------------------------------------------------- */
PS.CODES = { Taxi:'TAXIBU', TaxiIntl:'TAXIINT', Relocation:'EMPRELO', MealClient:'MEALCLI',
             Subsistence:'SUBSIST', LightRefreshment:'LIGHTRE', AccomDom:'ACCDOM',
             AccomIntl:'ACCINT', TravelOther:'TRAVOTH' };
PS.ACCT = { employee:'529200', client:'529300' };           // client meal split

/* Attendee templates are PII (real client names) and are kept OUT of this public file.
   Load them at runtime from personal/attendees.json (gitignored). One key per client; each
   value is the list of attendee rows for that client's meal modal. Shape:
     PS.TEMPLATES = {
       "ClientKey": [ { name: "Surname,First", company: "ClientName", title: "Role" }, ... ],
     };
   Usage: PS.fillAttendeeBlanks(PS.TEMPLATES[clientKey]) for client / int'l meals.
   In the console you can inject them with:  PS.TEMPLATES = <paste personal/attendees.json>; */
PS.TEMPLATES = {};
/* helper: split AUD amount 50/50 so halves sum exactly, e.g. PS.halves(34.51) -> [17.26,17.25] */
PS.halves = (a)=>{ const c=Math.round(a*100); const x=Math.ceil(c/2), y=c-x; return [x/100, y/100]; };

/* Expose globally so PS persists across separate evals (automation `javascript_tool` runs each call
   in its own scope; `const PS` alone would not survive). DevTools console use is unaffected. */
try { window.PS = PS; } catch (e) {}

console.log('PS toolkit loaded (window.PS). PS.audit() to inspect. See RUNBOOK.md for the procedure.');
