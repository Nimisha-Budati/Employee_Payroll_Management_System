(async function () {
  'use strict';
  const { $, html, icon, fmt, api } = App;
  const user = await App.boot({ role: 'EMPLOYEE', nav: 'dashboard' });
  const hour = new Date().getHours();
  $('#greeting').textContent = `${hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'}, ${user.first_name || user.username}`;
  $('#stats').innerHTML = html`${[0, 1, 2, 3].map(() => html`<div class="card stat"><span class="skeleton" style="width:100%;height:56px"></span></div>`)}`;

  const data = await App.guard($('#stats'), () => api.get('/dashboard/employee/'));
  if (!data) return;
  const { employee, attendance, requests, latest_payslip: slip } = data;

  if (!employee) $('#notice').innerHTML = html`<div class="alert alert-warning">${icon('info')}<span>Your employment record has not been created yet. An administrator needs to complete it before payroll, attendance and leave work for you.</span></div>`;

  const att = attendance.checked_out_today ? 'Completed today' : attendance.checked_in_today ? 'Checked in' : 'Not checked in';
  const shift = data.shift;
  const lateToday = attendance.late_minutes_today ? ` · ${attendance.late_minutes_today} min late` : '';
  const pendingTotal = requests.pending_leaves + requests.pending_wfh + requests.pending_documents + (requests.pending_overtime || 0);
  $('#stats').innerHTML = html`
    <a class="card stat" href="employee-payslips.html"><span class="stat-icon green">${icon('wallet')}</span><div><div class="stat-label">${slip ? `Net pay · ${fmt.months[slip.month - 1]}` : 'Latest net pay'}</div><div class="stat-value">${slip ? fmt.compactMoney(slip.net_salary) : '—'}</div><div class="stat-note">${slip ? fmt.money(slip.net_salary, { decimals: 0 }) : 'No payslip yet'}</div></div></a>
    <a class="card stat" href="employee-attendance.html"><span class="stat-icon blue">${icon('pin')}</span><div><div class="stat-label">Today</div><div class="stat-value" style="font-size:20px">${att}</div><div class="stat-note">${shift ? `${shift.name} ${shift.start_time.slice(0, 5)}–${shift.end_time.slice(0, 5)}` : 'No shift'}${lateToday} · ${attendance.days_present_this_month} present, ${attendance.late_days_this_month} late this month</div></div></a>
    <a class="card stat" href="employee-leave.html"><span class="stat-icon amber">${icon('clock')}</span><div><div class="stat-label">Pending requests</div><div class="stat-value">${pendingTotal}</div><div class="stat-note">${requests.pending_leaves} leave · ${requests.pending_wfh} WFH · ${requests.pending_documents} docs</div></div></a>
    <a class="card stat" href="employee-profile.html"><span class="stat-icon">${icon('briefcase')}</span><div><div class="stat-label">${employee ? employee.designation : 'Employee'}</div><div class="stat-value" style="font-size:20px">${employee ? employee.employee_id : '—'}</div><div class="stat-note">${employee ? employee.department : 'Record pending'}</div></div></a>`;

  App.barChart($('#trend'), data.salary_trend.map(i => ({ label: i.label, value: i.net })), { label: 'Net salary by month' });
  const balances = Object.entries(data.leave_balance);
  $('#balYear').textContent = `Leave year ${data.leave_year} · from your organisation's leave policy`;
  $('#balances').innerHTML = balances.length ? html`<div class="table-wrap"><table class="table table-compact"><thead><tr><th>Leave type</th><th class="right">Allowed</th><th class="right">Used</th><th class="right">Pending</th><th class="right">Available</th></tr></thead><tbody>
    ${balances.map(([type, b]) => html`<tr><td>${type}${b.is_paid ? '' : html` <span class="badge badge-warning">Unpaid</span>`}</td>
      <td class="right num">${b.unlimited ? '—' : b.total}</td><td class="right num">${fmt.number(b.approved)}</td>
      <td class="right num">${fmt.number(b.pending)}</td><td class="right num"><strong>${b.unlimited ? 'No limit' : fmt.number(b.available)}</strong></td></tr>`)}
    </tbody></table></div>` : App.empty({ iconName: 'calendar', title: 'No leave types yet' });
  $('#holidays').innerHTML = data.upcoming_holidays.length ? html`${data.upcoming_holidays.map(h => html`<li class="row" style="justify-content:space-between;flex-wrap:nowrap"><div><div style="font-weight:600">${h.name}</div><div class="muted">${fmt.dateLong(h.date)}</div></div>${App.badge(h.holiday_type)}</li>`)}`
    : html`<li>${App.empty({ iconName: 'calendar', title: 'No upcoming holidays' })}</li>`;
  $('#announcements').innerHTML = data.announcements.length ? html`${data.announcements.map(a => html`<li><div style="font-weight:600">${a.title}</div><div class="muted truncate">${a.message}</div><div class="subtle" style="font-size:12.5px;margin-top:2px">${fmt.relative(a.created_at)}</div></li>`)}`
    : html`<li>${App.empty({ iconName: 'flag', title: 'No announcements' })}</li>`;
})();
