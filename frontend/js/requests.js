/* Leave and work-from-home requests for both roles. Configured through data-role / data-kind on <body>. */
(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  const role = document.body.dataset.role;
  const kind = document.body.dataset.kind;
  const admin = role === 'ADMIN';
  const leave = kind === 'leave';
  await App.boot({ role, nav: leave ? 'leave' : 'wfh' });

  const state = { page: 1, pageSize: 10, search: '', status: '' };
  let balanceData = null;   // leave types and balances come from the leave policy configured by administrators
  const columns = (admin ? 1 : 0) + 5 + 1;

  $('#searchIcon').innerHTML = icon('search');
  $('#searchBox').hidden = !admin;
  $('#head').innerHTML = html`<tr>${admin ? html`<th>Employee</th>` : ''}${leave ? html`<th>Type</th>` : ''}<th>Dates</th><th class="right">Days</th><th>Reason</th><th>Status</th><th class="right">Actions</th></tr>`;
  const cols = admin ? (leave ? 7 : 6) : (leave ? 6 : 5);
  if (!admin) $('#actions').innerHTML = html`<button class="btn btn-primary" id="newBtn" type="button">${icon('plus')} ${leave ? 'Apply for leave' : 'Request WFH'}</button>`;

  async function loadBalances() {
    if (!leave || admin) return;
    const box = $('#balances');
    try {
      balanceData = await api.get('/leaves/balance/');
      box.hidden = false;
      const entries = Object.entries(balanceData.balances);
      box.innerHTML = html`<div class="card-header"><div><h2>My leave balance</h2><p>Leave year ${balanceData.label} · set by your administrator</p></div></div>
        <div class="table-wrap"><table class="table"><thead><tr><th>Leave type</th><th class="right">Total allowed</th><th class="right">Used</th><th class="right">Pending</th><th class="right">Available</th></tr></thead><tbody>
        ${entries.length ? entries.map(([type, b]) => html`<tr>
          <td><div class="cell-main">${type}</div><div class="cell-sub">${b.is_paid ? 'Paid' : 'Unpaid (loss of pay)'}${b.carried_forward ? ` · ${b.carried_forward} carried forward` : ''}${b.adjustment ? ` · ${b.adjustment > 0 ? '+' : ''}${b.adjustment} adjusted` : ''}</div></td>
          <td class="right num">${b.unlimited ? html`<span class="muted">No limit</span>` : b.total}</td>
          <td class="right num">${fmt.number(b.approved)}</td>
          <td class="right num">${Number(b.pending) ? html`<span class="badge badge-warning">${fmt.number(b.pending)}</span>` : '0'}</td>
          <td class="right num">${b.unlimited ? '—' : html`<strong>${fmt.number(b.available)}</strong>${Number(b.pending) ? html`<div class="cell-sub">${fmt.number(b.remaining)} can be requested</div>` : ''}`}</td></tr>`)
          : html`<tr><td colspan="5">${App.empty({ iconName: 'calendar', title: 'No leave types yet', text: 'Your administrator has not set up any leave types.' })}</td></tr>`}
        </tbody></table></div>`;
    } catch (error) { box.hidden = true; }
  }

  function dates(item) {
    return item.start_date === item.end_date ? fmt.date(item.start_date) : `${fmt.date(item.start_date)} – ${fmt.date(item.end_date)}`;
  }

  function rowHtml(item) {
    const note = leave ? item.rejection_reason : item.admin_note;
    return html`<tr>
      ${admin ? html`<td><div class="cell-main">${item.employee_username}</div>${leave ? html`<div class="cell-sub mono">${item.employee_code}</div>` : ''}</td>` : ''}
      ${leave ? html`<td>${item.leave_type}</td>` : ''}
      <td class="nowrap">${dates(item)}</td>
      <td class="right num">${item.number_of_days}</td>
      <td style="max-width:280px"><div class="truncate" title="${item.reason}">${item.reason || '—'}</div>${note ? html`<div class="cell-sub">${admin ? 'Note' : 'Response'}: ${note}</div>` : ''}</td>
      <td>${App.badge(item.status)}</td>
      <td><div class="actions">${actions(item)}</div></td>
    </tr>`;
  }

  function actions(item) {
    if (admin && item.status === 'PENDING') {
      return html`<button class="btn btn-sm btn-success" type="button" data-approve="${item.id}">${icon('check', 'icon-sm')} Approve</button><button class="btn btn-sm btn-danger" type="button" data-reject="${item.id}">${icon('x', 'icon-sm')} Reject</button>`;
    }
    if (!admin && item.status === 'PENDING') return html`<button class="btn btn-sm" type="button" data-cancel="${item.id}">Cancel</button>`;
    return html`<span class="muted">—</span>`;
  }

  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(cols, 5);
    try {
      let list, count;
      const params = { status: state.status };
      if (leave) {
        Object.assign(params, { page: state.page, page_size: state.pageSize, search: state.search });
        const data = await api.get('/leaves/', params);
        if (!data.results.length && state.page > 1) { state.page -= 1; return load(); }
        list = data.results; count = data.count;
      } else {
        const all = await api.get('/wfh/', admin ? { ...params, search: state.search } : params);
        count = all.length;
        const start = (state.page - 1) * state.pageSize;
        list = all.slice(start, start + state.pageSize);
      }
      rows.innerHTML = list.length ? html`${list.map(rowHtml)}` : App.emptyRow(cols, state.status || state.search
        ? { iconName: 'search', title: 'No requests match your filters', text: 'Try a different search or clear the filters.' }
        : { iconName: leave ? 'calendar' : 'home', title: admin ? 'No requests yet' : 'You have not made any requests', text: admin ? 'Requests from employees will appear here for review.' : 'Use the button above to submit your first request.' });
      $$('[data-approve]', rows).forEach(b => b.addEventListener('click', () => approve(list.find(i => String(i.id) === b.dataset.approve))));
      $$('[data-reject]', rows).forEach(b => b.addEventListener('click', () => reject(list.find(i => String(i.id) === b.dataset.reject))));
      $$('[data-cancel]', rows).forEach(b => b.addEventListener('click', () => cancel(list.find(i => String(i.id) === b.dataset.cancel))));
      App.pager($('#pager'), { page: state.page, count, pageSize: state.pageSize }, page => { state.page = page; load(); });
    } catch (error) {
      rows.innerHTML = App.errorRow(cols, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
      $('#pager').hidden = true;
    }
  }

  const endpoint = item => (leave ? `/leaves/${item.id}/status/` : `/wfh/${item.id}/`);

  async function approve(item) {
    const who = item.employee_username;
    const ok = await App.confirm({ title: 'Approve request?', message: `${who}'s request for ${dates(item)} (${item.number_of_days} day${item.number_of_days === 1 ? '' : 's'}) will be approved and they will be notified.`, confirmLabel: 'Approve' });
    if (!ok) return;
    try { await api.put(endpoint(item), { status: 'APPROVED' }); App.toast('Request approved.'); load(); } catch (error) { App.error(error); }
  }

  function reject(item) {
    App.modal({
      title: 'Reject request', subtitle: `${item.employee_username} · ${dates(item)}`, submitLabel: 'Reject request', submitVariant: 'danger',
      body: html`<div class="form-grid">${field({ label: leave ? 'Reason (shown to the employee)' : 'Note (required, shown to the employee)', name: 'note', type: 'textarea', required: !leave, span2: true, attrs: 'maxlength="300"' })}</div>`,
      onSubmit: async (formData, ctx) => {
        const note = (formData.get('note') || '').trim();
        await api.put(endpoint(item), leave ? { status: 'REJECTED', rejection_reason: note } : { status: 'REJECTED', admin_note: note });
        ctx.close(); App.toast('Request rejected.'); load();
      },
    });
  }

  async function cancel(item) {
    const ok = await App.confirm({ title: 'Cancel request?', message: `Your request for ${dates(item)} will be cancelled.`, confirmLabel: 'Cancel request', danger: true });
    if (!ok) return;
    try { await api.delete(leave ? `/leaves/${item.id}/` : `/wfh/${item.id}/`); App.toast('Request cancelled.'); load(); loadBalances(); } catch (error) { App.error(error); }
  }

  async function openNew() {
    const today = App.todayISO();
    let types = [];
    if (leave) {
      try { [types] = await Promise.all([api.get('/leave-types/'), loadBalances()]); } catch (error) { App.error(error); return; }
      if (!types.length) { App.toast('No leave types are available. Please contact an administrator.', 'error'); return; }
    }
    const balanceOf = name => (balanceData && balanceData.balances[name]) || null;
    const optionLabel = t => {
      const b = balanceOf(t.name);
      if (t.annual_days === null) return `${t.name} — ${t.is_paid ? 'paid' : 'unpaid'}, no limit`;
      return `${t.name} — ${b ? b.remaining : t.annual_days} day${(b ? b.remaining : t.annual_days) === 1 ? '' : 's'} can be requested`;
    };
    App.modal({
      title: leave ? 'Apply for leave' : 'Request work from home',
      submitLabel: 'Submit request',
      body: html`<div class="form-grid">
        ${leave ? field({ label: 'Leave type', name: 'leave_type', type: 'select', options: types.map(t => [t.name, optionLabel(t)]), span2: true }) : ''}
        ${leave ? html`<div class="span-2 alert alert-info" id="typeInfo" role="status"></div>` : ''}
        ${field({ label: 'From', name: 'start_date', type: 'date', value: today, required: true })}
        ${field({ label: 'To', name: 'end_date', type: 'date', value: today, required: true })}
        ${field({ label: 'Reason', name: 'reason', type: 'textarea', required: true, span2: true, attrs: 'maxlength="500"' })}
      </div>`,
      onOpen: ({ form }) => {
        if (!leave) return;
        const info = () => {
          const t = types.find(item => item.name === form.elements.leave_type.value);
          const b = t && balanceOf(t.name);
          const start = form.elements.start_date.value, end = form.elements.end_date.value;
          const requested = start && end && end >= start ? Math.round((new Date(`${end}T00:00:00`) - new Date(`${start}T00:00:00`)) / 86400000) + 1 : 0;
          const over = t && t.annual_days !== null && b && requested > b.remaining;
          $('#typeInfo').className = `span-2 alert ${over || (end && start && end < start) ? 'alert-warning' : 'alert-info'}`;
          $('#typeInfo').innerHTML = html`${icon(over ? 'alert' : 'info')}<span>${t ? html`<strong>${t.name}</strong>: ${t.is_paid ? 'paid' : 'unpaid — these days are deducted from your salary'}.
            ${t.annual_days === null ? 'No annual limit.' : b ? `${b.available} of ${b.total} days available${b.pending ? `, ${b.pending} pending` : ''}; you can request ${b.remaining}.` : ''}
            ${t.description ? ` ${t.description}` : ''}` : ''}
            ${end && start && end < start ? html`<br>The end date cannot be before the start date.` : requested ? html`<br>This request is <strong>${requested} day${requested === 1 ? '' : 's'}</strong> (calendar days).` : ''}
            ${over ? html`<br>That is more than you can request for this leave type.` : ''}</span>`;
        };
        ['leave_type', 'start_date', 'end_date'].forEach(name => form.elements[name].addEventListener('change', info));
        info();
      },
      onSubmit: async (formData, ctx) => {
        await api.post(leave ? '/leaves/' : '/wfh/', Object.fromEntries(formData));
        ctx.close(); App.toast('Request submitted.'); state.page = 1; load(); loadBalances();
      },
    });
  }

  const newBtn = $('#newBtn'); if (newBtn) newBtn.addEventListener('click', openNew);
  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); state.page = 1; load(); }));
  $('#statusFilter').addEventListener('change', e => { state.status = e.target.value; state.page = 1; load(); });
  loadBalances();
  load();
})();
