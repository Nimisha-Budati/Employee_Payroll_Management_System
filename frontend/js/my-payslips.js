(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api } = App;
  await App.boot({ role: 'EMPLOYEE', nav: 'payslips' });
  const thisYear = new Date().getFullYear();
  let year = thisYear;
  $('#year').innerHTML = html`${Array.from({ length: 6 }, (_, i) => thisYear - i).map(y => html`<option value="${y}">${y}</option>`)}`;

  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(6, 4);
    try {
      const { results, totals } = await api.get('/payroll/payslips/', { year });
      $('#stats').innerHTML = html`
        <div class="card stat"><span class="stat-icon green">${icon('wallet')}</span><div><div class="stat-label">Net received in ${year}</div><div class="stat-value">${fmt.compactMoney(totals.net)}</div><div class="stat-note">${results.length} payslip${results.length === 1 ? '' : 's'}</div></div></div>
        <div class="card stat"><span class="stat-icon">${icon('rupee')}</span><div><div class="stat-label">Gross earnings</div><div class="stat-value">${fmt.compactMoney(totals.gross)}</div><div class="stat-note">${fmt.money(totals.gross, { decimals: 0 })}</div></div></div>
        <div class="card stat"><span class="stat-icon amber">${icon('layers')}</span><div><div class="stat-label">Deductions</div><div class="stat-value">${fmt.compactMoney(totals.deductions)}</div><div class="stat-note">PF, tax, loss of pay</div></div></div>`;
      rows.innerHTML = results.length ? html`${results.map(slip => html`<tr>
        <td class="cell-main">${fmt.months[slip.month - 1]} ${slip.year}</td>
        <td class="right num">${fmt.money(slip.gross_earnings)}</td><td class="right num">${fmt.money(slip.total_deductions)}</td>
        <td class="right num"><strong>${fmt.money(slip.net_salary)}</strong></td><td>${fmt.date(slip.paid_at)}</td>
        <td><div class="actions"><button class="btn btn-sm" type="button" data-view="${slip.id}">${icon('eye', 'icon-sm')} View</button><button class="btn btn-sm" type="button" data-dl="${slip.id}">${icon('download', 'icon-sm')} PDF</button></div></td></tr>`)}`
        : App.emptyRow(6, { iconName: 'receipt', title: `No payslips for ${year}`, text: 'Payslips appear here after your administrator finalises payroll for a month.' });
      $$('[data-view]', rows).forEach(b => b.addEventListener('click', () => {
        const slip = results.find(s => String(s.id) === b.dataset.view);
        App.modal({ title: 'Payslip', subtitle: slip.period_label, wide: true, cancelLabel: 'Close', body: App.payslipHtml(slip) });
      }));
      $$('[data-dl]', rows).forEach(b => b.addEventListener('click', () => {
        const slip = results.find(s => String(s.id) === b.dataset.dl);
        App.download(`/payroll/payslips/${slip.id}/pdf/`, `payslip_${slip.employee_code}_${slip.year}-${String(slip.month).padStart(2, '0')}.pdf`);
      }));
    } catch (error) {
      $('#stats').innerHTML = '';
      rows.innerHTML = App.errorRow(6, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
    }
  }
  $('#year').addEventListener('change', e => { year = Number(e.target.value); load(); });
  load();
})();
