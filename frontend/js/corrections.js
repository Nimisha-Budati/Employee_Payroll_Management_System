(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  await App.boot({ role: 'ADMIN', nav: 'corrections' });
  $('#searchIcon').innerHTML = icon('search');
  const TYPES = [
    ['MISSED_CHECK_IN', 'Missed check-in'], ['MISSED_CHECK_OUT', 'Missed check-out'],
    ['WRONG_TIMES', 'Incorrect times'], ['MISSED_DAY', 'Worked, no attendance'],
  ];
  $('#type').innerHTML = html`<option value="">All types</option>${TYPES.map(([v, l]) => html`<option value="${v}">${l}</option>`)}`;
  const state = { page: 1, pageSize: 15, status: 'PENDING', search: '', type: '', department: '', from: '', to: '' };
  try {
    const meta = await api.get('/employees/meta/');
    $('#department').innerHTML = html`<option value="">All departments</option>${meta.departments.map(d => html`<option value="${d}">${d}</option>`)}`;
  } catch (error) { /* department filter stays at "All" */ }

  const clock = value => (value ? fmt.time(value) : '—');
  const day = value => (value ? new Date(value).toDateString() : '');
  // Show the date too when a time falls on a different day from the attendance date (overnight shifts).
  const stamp = (value, date) => (!value ? html`<span class="subtle">—</span>` : day(value) !== new Date(`${date}T00:00:00`).toDateString() ? `${fmt.date(value)} ${clock(value)}` : clock(value));

  async function loadStats() {
    try {
      const counts = await Promise.all(['PENDING', 'APPROVED', 'REJECTED'].map(s => api.get('/attendance/corrections/', { status: s, page: 1, page_size: 1 })));
      const [pending, approved, rejected] = counts.map(c => c.count);
      $('#stats').innerHTML = html`
        <div class="card stat"><span class="stat-icon amber">${icon('clock')}</span><div><div class="stat-label">Pending</div><div class="stat-value">${pending}</div><div class="stat-note">Waiting for your decision</div></div></div>
        <div class="card stat"><span class="stat-icon green">${icon('check')}</span><div><div class="stat-label">Approved</div><div class="stat-value">${approved}</div><div class="stat-note">Attendance updated</div></div></div>
        <div class="card stat"><span class="stat-icon">${icon('x')}</span><div><div class="stat-label">Rejected</div><div class="stat-value">${rejected}</div><div class="stat-note">With a reason</div></div></div>
        <a class="card stat" href="admin-audit.html?module=Attendance"><span class="stat-icon blue">${icon('activity')}</span><div><div class="stat-label">Audit trail</div><div class="stat-value">${approved + rejected}</div><div class="stat-note">Decisions recorded</div></div></a>`;
    } catch (error) { $('#stats').innerHTML = ''; }
  }

  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(7, 5);
    try {
      const data = await api.get('/attendance/corrections/', {
        status: state.status, search: state.search, correction_type: state.type, department: state.department,
        from: state.from, to: state.to, page: state.page, page_size: state.pageSize,
      });
      if (!data.results.length && state.page > 1) { state.page -= 1; return load(); }
      rows.innerHTML = data.results.length ? html`${data.results.map(c => {
        const recordedIn = c.status === 'PENDING' ? (c.current_check_in || c.original_check_in) : c.original_check_in;
        const recordedOut = c.status === 'PENDING' ? (c.current_check_out || c.original_check_out) : c.original_check_out;
        return html`<tr>
        <td><div class="cell-main">${c.employee_name}</div><div class="cell-sub mono">${c.employee_code}${c.department ? ` · ${c.department}` : ''}</div></td>
        <td class="nowrap">${fmt.date(c.date)}<div class="cell-sub">sent ${fmt.relative(c.created_at)}</div></td>
        <td style="min-width:200px;max-width:320px"><div>${c.correction_type_label}</div><div class="cell-sub">${c.reason}</div></td>
        <td class="nowrap"><div>In ${stamp(recordedIn, c.date)}</div><div>Out ${stamp(recordedOut, c.date)}</div></td>
        <td class="nowrap"><div>In <strong>${c.requested_check_in ? stamp(c.requested_check_in, c.date) : 'unchanged'}</strong></div><div>Out <strong>${c.requested_check_out ? stamp(c.requested_check_out, c.date) : 'unchanged'}</strong></div></td>
        <td>${App.badge(c.status)}${c.review_note ? html`<div class="cell-sub">${c.review_note}</div>` : ''}${c.reviewed_at ? html`<div class="cell-sub">${c.reviewed_by_name} · ${fmt.dateTime(c.reviewed_at)}</div>` : ''}</td>
        <td><div class="actions">${c.status === 'PENDING' ? html`<button class="btn btn-sm btn-success" type="button" data-approve="${c.id}">Approve</button><button class="btn btn-sm btn-danger" type="button" data-reject="${c.id}">Reject</button>` : ''}</div></td>
      </tr>`;
      })}` : App.emptyRow(7, state.status === 'PENDING' && !state.search && !state.type && !state.department
        ? { iconName: 'checkCircle', title: 'No pending correction requests', text: 'Requests from employees appear here.' }
        : { iconName: 'search', title: 'No requests match these filters', text: 'Try a different status or filter.' });
      const find = id => data.results.find(c => String(c.id) === id);
      $$('[data-approve]', rows).forEach(b => b.addEventListener('click', () => decide(find(b.dataset.approve), 'APPROVED')));
      $$('[data-reject]', rows).forEach(b => b.addEventListener('click', () => decide(find(b.dataset.reject), 'REJECTED')));
      App.pager($('#pager'), { page: state.page, count: data.count, pageSize: state.pageSize }, page => { state.page = page; load(); });
    } catch (error) {
      rows.innerHTML = App.errorRow(7, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
      $('#pager').hidden = true;
    }
  }

  function decide(c, decision) {
    const approve = decision === 'APPROVED';
    App.modal({
      title: approve ? 'Approve correction' : 'Reject correction', subtitle: `${c.employee_name} · ${fmt.date(c.date)}`,
      submitLabel: approve ? 'Approve and update attendance' : 'Reject request', submitVariant: approve ? 'success' : 'danger',
      body: html`<div class="form-grid">
        <dl class="kv span-2">
          <dt>Request</dt><dd>${c.correction_type_label}</dd>
          <dt>Reason</dt><dd>${c.reason}</dd>
          <dt>Check-in</dt><dd>${stamp(c.current_check_in || c.original_check_in, c.date)} → <strong>${c.requested_check_in ? stamp(c.requested_check_in, c.date) : 'unchanged'}</strong></dd>
          <dt>Check-out</dt><dd>${stamp(c.current_check_out || c.original_check_out, c.date)} → <strong>${c.requested_check_out ? stamp(c.requested_check_out, c.date) : 'unchanged'}</strong></dd>
        </dl>
        ${approve ? html`<div class="span-2 alert alert-info">${icon('info')}<span>The attendance record is updated, marked as corrected, and late minutes are recalculated from the employee's shift.</span></div>` : ''}
        ${field({ label: approve ? 'Note to the employee (optional)' : 'Reason (shown to the employee)', name: 'review_note', type: 'textarea', required: !approve, span2: true, attrs: 'maxlength="1000"' })}
      </div>`,
      onSubmit: async (formData, ctx) => {
        await api.post(`/attendance/corrections/${c.id}/review/`, { status: decision, review_note: formData.get('review_note') || '' });
        ctx.close(); App.toast(approve ? 'Correction approved; attendance updated.' : 'Correction rejected.'); load(); loadStats();
      },
    });
  }

  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); state.page = 1; load(); }));
  ['status', 'type', 'department', 'from', 'to'].forEach(id => {
    $(`#${id}`).addEventListener('change', e => { state[id] = e.target.value; state.page = 1; load(); });
  });
  load(); loadStats();
})();
