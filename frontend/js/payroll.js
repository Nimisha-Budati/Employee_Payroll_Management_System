(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  await App.boot({ role: 'ADMIN', nav: 'payroll' });

  $('#searchIcon').innerHTML = icon('search');
  $('#exportBtn').innerHTML = html`${icon('download')} Export CSV`;
  $('#runBtn').innerHTML = html`${icon('wallet')} Run payroll`;

  // Default to the last finished month.
  const now = new Date();
  const last = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const state = { year: last.getFullYear(), month: last.getMonth() + 1, page: 1, pageSize: 10, search: '', status: '' };

  $('#month').innerHTML = html`${fmt.months.map((name, index) => html`<option value="${index + 1}"${index + 1 === state.month ? App.raw(' selected') : ''}>${name}</option>`)}`;
  const years = Array.from({ length: 6 }, (_, i) => now.getFullYear() - i);
  $('#year').innerHTML = html`${years.map(y => html`<option value="${y}"${y === state.year ? App.raw(' selected') : ''}>${y}</option>`)}`;

  let totals = null;

  function renderStats() {
    const t = totals || { count: 0, gross: 0, deductions: 0, net: 0, drafts: 0, paid: 0 };
    $('#stats').innerHTML = html`
      <div class="card stat"><span class="stat-icon">${icon('users')}</span><div><div class="stat-label">Payslips</div><div class="stat-value">${t.count}</div><div class="stat-note">${t.drafts} draft · ${t.paid} paid</div></div></div>
      <div class="card stat"><span class="stat-icon green">${icon('rupee')}</span><div><div class="stat-label">Gross earnings</div><div class="stat-value">${fmt.compactMoney(t.gross)}</div><div class="stat-note">${fmt.money(t.gross, { decimals: 0 })}</div></div></div>
      <div class="card stat"><span class="stat-icon amber">${icon('layers')}</span><div><div class="stat-label">Deductions</div><div class="stat-value">${fmt.compactMoney(t.deductions)}</div><div class="stat-note">${fmt.money(t.deductions, { decimals: 0 })}</div></div></div>
      <div class="card stat"><span class="stat-icon blue">${icon('wallet')}</span><div><div class="stat-label">Net payable</div><div class="stat-value">${fmt.compactMoney(t.net)}</div><div class="stat-note">${fmt.money(t.net, { decimals: 0 })}</div></div></div>`;
    const finalize = $('#finalizeBtn');
    finalize.hidden = !t.drafts;
    finalize.innerHTML = html`${icon('check')} Review & finalise ${t.drafts} draft${t.drafts === 1 ? '' : 's'}`;
    $('#varianceBtn').hidden = !t.count;
  }

  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(8, 6);
    try {
      const data = await api.get('/payroll/payslips/', { year: state.year, month: state.month, page: state.page, page_size: state.pageSize, search: state.search, status: state.status });
      if (!data.results.length && state.page > 1) { state.page -= 1; return load(); }
      totals = data.totals;
      renderStats();
      const period = fmt.period(state.year, state.month);
      rows.innerHTML = data.results.length ? html`${data.results.map(rowHtml)}` : App.emptyRow(8, state.search || state.status
        ? { iconName: 'search', title: 'No payslips match your filters', text: 'Try a different search or clear the filters.' }
        : { iconName: 'wallet', title: `No payslips for ${period}`, text: 'Use Run payroll to generate draft payslips for this month. Payroll can only be run after the month has ended.' });
      $$('[data-view]', rows).forEach(b => b.addEventListener('click', () => viewSlip(data.results.find(s => String(s.id) === b.dataset.view))));
      $$('[data-adjust]', rows).forEach(b => b.addEventListener('click', () => adjustSlip(data.results.find(s => String(s.id) === b.dataset.adjust))));
      $$('[data-pdf]', rows).forEach(b => b.addEventListener('click', () => App.openFile(`/payroll/payslips/${b.dataset.pdf}/pdf/`, { inline: 1 })));
      App.pager($('#pager'), { page: state.page, count: data.count, pageSize: state.pageSize }, page => { state.page = page; load(); });
    } catch (error) {
      totals = null; renderStats();
      rows.innerHTML = App.errorRow(8, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
      $('#pager').hidden = true;
    }
  }

  function rowHtml(slip) {
    const draft = slip.status === 'DRAFT';
    return html`<tr>
      <td><div class="cell-main">${slip.employee_name}</div><div class="cell-sub mono">${slip.employee_code}</div></td>
      <td>${slip.department || '—'}</td>
      <td class="right num">${fmt.number(slip.paid_days)} / ${slip.working_days}</td>
      <td class="right num">${fmt.money(slip.gross_earnings)}</td>
      <td class="right num">${fmt.money(slip.total_deductions)}</td>
      <td class="right num"><strong>${fmt.money(slip.net_salary)}</strong></td>
      <td>${App.badge(slip.status)}</td>
      <td><div class="actions">
        <button class="btn btn-sm" type="button" data-view="${slip.id}">${icon('eye', 'icon-sm')} View</button>
        ${draft ? html`<button class="btn btn-sm" type="button" data-adjust="${slip.id}">${icon('edit', 'icon-sm')} Adjust</button>` : ''}
        <button class="btn btn-sm" type="button" data-pdf="${slip.id}" aria-label="Open PDF for ${slip.employee_name}">${icon('file', 'icon-sm')} PDF</button>
      </div></td>
    </tr>`;
  }

  function viewSlip(slip) {
    App.modal({ title: 'Payslip', subtitle: slip.period_label, body: App.payslipHtml(slip), wide: true, cancelLabel: 'Close' });
  }

  function adjustSlip(slip) {
    const body = html`<div class="form-grid">
      <div class="span-2 alert alert-info">${icon('info')}<span>Adjusting ${slip.employee_name} · ${slip.period_label}. Net salary is recalculated automatically. Recalculate to discard manual changes.</span></div>
      ${field({ label: 'Loss of pay days', name: 'lop_days', type: 'number', value: slip.lop_days, hint: `Whole or half days, up to ${slip.working_days}.`, attrs: 'min="0" step="0.5"' })}
      ${field({ label: 'Bonus (₹)', name: 'bonus', type: 'number', value: slip.bonus, attrs: 'min="0" step="0.01"' })}
      ${field({ label: 'Other deductions (₹)', name: 'other_deduction', type: 'number', value: slip.other_deduction, attrs: 'min="0" step="0.01"' })}
      ${field({ label: 'Note', name: 'notes', value: slip.notes, span2: true, attrs: 'maxlength="300"' })}
    </div>
    <div style="margin-top:16px"><button class="btn btn-sm" type="button" id="recalc">${icon('refresh', 'icon-sm')} Recalculate from attendance</button> <button class="btn btn-sm btn-danger" type="button" id="deleteSlip">${icon('trash', 'icon-sm')} Delete draft</button></div>`;
    App.modal({
      title: 'Adjust draft payslip', body, wide: true, submitLabel: 'Save adjustments',
      onOpen: ({ dialog, close }) => {
        $('#recalc', dialog).addEventListener('click', async () => {
          const ok = await App.confirm({ title: 'Recalculate payslip?', message: 'This rebuilds the payslip from the current salary structure and attendance and discards manual changes.', confirmLabel: 'Recalculate' });
          if (!ok) return;
          try { await api.post(`/payroll/payslips/${slip.id}/recalculate/`); close(); App.toast('Payslip recalculated.'); load(); } catch (error) { App.error(error); }
        });
        $('#deleteSlip', dialog).addEventListener('click', async () => {
          const ok = await App.confirm({ title: 'Delete this draft?', message: 'The draft payslip is removed. You can generate it again by running payroll.', confirmLabel: 'Delete', danger: true });
          if (!ok) return;
          try { await api.delete(`/payroll/payslips/${slip.id}/`); close(); App.toast('Draft deleted.'); load(); } catch (error) { App.error(error); }
        });
      },
      onSubmit: async (formData, ctx) => {
        await api.patch(`/payroll/payslips/${slip.id}/`, {
          lop_days: formData.get('lop_days') || 0, bonus: formData.get('bonus') || 0,
          other_deduction: formData.get('other_deduction') || 0, notes: formData.get('notes') || '',
        });
        ctx.close(); App.toast('Payslip updated.'); load();
      },
    });
  }

  function runPayroll() {
    const period = fmt.period(state.year, state.month);
    const body = html`<div class="form-grid">
      <div class="span-2 alert alert-info">${icon('info')}<span>Creates <strong>draft</strong> payslips for every active employee with a salary structure for <strong>${period}</strong>. Existing payslips are never overwritten. Nothing is visible to employees until you finalise.</span></div>
      ${field({ label: 'Loss of pay', name: 'lop_mode', type: 'select', span2: true, value: 'ATTENDANCE',
        options: [['ATTENDANCE', 'Calculate from attendance, leave and work-from-home records'], ['NONE', 'Do not deduct for absence (full month)']],
        hint: 'Working days exclude weekends and holidays in the calendar.' })}
    </div>`;
    App.modal({
      title: `Run payroll for ${period}`, body, submitLabel: 'Generate drafts',
      onSubmit: async (formData, ctx) => {
        const result = await api.post('/payroll/run/', { year: state.year, month: state.month, lop_mode: formData.get('lop_mode') });
        ctx.close();
        showRunResult(result);
        load();
      },
    });
  }

  function showRunResult(result) {
    const body = html`<div class="stack-sm">
      <div class="alert ${result.created ? 'alert-success' : 'alert-warning'}">${icon(result.created ? 'check' : 'alert')}<span><strong>${result.created}</strong> draft payslip${result.created === 1 ? '' : 's'} created for ${result.period}.</span></div>
      ${result.skipped.length ? html`<div><strong>${result.skipped.length} skipped</strong><ul class="list" style="margin-top:8px;border:1px solid var(--border);border-radius:var(--radius)">${result.skipped.map(s => html`<li><div class="cell-main">${s.employee}</div><div class="cell-sub">${s.reason}</div></li>`)}</ul></div>` : ''}
    </div>`;
    App.modal({ title: 'Payroll run complete', body, cancelLabel: 'Close' });
  }

  // Finalising happens on the variance review page, which requires a recorded review first.
  function finalize() {
    location.href = `admin-payroll-review.html?year=${state.year}&month=${state.month}`;
  }

  $('#runBtn').addEventListener('click', runPayroll);
  $('#finalizeBtn').addEventListener('click', finalize);
  $('#varianceBtn').innerHTML = html`${icon('trending')} Variance vs last month`;
  $('#varianceBtn').addEventListener('click', finalize);
  $('#exportBtn').addEventListener('click', () => App.download('/payroll/export/', `payroll_${state.year}-${String(state.month).padStart(2, '0')}.csv`, { year: state.year, month: state.month }));
  $('#month').addEventListener('change', e => { state.month = Number(e.target.value); state.page = 1; load(); });
  $('#year').addEventListener('change', e => { state.year = Number(e.target.value); state.page = 1; load(); });
  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); state.page = 1; load(); }));
  $('#statusFilter').addEventListener('change', e => { state.status = e.target.value; state.page = 1; load(); });
  load();
})();
