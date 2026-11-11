/* Shared payslip rendering — PayFlow-style.
   Single continuous table: earnings → Gross earnings (bold) → deductions → Total deductions (bold) → Net pay (dark row).
   Header section (outside table): brand · name · period · annual package · shared rates.  */
(function () {
  'use strict';
  const { html, fmt } = App;

  /* ── Helpers ────────────────────────────────────────────────────────────── */

  /** Indian rupee format, e.g. ₹1,00,000 or ₹750 (no trailing .00 for whole numbers). */
  function inr(value) {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency', currency: 'INR',
      minimumFractionDigits: 0, maximumFractionDigits: 2,
    }).format(Number(value || 0));
  }

  /** Sum of all fixed monthly salary components (same as SalaryStructure.COMPONENT_FIELDS). */
  function monthlyGross(slip) {
    return ['basic', 'hra', 'da', 'conveyance_allowance', 'medical_allowance', 'special_allowance', 'other_allowance']
      .reduce((s, f) => s + Number(slip[f] || 0), 0);
  }

  /** Annual package = monthly component gross × 12. */
  function annualPackage(slip) {
    return monthlyGross(slip) * 12;
  }

  /**
   * "Shared rates: PF 10%; TDS 4%; professional tax 6%; other 0.75%."
   *
   * PF is stored as a percentage (pf_percent).
   * TDS, professional tax and other are stored as fixed monthly amounts;
   * we express them as a percentage of the monthly component gross so the
   * rates line matches the reference format exactly.
   */
  function ratesLine(slip) {
    const gross = monthlyGross(slip);
    const parts = [];

    const pf = Number(slip.pf_percent || 0);
    if (pf) parts.push(`PF ${fmt.number(pf)}%`);

    if (gross > 0) {
      const tds = Number(slip.tds || 0);
      const pt  = Number(slip.professional_tax || 0);
      const oth = Number(slip.other_deduction || 0);
      const pct = v => fmt.number(parseFloat((v / gross * 100).toFixed(2)));
      if (tds) parts.push(`TDS ${pct(tds)}%`);
      if (pt)  parts.push(`professional tax ${pct(pt)}%`);
      if (oth) parts.push(`other ${pct(oth)}%`);
    }

    return parts.length ? `Shared rates: ${parts.join('; ')}.` : '';
  }

  /* ── Main renderer ──────────────────────────────────────────────────────── */

  App.payslipHtml = function payslipHtml(slip) {
    const annual = annualPackage(slip);
    const rates  = ratesLine(slip);
    const lop    = Number(slip.lop_days || 0);

    /* One <tr> helper — no indentation, bold/divider/net are style variants only. */
    function row(label, amount, { bold = false, divider = false, net = false } = {}) {
      const cls = ['pf-row', bold ? 'pf-bold' : '', divider ? 'pf-divider' : '', net ? 'pf-net' : '']
        .filter(Boolean).join(' ');
      return html`<tr class="${cls}"><td class="pf-label">${label}</td><td class="pf-amount">${inr(amount)}</td></tr>`;
    }

    /* ── Earnings rows (non-zero only, except Annual package always shown) ── */
    const earningDefs = [
      ['Annual package',   annual],
      ['Basic',            slip.basic],
      ['HRA',              slip.hra],
      ['Dearness allowance', slip.da],
      ['Conveyance allowance', slip.conveyance_allowance],
      ['Medical allowance',   slip.medical_allowance],
      ['Special allowance',   slip.special_allowance],
      ['Other allowance',     slip.other_allowance],
      [`Overtime (${fmt.number(slip.overtime_hours)} h)`, slip.overtime_pay],
      ['Bonus',            slip.bonus],
    ].filter(([label, amt]) => Number(amt || 0) !== 0 || label === 'Annual package');

    /* ── Deduction rows (Unpaid leave always shown even at ₹0) ── */
    const deductDefs = [
      ['Provident fund (PF)',  slip.pf],
      ['Income tax (TDS)',     slip.tds],
      ['Professional tax',     slip.professional_tax],
      ['Other deductions',     slip.other_deduction],
      [`Unpaid leave (${fmt.number(lop)} day${lop === 1 ? '' : 's'})`, slip.lop_deduction],
    ].filter(([label, amt]) => Number(amt || 0) !== 0 || label.startsWith('Unpaid leave'));

    const earnRows   = earningDefs.map(([l, a]) => row(l, a));
    const grossRow   = row('Gross earnings',   slip.gross_earnings,  { bold: true, divider: true });
    const deductRows = deductDefs.map(([l, a]) => row(l, a));
    const totalRow   = row('Total deductions', slip.total_deductions, { bold: true, divider: true });
    const netRow     = row('Net pay',          slip.net_salary,       { bold: true, net: true });

    /* Compact attendance line shown below the table */
    const attnParts = slip.working_days ? [
      `${slip.working_days} working days`,
      `${fmt.number(slip.paid_days)} paid`,
      ...(lop ? [`${fmt.number(lop)} unpaid`] : []),
    ] : [];

    return html`<div class="pf-slip">

      <div class="pf-brand">PayFlow</div>

      <div class="pf-hero">
        <div class="pf-name">${slip.employee_name} · ${slip.period_label}</div>
        <div class="pf-status-block">${App.badge(slip.status)}${slip.paid_at ? html`<div class="pf-paid-on">Paid ${fmt.date(slip.paid_at)}</div>` : ''}</div>
      </div>

      ${annual ? html`<p class="pf-annual">Annual package: ${inr(annual)}</p>` : ''}
      ${rates  ? html`<p class="pf-rates">${rates}</p>` : ''}

      <table class="pf-table">
        <thead>
          <tr><th class="pf-th-label">Description</th><th class="pf-th-amount">Amount</th></tr>
        </thead>
        <tbody>
          ${earnRows}
          ${grossRow}
          ${deductRows}
          ${totalRow}
          ${netRow}
        </tbody>
      </table>

      <p class="pf-meta">${[slip.employee_code, slip.designation, slip.department, ...attnParts].filter(Boolean).join(' · ')}</p>
      ${slip.notes ? html`<p class="pf-note">Note: ${slip.notes}</p>` : ''}

      <div class="pf-actions">
        <button class="btn btn-sm pf-print-btn" type="button" onclick="
          const el = this.closest('.pf-slip');
          const win = window.open('', '_blank', 'width=680,height=900');
          const styles = Array.from(document.querySelectorAll('link[rel=stylesheet]')).map(l => l.outerHTML).join('');
          win.document.write('<html><head>' + styles + '<style>body{padding:28px 32px;max-width:620px;margin:0 auto}.pf-actions{display:none!important}</style></head><body>' + el.outerHTML + '</body></html>');
          win.document.close(); win.focus(); setTimeout(function(){ win.print(); }, 400);
        ">🖨 Print</button>
      </div>

    </div>`;
  };
})();
