(async function () {
  'use strict';
  const { $, html, icon, fmt, api, field } = App;
  await App.boot({ role: 'ADMIN', nav: 'attendance' });
  $('#searchIcon').innerHTML = icon('search');
  $('#settingsBtn').innerHTML = html`${icon('sliders')} Office location`;
  $('#excelBtn').innerHTML = html`${icon('spreadsheet')} Export Excel`;

  const today = new Date();
  const state = { page: 1, pageSize: 15, search: '', department: '', from: fmt.iso(new Date(today.getFullYear(), today.getMonth(), 1)), to: App.todayISO(), late: '', tab: 'records' };
  $('#from').value = state.from;
  $('#to').value = state.to;

  try {
    const meta = await api.get('/employees/meta/');
    $('#department').innerHTML = html`<option value="">All departments</option>${meta.departments.map(name => html`<option value="${name}">${name}</option>`)}`;
  } catch (error) { /* department filter stays at "All" */ }

  const filters = () => ({ search: state.search, department: state.department, from: state.from, to: state.to, late: state.late });
  const lateCell = minutes => (minutes == null ? html`<span class="muted" title="No shift assigned">—</span>` : minutes > 0 ? html`<span class="badge badge-warning">${minutes} min</span>` : html`<span class="badge badge-success">On time</span>`);

  async function loadSummary() {
    try {
      const data = await api.get('/attendance/', { ...filters(), summary: 'true' });
      const t = data.totals;
      $('#stats').innerHTML = html`
        <div class="card stat"><span class="stat-icon">${icon('users')}</span><div><div class="stat-label">Employees</div><div class="stat-value">${t.employees}</div><div class="stat-note">${t.records} check-ins</div></div></div>
        <div class="card stat"><span class="stat-icon amber">${icon('clock')}</span><div><div class="stat-label">Late check-ins</div><div class="stat-value">${t.late_days}</div><div class="stat-note">${t.records ? Math.round(100 * t.late_days / t.records) : 0}% of check-ins</div></div></div>
        <div class="card stat"><span class="stat-icon amber">${icon('timer')}</span><div><div class="stat-label">Late minutes</div><div class="stat-value">${fmt.number(t.late_minutes)}</div><div class="stat-note">${t.late_days ? Math.round(t.late_minutes / t.late_days) : 0} min average when late</div></div></div>
        <div class="card stat"><span class="stat-icon blue">${icon('briefcase')}</span><div><div class="stat-label">Hours worked</div><div class="stat-value">${fmt.number(Math.round(t.worked_minutes / 60))}</div><div class="stat-note">${fmt.date(state.from)} – ${fmt.date(state.to)}</div></div></div>`;
      if (state.tab === 'summary') {
        $('#summaryRows').innerHTML = data.employees.length ? html`${data.employees.map(r => html`<tr>
          <td><div class="cell-main">${r.employee_name}</div><div class="cell-sub mono">${r.employee_code}</div></td><td>${r.department || '—'}</td>
          <td class="right num">${r.days_present}</td><td class="right num">${r.late_days}</td><td class="right num">${fmt.number(r.late_minutes)}</td>
          <td class="right num">${r.average_late_minutes ? `${r.average_late_minutes} min` : '—'}</td><td class="right num">${fmt.duration(r.worked_minutes)}</td></tr>`)}`
          : App.emptyRow(7, { iconName: 'pin', title: 'No attendance in this period', text: 'Try a wider date range or clear the filters.' });
      }
    } catch (error) {
      $('#stats').innerHTML = '';
      if (state.tab === 'summary') { $('#summaryRows').innerHTML = App.errorRow(7, error.message); $('[data-retry]', $('#summaryRows')).addEventListener('click', load); }
    }
  }

  async function loadRecords() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(9, 6);
    try {
      const data = await api.get('/attendance/', { ...filters(), page: state.page, page_size: state.pageSize });
      if (!data.results.length && state.page > 1) { state.page -= 1; return loadRecords(); }
      const dist = v => (v == null ? '—' : `${v} m`);
      rows.innerHTML = data.results.length ? html`${data.results.map(r => html`<tr>
        <td><div class="cell-main">${r.employee_name}</div><div class="cell-sub mono">${r.employee_code || r.employee_username}</div></td>
        <td class="nowrap">${fmt.date(r.date)}</td><td>${r.shift_name || html`<span class="muted">No shift</span>`}${r.scheduled_start ? html`<div class="cell-sub">starts ${fmt.time(r.scheduled_start)}</div>` : ''}</td>
        <td>${fmt.time(r.check_in_at)}</td><td class="right">${lateCell(r.late_minutes)}</td><td>${r.check_out_at ? fmt.time(r.check_out_at) : '—'}</td>
        <td class="right num">${r.worked_minutes == null ? '—' : fmt.duration(r.worked_minutes)}</td>
        <td class="right num">${dist(r.check_in_distance_meters)} / ${dist(r.check_out_distance_meters)}</td><td>${App.badge(r.status)}</td></tr>`)}`
        : App.emptyRow(9, { iconName: 'pin', title: 'No attendance records', text: state.search || state.department || state.late ? 'Try a different search or filter.' : 'Records appear when employees check in.' });
      App.pager($('#pager'), { page: state.page, count: data.count, pageSize: state.pageSize }, page => { state.page = page; loadRecords(); });
    } catch (error) {
      rows.innerHTML = App.errorRow(9, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
      $('#pager').hidden = true;
    }
  }

  function load() {
    loadSummary();
    if (state.tab === 'records') loadRecords(); else $('#pager').hidden = true;
  }

  function setTab(tab) {
    state.tab = tab;
    $('#tabRecords').setAttribute('aria-selected', String(tab === 'records'));
    $('#tabSummary').setAttribute('aria-selected', String(tab === 'summary'));
    $('#recordsPane').hidden = tab !== 'records';
    $('#summaryPane').hidden = tab !== 'summary';
    load();
  }

  async function openSettings() {
    let s;
    try { s = await api.get('/attendance/settings/'); } catch (error) { return App.error(error); }
    App.modal({
      title: 'Office location', subtitle: 'Employees must be within the radius to check in or out.', submitLabel: 'Save location',
      body: html`<div class="form-grid">
        ${field({ label: 'Latitude', name: 'latitude', type: 'number', value: s.latitude ?? '', required: true, attrs: 'step="any" min="-90" max="90"' })}
        ${field({ label: 'Longitude', name: 'longitude', type: 'number', value: s.longitude ?? '', required: true, attrs: 'step="any" min="-180" max="180"' })}
        ${field({ label: 'Allowed radius (metres)', name: 'radius_meters', type: 'number', value: s.radius_meters ?? 100, required: true, attrs: 'min="10" step="1"' })}
        ${field({ label: 'Attendance enabled', name: 'is_enabled', type: 'checkbox', value: s.is_enabled, span2: true })}
        <div class="span-2"><button class="btn btn-sm" type="button" id="useHere">${icon('pin', 'icon-sm')} Use my current location</button></div>
        <p class="span-2 muted" style="margin:0">Late minutes use each employee's shift (Shifts page). Set a default shift for employees without one.</p>
      </div>`,
      onOpen: ({ form }) => {
        $('#useHere').addEventListener('click', () => {
          if (!navigator.geolocation) return App.toast('Your browser does not support location access.', 'error');
          navigator.geolocation.getCurrentPosition(
            p => { form.elements.latitude.value = p.coords.latitude.toFixed(6); form.elements.longitude.value = p.coords.longitude.toFixed(6); },
            () => App.toast('Could not read your location.', 'error'));
        });
      },
      onSubmit: async (formData, ctx) => {
        await api.put('/attendance/settings/', {
          latitude: formData.get('latitude'), longitude: formData.get('longitude'),
          radius_meters: formData.get('radius_meters'), is_enabled: formData.get('is_enabled') === 'on',
        });
        ctx.close(); App.toast('Office location saved.');
      },
    });
  }

  const refilter = () => { state.page = 1; load(); };
  $('#tabRecords').addEventListener('click', () => setTab('records'));
  $('#tabSummary').addEventListener('click', () => setTab('summary'));
  $('#settingsBtn').addEventListener('click', openSettings);
  $('#excelBtn').addEventListener('click', () => App.download('/reports/excel/attendance/', `attendance_${state.from}_${state.to}.xlsx`, { department: state.department, from: state.from, to: state.to, late: state.late === 'true' ? 'true' : '' }));
  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); refilter(); }));
  $('#department').addEventListener('change', e => { state.department = e.target.value; refilter(); });
  $('#late').addEventListener('change', e => { state.late = e.target.value; refilter(); });
  $('#from').addEventListener('change', e => { state.from = e.target.value; refilter(); });
  $('#to').addEventListener('change', e => { state.to = e.target.value; refilter(); });
  load();
})();
