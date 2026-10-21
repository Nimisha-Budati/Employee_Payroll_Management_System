(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api } = App;
  await App.boot({ role: 'ADMIN', nav: 'analytics' });
  $('#excelBtn').innerHTML = html`${icon('spreadsheet')} Export Excel`;

  const monthValue = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
  const now = new Date();
  const state = { to: monthValue(now), from: monthValue(new Date(now.getFullYear(), now.getMonth() - 5, 1)), department: '' };
  $('#from').value = state.from; $('#to').value = state.to;
  try {
    const meta = await api.get('/employees/meta/');
    $('#department').innerHTML = html`<option value="">All departments</option>${meta.departments.map(d => html`<option value="${d}">${d}</option>`)}`;
  } catch (error) { /* department filter stays at "All" */ }

  const pctText = value => (value == null ? '—' : `${fmt.number(value)}%`);
  // A change badge: "good" says whether an increase is good news (cost up is not).
  function compare(item, { good = 'down', money = false, points = false } = {}) {
    if (!item || item.change == null) return html`<span class="subtle">no earlier data</span>`;
    const change = Number(item.change);
    if (!change) return html`<span class="subtle">no change vs previous period</span>`;
    const better = (change > 0) === (good === 'up');
    const text = points ? `${change > 0 ? '+' : ''}${fmt.number(change)} pts` : item.percent != null ? `${change > 0 ? '+' : ''}${fmt.number(item.percent)}%`
      : `${change > 0 ? '+' : ''}${money ? fmt.compactMoney(change) : fmt.number(change)}`;
    const tone = good === 'none' ? '' : better ? 'change-up' : 'change-down';
    return html`<span class="compare ${tone}">${change > 0 ? '▲' : '▼'} ${text}</span> <span class="subtle">vs previous</span>`;
  }

  function lineChart(container, labels, series, { format = v => v, label = 'Chart' } = {}) {
    const values = series.flatMap(s => s.values.filter(v => v != null).map(Number));
    if (!values.length || values.every(v => !v)) {
      container.innerHTML = App.empty({ iconName: 'chart', title: 'No data in this period', text: 'Figures appear once there is activity to report.' });
      return;
    }
    const width = 600, height = 220, pad = { top: 12, right: 12, bottom: 28, left: 46 };
    const max = Math.max(...values) * 1.15 || 1;
    const innerW = width - pad.left - pad.right, innerH = height - pad.top - pad.bottom;
    const x = i => pad.left + (labels.length === 1 ? innerW / 2 : (innerW * i) / (labels.length - 1));
    const y = v => pad.top + innerH - (Number(v) / max) * innerH;
    container.innerHTML = html`<div class="legend">${series.map((s, i) => html`<span><i class="series-${i + 1}"></i>${s.name}</span>`)}</div>
      <svg class="chart line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${label}" preserveAspectRatio="xMidYMid meet">
        ${[0, 0.5, 1].map(f => html`<line class="grid-line" x1="${pad.left}" x2="${width - pad.right}" y1="${y(f * max)}" y2="${y(f * max)}"/><text x="${pad.left - 6}" y="${y(f * max) + 4}" text-anchor="end">${format(f * max)}</text>`)}
        ${series.map((s, si) => {
          const points = s.values.map((v, i) => (v == null ? null : [x(i), y(v)])).filter(Boolean);
          return html`<polyline class="line series-${si + 1}" style="fill:none" points="${points.map(p => p.join(',')).join(' ')}"/>
            ${s.values.map((v, i) => (v == null ? '' : html`<circle class="dot series-${si + 1}" cx="${x(i)}" cy="${y(v)}" r="3.5"><title>${labels[i]} · ${s.name}: ${format(v)}</title></circle>`))}`;
        })}
        ${labels.map((l, i) => html`<text x="${x(i)}" y="${height - 8}" text-anchor="middle">${l}</text>`)}
      </svg>`;
  }

  async function load() {
    $('#stats').innerHTML = html`${[0, 1, 2, 3, 4, 5, 6, 7].map(() => html`<div class="card stat"><span class="skeleton" style="width:100%;height:56px"></span></div>`)}`;
    ['costChart', 'overtimeChart', 'lateChart', 'headcountChart'].forEach(id => { $(`#${id}`).innerHTML = html`<span class="skeleton" style="width:100%;height:200px;display:block"></span>`; });
    $('#deptRows').innerHTML = App.skeletonRows(7, 4);
    $('#leaveRows').innerHTML = App.skeletonRows(5, 3);
    $('#monthRows').innerHTML = App.skeletonRows(5, 4);
    let data;
    try {
      data = await api.get('/reports/analytics/', state);
    } catch (error) {
      $('#stats').innerHTML = '';
      $('#costChart').innerHTML = App.empty({ iconName: 'alert', title: 'Could not load analytics', text: error.message, action: html`<button class="btn btn-sm" id="retry" type="button">Try again</button>` });
      ['overtimeChart', 'lateChart', 'headcountChart'].forEach(id => { $(`#${id}`).innerHTML = ''; });
      $('#deptRows').innerHTML = ''; $('#leaveRows').innerHTML = ''; $('#monthRows').innerHTML = '';
      $('#retry').addEventListener('click', load);
      return;
    }
    render(data);
  }

  function render(data) {
    const s = data.summary, c = data.comparison;
    const notes = [...data.notes];
    if (!data.has_data) notes.unshift('There is no payroll, attendance, leave or overtime data in this period yet.');
    $('#notes').hidden = !notes.length;
    $('#notes').innerHTML = html`${icon('info')}<span>${notes.join(' ')} Compared with ${data.previous_from} to ${data.previous_to}.</span>`;
    $('#stats').innerHTML = html`
      <div class="card stat"><span class="stat-icon green">${icon('rupee')}</span><div><div class="stat-label">Payroll cost</div><div class="stat-value">${fmt.compactMoney(s.payroll_cost)}</div><div class="stat-note">${compare(c.payroll_cost, { money: true })}</div></div></div>
      <div class="card stat"><span class="stat-icon">${icon('wallet')}</span><div><div class="stat-label">Average per month</div><div class="stat-value">${fmt.compactMoney(s.average_monthly_cost)}</div><div class="stat-note">Net pay ${fmt.compactMoney(s.net_pay)}</div></div></div>
      <div class="card stat"><span class="stat-icon amber">${icon('timer')}</span><div><div class="stat-label">Overtime cost</div><div class="stat-value">${fmt.compactMoney(s.overtime_cost)}</div><div class="stat-note">${fmt.number(s.overtime_hours)} h · ${compare(c.overtime_cost, { money: true })}</div></div></div>
      <div class="card stat"><span class="stat-icon blue">${icon('users')}</span><div><div class="stat-label">Headcount (end)</div><div class="stat-value">${s.headcount_end}</div><div class="stat-note">+${s.joined} joined · −${s.left} left</div></div></div>
      <div class="card stat"><span class="stat-icon amber">${icon('clock')}</span><div><div class="stat-label">Late check-ins</div><div class="stat-value">${s.late_checkins}</div><div class="stat-note">${pctText(s.late_rate)} of ${s.present_days} · ${compare(c.late_checkins)}</div></div></div>
      <div class="card stat"><span class="stat-icon amber">${icon('alert')}</span><div><div class="stat-label">Absenteeism</div><div class="stat-value">${pctText(s.absenteeism_rate)}</div><div class="stat-note">${fmt.number(s.lop_days)} LOP days · ${compare(c.absenteeism_rate, { points: true })}</div></div></div>
      <div class="card stat"><span class="stat-icon">${icon('calendar')}</span><div><div class="stat-label">Leave days taken</div><div class="stat-value">${s.leave_days}</div><div class="stat-note">${compare(c.leave_days, { good: 'none' })}</div></div></div>
      <div class="card stat"><span class="stat-icon green">${icon('trending')}</span><div><div class="stat-label">Joiners / leavers</div><div class="stat-value">${s.joined} / ${s.left}</div><div class="stat-note">${compare(c.joined, { good: 'up' })}</div></div></div>`;

    const labels = data.monthly.map(m => m.label);
    App.barChart($('#costChart'), data.monthly.map(m => ({ label: m.label, value: Number(m.payroll.gross) })), { label: 'Payroll cost by month' });
    App.barChart($('#overtimeChart'), data.monthly.map(m => ({ label: m.label, value: Number(m.overtime.amount) })), { label: 'Overtime cost by month' });
    lineChart($('#lateChart'), labels, [
      { name: 'Late check-ins %', values: data.monthly.map(m => m.attendance.late_rate) },
      { name: 'Absenteeism %', values: data.monthly.map(m => m.absenteeism.rate) },
    ], { format: v => `${Math.round(v)}%`, label: 'Lateness and absenteeism by month' });
    lineChart($('#headcountChart'), labels, [
      { name: 'Headcount', values: data.monthly.map(m => m.headcount.end) },
      { name: 'Joined', values: data.monthly.map(m => m.headcount.joined) },
      { name: 'Left', values: data.monthly.map(m => m.headcount.left) },
    ], { format: v => Math.round(v), label: 'Headcount by month' });

    $('#deptNote').textContent = `${data.from} to ${data.to}${data.department ? ` · ${data.department}` : ''}`;
    $('#deptRows').innerHTML = data.departments.length ? html`${data.departments.map(d => html`<tr>
      <td class="cell-main">${d.department}</td><td class="right num">${d.headcount}</td><td class="right num">${fmt.money(d.gross, { decimals: 0 })}</td>
      <td class="right num">${fmt.money(d.net, { decimals: 0 })}</td><td class="right num">${fmt.money(d.overtime_amount, { decimals: 0 })}</td>
      <td class="right num">${d.late}</td><td class="right num">${d.leave_days}</td></tr>`)}`
      : App.emptyRow(7, { iconName: 'users', title: 'No department data in this period' });

    const u = data.leave_utilisation;
    $('#leaveNote').textContent = `Leave year ${u.label}, ${u.employees} active employee(s)`;
    $('#leaveRows').innerHTML = u.types.length ? html`${u.types.map(t => html`<tr>
      <td class="cell-main">${t.leave_type}${t.is_paid ? '' : html` <span class="badge">Unpaid</span>`}</td>
      <td class="right num">${t.entitled_days == null ? 'No limit' : t.entitled_days}</td><td class="right num">${t.used_days}</td><td class="right num">${t.pending_days}</td>
      <td>${t.utilisation == null ? html`<span class="subtle">—</span>` : html`<div class="progress-label"><span>${pctText(t.utilisation)}</span></div><div class="progress" role="progressbar" aria-valuenow="${t.utilisation}" aria-valuemin="0" aria-valuemax="100" aria-label="${t.leave_type} utilisation"><span style="width:${Math.min(100, Number(t.utilisation))}%"></span></div>`}</td></tr>`)}`
      : App.emptyRow(5, { iconName: 'calendar', title: 'No active leave types' });

    $('#monthRows').innerHTML = html`${data.monthly.map(m => html`<tr><td>${m.label}</td><td class="right num">${m.attendance.present}</td>
      <td class="right num">${m.attendance.late}${m.attendance.average_late_minutes ? html`<div class="cell-sub">avg ${m.attendance.average_late_minutes} min</div>` : ''}</td>
      <td class="right num">${m.leave_days}</td><td class="right num">${pctText(m.absenteeism.rate)}</td></tr>`)}`;
  }

  $('#filters').addEventListener('submit', event => {
    event.preventDefault();
    if (!$('#from').value || !$('#to').value) { App.toast('Choose both months.', 'error'); return; }
    if ($('#from').value > $('#to').value) { App.toast('The start month must be before the end month.', 'error'); return; }
    state.from = $('#from').value; state.to = $('#to').value; state.department = $('#department').value;
    load();
  });
  $$('[data-range]').forEach(b => b.addEventListener('click', () => {
    const months = Number(b.dataset.range);
    state.to = monthValue(now); state.from = monthValue(new Date(now.getFullYear(), now.getMonth() - months + 1, 1));
    $('#from').value = state.from; $('#to').value = state.to; state.department = $('#department').value;
    load();
  }));
  $('#excelBtn').addEventListener('click', () => App.download('/reports/excel/analytics/', `analytics_${state.from}_to_${state.to}.xlsx`, state));
  load();
})();
