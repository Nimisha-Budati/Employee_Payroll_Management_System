(async function () {
  'use strict';
  const { $, html, icon, fmt } = App;
  const user = await App.boot({ role: 'ADMIN', nav: 'dashboard' });
  $('#runPayrollBtn').innerHTML = html`${icon('wallet')} Run payroll`;
  const hour = new Date().getHours();
  $('#greeting').textContent = `${hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'}, ${user.first_name || user.username}`;
  $('#stats').innerHTML = html`${[0, 1, 2, 3].map(() => html`<div class="card stat"><span class="skeleton" style="width:100%;height:56px"></span></div>`)}`;

  const data = await App.guard($('#stats'), () => App.api.get('/dashboard/admin/'));
  if (!data) return;
  const { employees, pending, attendance, payroll } = data;
  const pendingTotal = pending.leaves + pending.wfh + pending.documents + (pending.overtime || 0);

  $('#stats').innerHTML = html`
    <a class="card stat" href="employee-management.html"><span class="stat-icon">${icon('users')}</span><div><div class="stat-label">Active employees</div><div class="stat-value">${employees.active}</div><div class="stat-note">${employees.joined_this_month} joined this month</div></div></a>
    <a class="card stat" href="admin-payroll.html"><span class="stat-icon green">${icon('wallet')}</span><div><div class="stat-label">${payroll.latest ? `Net payroll · ${payroll.latest.label}` : 'Net payroll'}</div><div class="stat-value">${payroll.latest ? fmt.compactMoney(payroll.latest.net) : '—'}</div><div class="stat-note">${payroll.latest ? `${payroll.latest.count} payslips${payroll.latest.drafts ? `, ${payroll.latest.drafts} draft` : ''}` : 'No payroll run yet'}</div></div></a>
    <a class="card stat" href="admin-leave.html"><span class="stat-icon amber">${icon('clock')}</span><div><div class="stat-label">Pending approvals</div><div class="stat-value">${pendingTotal}</div><div class="stat-note">${pending.leaves} leave · ${pending.wfh} WFH · ${pending.documents} docs · ${pending.overtime || 0} overtime</div></div></a>
    <a class="card stat" href="admin-attendance.html"><span class="stat-icon blue">${icon('pin')}</span><div><div class="stat-label">Checked in today</div><div class="stat-value">${attendance.checked_in_today}<span class="muted" style="font-size:15px;font-weight:500"> / ${employees.active}</span></div><div class="stat-note">${attendance.late_today} late · ${attendance.on_leave_today} on leave · ${attendance.working_from_home_today} remote</div></div></a>`;

  const alerts = [];
  if (employees.pending_onboarding) alerts.push(['users', `${employees.pending_onboarding} registered account${employees.pending_onboarding === 1 ? ' is' : 's are'} waiting for an employee record.`, 'employee-management.html', 'Onboard']);
  if (payroll.employees_without_structure) alerts.push(['rupee', `${payroll.employees_without_structure} active employee${payroll.employees_without_structure === 1 ? ' has' : 's have'} no salary structure and will be skipped in payroll.`, 'admin-salary.html', 'Set up salaries']);
  if (pending.overtime) alerts.push(['timer', `${pending.overtime} overtime record${pending.overtime === 1 ? '' : 's'} waiting for approval (unapproved overtime is not paid).`, 'overtime.html', 'Review']);
  if (payroll.latest && payroll.latest.drafts) alerts.push(['wallet', `${payroll.latest.drafts} draft payslip${payroll.latest.drafts === 1 ? '' : 's'} for ${payroll.latest.label} still need to be finalised.`, 'admin-payroll.html', 'Review']);
  $('#attention').innerHTML = html`${alerts.map(([iconName, text, href, label]) => html`<div class="alert alert-warning">${icon(iconName)}<span style="flex:1">${text}</span><a href="${href}"><strong>${label}</strong></a></div>`)}`;

  App.barChart($('#trendChart'), payroll.trend.map(item => ({ label: item.label, value: item.net })), { label: 'Net payroll by month' });
  App.barChart($('#attChart'), attendance.trend.map(day => ({ label: day.label.split(' ')[0], value: day.present })), { label: 'Check-ins per day', format: value => `${Math.round(value)}` });
  $('#attNote').textContent = `Check-ins per day · ${attendance.late_this_month} late this month (avg ${attendance.average_late_minutes_this_month} min)`;
  const leave = data.leave;
  const byStatus = leave.by_status;
  $('#leaveNote').textContent = `${leave.year} · ${leave.approved_days_this_month} approved day${leave.approved_days_this_month === 1 ? '' : 's'} this month`;
  $('#leaveStats').innerHTML = html`<div class="row" style="gap:8px;flex-wrap:wrap">${App.badge('PENDING', `${byStatus.PENDING || 0} pending`)}${App.badge('APPROVED', `${byStatus.APPROVED || 0} approved`)}${App.badge('REJECTED', `${byStatus.REJECTED || 0} rejected`)}</div><div id="leaveTypes"></div>`;
  App.hbars($('#leaveTypes'), leave.approved_days_by_type.map(row => ({ label: row.leave_type, value: row.days })), { format: value => `${value} day${Number(value) === 1 ? '' : 's'}` });
  App.hbars($('#deptChart'), data.departments.map(item => ({ label: item.department || 'Unassigned', value: item.headcount })), { format: value => `${value}` });

  $('#pendingLeaves').innerHTML = data.recent_leaves.length ? html`${data.recent_leaves.map(leave => html`<li class="row" style="justify-content:space-between;flex-wrap:nowrap"><div><div class="cell-main" style="font-weight:600">${leave.employee_username}</div><div class="muted">${leave.leave_type} · ${fmt.date(leave.start_date)} – ${fmt.date(leave.end_date)} (${leave.number_of_days}d)</div></div>${App.badge('PENDING')}</li>`)}`
    : html`<li>${App.empty({ iconName: 'check', title: 'All caught up', text: 'No leave requests are waiting for approval.' })}</li>`;
  $('#announcements').innerHTML = data.announcements.length ? html`${data.announcements.map(item => html`<li><div style="font-weight:600">${item.title}</div><div class="muted truncate">${item.message}</div><div class="subtle" style="font-size:12.5px;margin-top:2px">${fmt.relative(item.created_at)}</div></li>`)}`
    : html`<li>${App.empty({ iconName: 'flag', title: 'No announcements', text: 'Post one from the Announcements page.' })}</li>`;
})();
