/* Shared payslip rendering used by the admin payroll page and the employee payslips page. */
(function () {
  'use strict';
  const { html, fmt } = App;
  const money = value => fmt.money(value);

  App.payslipHtml = function payslipHtml(slip) {
    const earn = [
      ['Basic', slip.basic], ['House rent allowance', slip.hra], ['Dearness allowance', slip.da], ['Conveyance', slip.conveyance_allowance],
      ['Medical', slip.medical_allowance], ['Special allowance', slip.special_allowance], ['Other allowance', slip.other_allowance],
      ['Overtime' + (Number(slip.overtime_hours) ? ` (${fmt.number(slip.overtime_hours)} h)` : ''), slip.overtime_pay], ['Bonus', slip.bonus],
    ].filter(([, amount]) => Number(amount) !== 0);
    const deduct = [
      [`Provident fund (${fmt.number(slip.pf_percent)}%)`, slip.pf], ['Professional tax', slip.professional_tax], ['Income tax (TDS)', slip.tds],
      ['Other deductions', slip.other_deduction], [`Loss of pay (${fmt.number(slip.lop_days)} day${Number(slip.lop_days) === 1 ? '' : 's'})`, slip.lop_deduction],
    ].filter(([, amount]) => Number(amount) !== 0);
    const line = ([label, amount]) => html`<div class="slip-line"><span>${label}</span><span class="num">${money(amount)}</span></div>`;
    return html`<div class="slip">
      <div class="row" style="justify-content:space-between;align-items:flex-start">
        <div><strong style="font-size:16px">${slip.employee_name}</strong><div class="muted">${slip.employee_code} · ${slip.designation || 'No designation'} · ${slip.department || 'No department'}</div></div>
        <div style="text-align:right">${App.badge(slip.status)}<div class="muted" style="margin-top:4px">${slip.period_label}</div></div>
      </div>
      <dl class="kv" style="grid-template-columns:repeat(3,auto);justify-content:space-between;gap:6px 24px;margin:0">
        <div><dt>Working days</dt><dd style="text-align:left">${slip.working_days}</dd></div>
        <div><dt>Paid days</dt><dd style="text-align:left">${fmt.number(slip.paid_days)}</dd></div>
        <div><dt>Loss of pay days</dt><dd style="text-align:left">${fmt.number(slip.lop_days)}</dd></div>
      </dl>
      <div class="slip-grid">
        <div class="slip-col"><h3>Earnings</h3>${earn.map(line)}<div class="slip-line total"><span>Gross earnings</span><span class="num">${money(slip.gross_earnings)}</span></div></div>
        <div class="slip-col"><h3>Deductions</h3>${deduct.length ? deduct.map(line) : html`<div class="slip-line"><span class="muted">No deductions</span><span>—</span></div>`}<div class="slip-line total"><span>Total deductions</span><span class="num">${money(slip.total_deductions)}</span></div></div>
      </div>
      <div class="slip-net"><span>Net salary</span><strong class="num">${money(slip.net_salary)}</strong></div>
      ${slip.notes ? html`<p class="muted" style="margin:0">Note: ${slip.notes}</p>` : ''}
      ${slip.paid_at ? html`<p class="muted" style="margin:0">Paid on ${fmt.date(slip.paid_at)}</p>` : ''}
    </div>`;
  };
})();
