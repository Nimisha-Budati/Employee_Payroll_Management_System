(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  const user = await App.boot({ nav: 'overtime' });
  const admin = user.role === 'ADMIN';
  $('#searchIcon').innerHTML = icon('search');
  $('#searchBox').hidden = !admin;
  if (!admin) $('#lead').textContent = 'Claim overtime you worked. Only overtime approved by an administrator is added to your payslip.';

  const now = new Date();
  const state = { year: now.getFullYear(), month: now.getMonth() + 1, page: 1, pageSize: 10, search: '', status: '' };
  $('#month').innerHTML = html`${fmt.months.map((name, index) => html`<option value="${index + 1}"${index + 1 === state.month ? App.raw(' selected') : ''}>${name}</option>`)}`;
  $('#year').innerHTML = html`${Array.from({ length: 6 }, (_, i) => now.getFullYear() - i).map(y => html`<option value="${y}">${y}</option>`)}`;
  $('#actions').innerHTML = admin
    ? html`<button class="btn" id="excelBtn" type="button">${icon('spreadsheet')} Excel</button><button class="btn" id="generateBtn" type="button">${icon('refresh')} From attendance</button><button class="btn btn-primary" id="newBtn" type="button">${icon('plus')} Record overtime</button>`
    : html`<button class="btn btn-primary" id="newBtn" type="button">${icon('plus')} Claim overtime</button>`;
  const cols = admin ? 9 : 8;
  $('#head').innerHTML = html`<tr>${admin ? html`<th>Employee</th>` : ''}<th>Date</th><th class="right">Hours</th><th class="right">Rate</th><th class="right">Amount</th><th>Source</th><th>Reason</th><th>Status</th><th class="right">Actions</th></tr>`;
  const SOURCES = { REQUEST: 'Employee claim', MANUAL: 'Admin entry', ATTENDANCE: 'From attendance' };

  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(cols, 5);
    try {
      const data = await api.get('/overtime/', { year: state.year, month: state.month, status: state.status, search: state.search, page: state.page, page_size: state.pageSize });
      if (!data.results.length && state.page > 1) { state.page -= 1; return load(); }
      const t = data.totals;
      $('#stats').innerHTML = html`
        <div class="card stat"><span class="stat-icon">${icon('layers')}</span><div><div class="stat-label">Records</div><div class="stat-value">${t.count}</div><div class="stat-note">${fmt.period(state.year, state.month)}</div></div></div>
        <div class="card stat"><span class="stat-icon amber">${icon('clock')}</span><div><div class="stat-label">Pending approval</div><div class="stat-value">${t.pending}</div><div class="stat-note">Not paid until approved</div></div></div>
        <div class="card stat"><span class="stat-icon blue">${icon('timer')}</span><div><div class="stat-label">Approved hours</div><div class="stat-value">${fmt.number(t.approved_hours)}</div><div class="stat-note">Included in payroll</div></div></div>
        <div class="card stat"><span class="stat-icon green">${icon('rupee')}</span><div><div class="stat-label">Approved amount</div><div class="stat-value">${fmt.compactMoney(t.approved_amount)}</div><div class="stat-note">${fmt.money(t.approved_amount)}</div></div></div>`;
      rows.innerHTML = data.results.length ? html`${data.results.map(r => html`<tr>
        ${admin ? html`<td><div class="cell-main">${r.employee_name}</div><div class="cell-sub mono">${r.employee_code}</div></td>` : ''}
        <td class="nowrap">${fmt.date(r.date)}</td><td class="right num">${fmt.number(r.hours)}</td><td class="right num">${fmt.money(r.rate)}</td>
        <td class="right num"><strong>${fmt.money(r.amount)}</strong></td><td>${SOURCES[r.source] || r.source}</td>
        <td style="max-width:260px"><div class="truncate" title="${r.reason}">${r.reason || '—'}</div>${r.review_note ? html`<div class="cell-sub">Note: ${r.review_note}</div>` : ''}</td>
        <td>${App.badge(r.status)}${r.reviewed_by_name ? html`<div class="cell-sub">by ${r.reviewed_by_name}</div>` : ''}</td>
        <td><div class="actions">${actions(r)}</div></td></tr>`)}`
        : App.emptyRow(cols, { iconName: 'timer', title: state.status || state.search ? 'No overtime matches your filters' : `No overtime in ${fmt.period(state.year, state.month)}`, text: admin ? 'Record overtime, approve employee claims, or create pending records from attendance.' : 'Use "Claim overtime" for extra hours you worked.' });
      const find = id => data.results.find(r => String(r.id) === id);
      $$('[data-approve]', rows).forEach(b => b.addEventListener('click', () => approve(find(b.dataset.approve))));
      $$('[data-reject]', rows).forEach(b => b.addEventListener('click', () => reject(find(b.dataset.reject))));
      $$('[data-edit]', rows).forEach(b => b.addEventListener('click', () => openForm(find(b.dataset.edit))));
      $$('[data-cancel]', rows).forEach(b => b.addEventListener('click', () => cancel(find(b.dataset.cancel))));
      App.pager($('#pager'), { page: state.page, count: data.count, pageSize: state.pageSize }, page => { state.page = page; load(); });
    } catch (error) {
      rows.innerHTML = App.errorRow(cols, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
      $('#pager').hidden = true;
    }
  }

  function actions(r) {
    if (r.status !== 'PENDING') return html`<span class="muted">—</span>`;
    const common = html`<button class="btn btn-sm" type="button" data-edit="${r.id}">${icon('edit', 'icon-sm')}</button><button class="btn btn-sm" type="button" data-cancel="${r.id}">Cancel</button>`;
    return admin ? html`<button class="btn btn-sm btn-success" type="button" data-approve="${r.id}">${icon('check', 'icon-sm')} Approve</button><button class="btn btn-sm btn-danger" type="button" data-reject="${r.id}">${icon('x', 'icon-sm')} Reject</button>${common}` : common;
  }

  async function openForm(record) {
    const editing = Boolean(record);
    let employees = [];
    if (admin && !editing) {
      try { employees = await api.get('/employees/', { status: 'ACTIVE' }); } catch (error) { return App.error(error); }
    }
    const r = record || {};
    App.modal({
      title: editing ? 'Edit overtime' : admin ? 'Record overtime' : 'Claim overtime', submitLabel: editing ? 'Save changes' : admin ? 'Save' : 'Submit claim',
      subtitle: editing && admin ? `${r.employee_name} · ${r.employee_code}` : '',
      body: html`<div class="form-grid">
        ${admin && !editing ? field({ label: 'Employee', name: 'employee_id', type: 'select', options: employees.map(e => [e.user_id, `${e.full_name} · ${e.employee_id}`]), span2: true }) : ''}
        ${field({ label: 'Date worked', name: 'date', type: 'date', value: r.date || App.todayISO(), required: true, attrs: `max="${App.todayISO()}"` })}
        ${field({ label: 'Hours', name: 'hours', type: 'number', value: r.hours || '', required: true, attrs: 'min="0.25" max="16" step="0.25"', hint: 'Quarter-hour steps.' })}
        ${admin ? field({ label: 'Rate per hour (₹)', name: 'rate', type: 'number', value: r.rate || '', attrs: 'min="0" step="0.01"', hint: editing ? '' : 'Leave empty to use the overtime rate from the salary structure.' }) : ''}
        ${field({ label: 'Reason / work done', name: 'reason', type: 'textarea', value: r.reason, required: true, span2: true, attrs: 'maxlength="500"' })}
        ${admin && !editing ? field({ label: 'Approve now (otherwise it stays pending)', name: 'approve', type: 'checkbox', value: true, span2: true }) : ''}
      </div>`,
      onSubmit: async (formData, ctx) => {
        const payload = { date: formData.get('date'), hours: formData.get('hours'), reason: formData.get('reason') };
        if (admin && formData.get('rate')) payload.rate = formData.get('rate');
        if (editing) await api.patch(`/overtime/${r.id}/`, payload);
        else {
          if (admin) { payload.employee_id = Number(formData.get('employee_id')); payload.approve = formData.get('approve') === 'on'; }
          await api.post('/overtime/', payload);
        }
        ctx.close(); App.toast(editing ? 'Overtime updated.' : admin ? 'Overtime recorded.' : 'Overtime claim submitted.'); load();
      },
    });
  }

  async function approve(r) {
    const ok = await App.confirm({ title: 'Approve overtime?', message: `${r.employee_name}: ${fmt.number(r.hours)} h on ${fmt.date(r.date)} = ${fmt.money(r.amount)}. It will be included when payroll for that month is run or recalculated.`, confirmLabel: 'Approve' });
    if (!ok) return;
    try { await api.put(`/overtime/${r.id}/review/`, { status: 'APPROVED' }); App.toast('Overtime approved.'); load(); } catch (error) { App.error(error); }
  }

  function reject(r) {
    App.modal({
      title: 'Reject overtime', subtitle: `${r.employee_name} · ${fmt.date(r.date)}`, submitLabel: 'Reject', submitVariant: 'danger',
      body: html`<div class="form-grid">${field({ label: 'Reason (shown to the employee)', name: 'review_note', type: 'textarea', required: true, span2: true, attrs: 'maxlength="300"' })}</div>`,
      onSubmit: async (formData, ctx) => { await api.put(`/overtime/${r.id}/review/`, { status: 'REJECTED', review_note: formData.get('review_note') }); ctx.close(); App.toast('Overtime rejected.'); load(); },
    });
  }

  async function cancel(r) {
    const ok = await App.confirm({ title: 'Cancel this overtime?', message: `${fmt.number(r.hours)} h on ${fmt.date(r.date)} will be cancelled.`, confirmLabel: 'Cancel overtime', danger: true });
    if (!ok) return;
    try { await api.delete(`/overtime/${r.id}/`); App.toast('Overtime cancelled.'); load(); } catch (error) { App.error(error); }
  }

  async function generate() {
    const period = fmt.period(state.year, state.month);
    const ok = await App.confirm({ title: `Create overtime from attendance for ${period}?`, message: 'For every check-in/check-out longer than the employee\'s shift (or the standard day), a PENDING overtime record is created in quarter hours. Days that already have overtime are skipped. Nothing is paid until you approve.', confirmLabel: 'Create pending records' });
    if (!ok) return;
    try {
      const result = await api.post('/overtime/generate/', { year: state.year, month: state.month });
      App.toast(`${result.created} pending record${result.created === 1 ? '' : 's'} created${result.skipped_finalised ? `, ${result.skipped_finalised} skipped (payroll finalised)` : ''}.`);
      load();
    } catch (error) { App.error(error); }
  }

  $('#newBtn').addEventListener('click', () => openForm(null));
  if (admin) {
    $('#generateBtn').addEventListener('click', generate);
    $('#excelBtn').addEventListener('click', () => {
      const last = new Date(state.year, state.month, 0).getDate();
      const mm = String(state.month).padStart(2, '0');
      App.download('/reports/excel/overtime/', `overtime_${state.year}-${mm}.xlsx`, { from: `${state.year}-${mm}-01`, to: `${state.year}-${mm}-${last}`, status: state.status });
    });
  }
  $('#month').addEventListener('change', e => { state.month = Number(e.target.value); state.page = 1; load(); });
  $('#year').addEventListener('change', e => { state.year = Number(e.target.value); state.page = 1; load(); });
  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); state.page = 1; load(); }));
  $('#statusFilter').addEventListener('change', e => { state.status = e.target.value; state.page = 1; load(); });
  load();
})();
