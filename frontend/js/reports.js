(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api } = App;
  await App.boot({ role: 'ADMIN', nav: 'reports' });
  const nowYear = new Date().getFullYear();
  let year = nowYear;
  $('#year').innerHTML = html`${Array.from({ length: 6 }, (_, i) => nowYear - i).map(y => html`<option value="${y}">${y}</option>`)}`;

  async function load() {
    $('#stats').innerHTML = html`${[0, 1, 2, 3].map(() => html`<div class="card stat"><span class="skeleton" style="width:100%;height:56px"></span></div>`)}`;
    $('#rows').innerHTML = App.skeletonRows(7, 6);
    let data;
    try { data = await api.get('/payroll/reports/', { year }); } catch (error) {
      $('#stats').innerHTML = '';
      $('#chart').innerHTML = App.empty({ iconName: 'alert', title: 'Could not load reports', text: error.message, action: html`<button class="btn btn-sm" id="retry">Try again</button>` });
      $('#retry').addEventListener('click', load);
      $('#depts').innerHTML = ''; $('#rows').innerHTML = '';
      return;
    }
    const sum = key => data.monthly.reduce((total, m) => total + Number(m[key]), 0);
    const runs = data.monthly.filter(m => m.count);
    $('#stats').innerHTML = html`
      <div class="card stat"><span class="stat-icon green">${icon('wallet')}</span><div><div class="stat-label">Net paid / payable</div><div class="stat-value">${fmt.compactMoney(sum('net'))}</div><div class="stat-note">${fmt.money(sum('net'), { decimals: 0 })}</div></div></div>
      <div class="card stat"><span class="stat-icon">${icon('rupee')}</span><div><div class="stat-label">Gross earnings</div><div class="stat-value">${fmt.compactMoney(sum('gross'))}</div><div class="stat-note">${year}</div></div></div>
      <div class="card stat"><span class="stat-icon amber">${icon('layers')}</span><div><div class="stat-label">Deductions</div><div class="stat-value">${fmt.compactMoney(sum('deductions'))}</div><div class="stat-note">PF, tax, loss of pay</div></div></div>
      <div class="card stat"><span class="stat-icon blue">${icon('calendar')}</span><div><div class="stat-label">Payroll months</div><div class="stat-value">${runs.length}</div><div class="stat-note">${sum('count')} payslips</div></div></div>`;
    $('#yearNote').textContent = `${year} · by payroll month`;
    if (runs.length) App.barChart($('#chart'), data.monthly.map(m => ({ label: m.label, value: Number(m.net) })), { label: `Net payroll by month in ${year}` });
    else $('#chart').innerHTML = App.empty({ iconName: 'chart', title: `No payroll in ${year}`, text: 'Run payroll to see totals here.' });
    $('#deptTitle').textContent = data.month ? `Cost by department · ${fmt.months[data.month - 1]}` : 'Cost by department';
    App.hbars($('#depts'), data.departments.map(d => ({ label: `${d.department} (${d.headcount})`, value: Number(d.net) })), { format: fmt.compactMoney });
    $('#rows').innerHTML = runs.length ? html`${runs.map(m => html`<tr>
      <td class="cell-main">${fmt.months[m.month - 1]}</td><td class="right num">${m.count}</td>
      <td class="right num">${fmt.money(m.gross)}</td><td class="right num">${fmt.money(m.deductions)}</td><td class="right num"><strong>${fmt.money(m.net)}</strong></td>
      <td>${m.drafts ? App.badge('DRAFT', `${m.drafts} draft`) : App.badge('PAID', 'All paid')}</td>
      <td><div class="actions"><button class="btn btn-sm" type="button" data-export="${m.month}">${icon('download', 'icon-sm')} CSV</button></div></td></tr>`)}`
      : App.emptyRow(7, { iconName: 'wallet', title: `No payroll in ${year}`, text: 'Months appear here once payslips are generated.' });
    $$('[data-export]', $('#rows')).forEach(b => b.addEventListener('click', () => App.download('/payroll/export/', `payroll_${year}-${String(b.dataset.export).padStart(2, '0')}.csv`, { year, month: b.dataset.export })));
  }
  $('#year').addEventListener('change', e => { year = Number(e.target.value); load(); });
  load();

  /* ---- Excel exports ---- */
  const REPORTS = {
    employees: { label: 'Employees', dates: 'Joined between', statuses: [['ACTIVE', 'Active'], ['INACTIVE', 'Inactive']] },
    attendance: { label: 'Attendance (late minutes, hours)', dates: 'Attendance dates', statuses: [] },
    leave: { label: 'Leave', dates: 'Leave dates', statuses: [['PENDING', 'Pending'], ['APPROVED', 'Approved'], ['REJECTED', 'Rejected']] },
    overtime: { label: 'Overtime', dates: 'Overtime dates', statuses: [['PENDING', 'Pending'], ['APPROVED', 'Approved'], ['REJECTED', 'Rejected'], ['CANCELLED', 'Cancelled']] },
    payroll: { label: 'Payroll register', dates: null, statuses: [['DRAFT', 'Draft'], ['PAID', 'Paid']] },
  };
  let meta = { departments: [] }, people = [];
  let leaveTypes = [];
  try { [meta, people, leaveTypes] = await Promise.all([api.get('/employees/meta/'), api.get('/employees/'), api.get('/leave-types/', { all: 'true' })]); } catch (error) { /* filters fall back to "All" */ }
  const today = new Date();
  const monthStart = App.fmt.iso(new Date(today.getFullYear(), today.getMonth(), 1));
  const form = $('#excelForm');
  function renderForm(kind) {
    const r = REPORTS[kind];
    form.innerHTML = html`
      <div class="field"><label for="xKind">Report</label><select class="select" id="xKind" name="kind">${Object.entries(REPORTS).map(([k, v]) => html`<option value="${k}"${k === kind ? App.raw(' selected') : ''}>${v.label}</option>`)}</select></div>
      ${r.dates ? html`<div class="field"><label for="xFrom">${r.dates}: from</label><input class="input" type="date" id="xFrom" name="from" value="${kind === 'employees' || kind === 'leave' ? '' : monthStart}"></div>
        <div class="field"><label for="xTo">to</label><input class="input" type="date" id="xTo" name="to" value="${kind === 'employees' || kind === 'leave' ? '' : App.todayISO()}"></div>`
        : html`<div class="field"><label for="xYear">Year</label><select class="select" id="xYear" name="year">${Array.from({ length: 6 }, (_, i) => today.getFullYear() - i).map(y => html`<option value="${y}">${y}</option>`)}</select></div>
        <div class="field"><label for="xMonth">Month</label><select class="select" id="xMonth" name="month"><option value="">Whole year</option>${fmt.months.map((m, i) => html`<option value="${i + 1}">${m}</option>`)}</select></div>`}
      <div class="field"><label for="xDept">Department</label><select class="select" id="xDept" name="department"><option value="">All departments</option>${meta.departments.map(d => html`<option value="${d}">${d}</option>`)}</select></div>
      ${kind !== 'employees' ? html`<div class="field"><label for="xEmp">Employee</label><select class="select" id="xEmp" name="employee"><option value="">All employees</option>${people.map(p => html`<option value="${p.id}">${p.full_name} · ${p.employee_id}</option>`)}</select></div>` : ''}
      ${r.statuses.length ? html`<div class="field"><label for="xStatus">Status</label><select class="select" id="xStatus" name="status"><option value="">All</option>${r.statuses.map(([v, l]) => html`<option value="${v}">${l}</option>`)}</select></div>` : ''}
      ${kind === 'leave' ? html`<div class="field"><label for="xType">Leave type</label><select class="select" id="xType" name="leave_type"><option value="">All types</option>${leaveTypes.map(t => html`<option value="${t.name}">${t.name}${t.is_active ? '' : ' (inactive)'}</option>`)}</select></div>` : ''}
      ${kind === 'attendance' ? html`<div class="field"><label for="xLate">Check-ins</label><select class="select" id="xLate" name="late"><option value="">All</option><option value="true">Late only</option></select></div>` : ''}
      ${kind === 'employees' ? html`<div class="field"><label for="xSearch">Search</label><input class="input" id="xSearch" name="search" type="search" placeholder="Name, ID, email"></div>` : ''}
      <div class="field" style="align-self:end"><button class="btn btn-primary" type="submit">${icon('download')} Download .xlsx</button></div>`;
    $('#xKind').addEventListener('change', event => renderForm(event.target.value));
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    const params = Object.fromEntries(Array.from(new FormData(form)).filter(([key, value]) => key !== 'kind' && value !== ''));
    const kind = $('#xKind').value;
    App.download(`/reports/excel/${kind}/`, `${kind}_report_${App.todayISO()}.xlsx`, params);
  });
  renderForm('attendance');
})();
