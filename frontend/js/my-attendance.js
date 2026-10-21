(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  await App.boot({ role: 'EMPLOYEE', nav: 'attendance' });
  $('#insightLink').innerHTML = html`${icon('sparkle')} AI attendance insights`;
  $('#correctBtn').innerHTML = html`${icon('edit')} Request correction`;
  const TYPES = [
    ['MISSED_CHECK_IN', 'Missed check-in'], ['MISSED_CHECK_OUT', 'Missed check-out'],
    ['WRONG_TIMES', 'Incorrect check-in or check-out time'], ['MISSED_DAY', 'Worked but no attendance recorded'],
  ];
  let history = [];
  let status = null;

  const shiftHours = shift => `${shift.start_time.slice(0, 5)} – ${shift.end_time.slice(0, 5)}`;
  const lateCell = minutes => (minutes == null ? html`<span class="muted">—</span>` : minutes > 0 ? html`<span class="badge badge-warning">${minutes} min</span>` : html`<span class="badge badge-success">On time</span>`);

  function locate() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error('Your browser does not support location access.'));
      navigator.geolocation.getCurrentPosition(
        position => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude }),
        error => reject(new Error(error.code === 1 ? 'Location permission was denied. Allow location access for this site and try again.' : 'Could not determine your location. Try again.')),
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
      );
    });
  }

  async function mark(action, button) {
    const original = button.innerHTML;
    button.disabled = true; button.innerHTML = '<span class="spinner"></span> Getting location…';
    try {
      const position = await locate();
      const record = await api.post(`/attendance/${action}/`, position);
      if (action === 'check-in' && record.late_minutes > 0) App.toast(`Checked in, ${record.late_minutes} min after your shift start.`, 'error');
      else App.toast(action === 'check-in' ? 'Checked in.' : 'Checked out.');
      await Promise.all([loadStatus(), loadHistory(), loadMonth()]);
    } catch (error) { App.error(error); button.disabled = false; button.innerHTML = original; }
  }

  async function loadStatus() {
    try { status = await api.get('/attendance/status/'); } catch (error) {
      $('#today').innerHTML = App.empty({ iconName: 'alert', title: 'Could not load attendance', text: error.message, action: html`<button class="btn btn-sm" id="retry">Try again</button>` });
      $('#retry').addEventListener('click', loadStatus); return;
    }
    const record = status.record;
    $('#todayDate').textContent = fmt.dateLong(status.date);
    $('#todayBadge').innerHTML = record ? App.badge(record.check_out_at ? 'CHECKED_OUT' : 'CHECKED_IN') : App.badge('PENDING', 'Not checked in');
    let action = '';
    if (!status.attendance_enabled) action = html`<div class="alert alert-warning">${icon('alert')}<span>Attendance has not been set up yet. Ask an administrator to configure the office location.</span></div>`;
    else if (!record || !record.check_in_at) action = html`<button class="btn btn-primary" id="checkIn" type="button">${icon('pin')} Check in</button>`;
    else if (!record.check_out_at) action = html`<button class="btn btn-primary" id="checkOut" type="button">${icon('logout')} Check out</button>`;
    else action = html`<div class="alert alert-success">${icon('check')}<span>You have completed attendance for today. Worked ${fmt.duration(record.worked_minutes)}.</span></div>`;
    $('#today').innerHTML = html`<dl class="kv" style="margin-bottom:20px">
      <dt>Check in</dt><dd>${record ? fmt.time(record.check_in_at) : '—'}</dd>
      <dt>Late</dt><dd>${record ? lateCell(record.late_minutes) : '—'}</dd>
      <dt>Check out</dt><dd>${record && record.check_out_at ? fmt.time(record.check_out_at) : '—'}</dd>
      <dt>Allowed distance</dt><dd>${status.attendance_enabled ? `${status.radius_meters} m from the office` : 'Not configured'}</dd>
    </dl>${action}`;
    const inBtn = $('#checkIn'), outBtn = $('#checkOut');
    if (inBtn) inBtn.addEventListener('click', () => mark('check-in', inBtn));
    if (outBtn) outBtn.addEventListener('click', () => mark('check-out', outBtn));
  }

  async function loadShift() {
    try {
      const data = await api.get('/shifts/my/');
      const shift = data.shift;
      $('#shiftNote').textContent = shift ? (data.source === 'DEFAULT' ? 'Company default shift' : 'Assigned by an administrator') : '';
      $('#shiftInfo').innerHTML = shift ? html`<dl class="kv">
          <dt>Shift</dt><dd><strong>${shift.name}</strong></dd>
          <dt>Hours</dt><dd>${shiftHours(shift)}${shift.crosses_midnight ? ' (overnight)' : ''}</dd>
          <dt>Grace period</dt><dd>${shift.grace_minutes} min</dd>
          <dt>Unpaid break</dt><dd>${shift.break_minutes} min</dd>
          <dt>Standard day</dt><dd>${fmt.duration(shift.standard_minutes)}</dd>
        </dl><p class="muted" style="margin:12px 0 0">Checking in more than ${shift.grace_minutes} minutes after ${shift.start_time.slice(0, 5)} is recorded as late.</p>`
        : App.empty({ iconName: 'clock', title: 'No shift assigned', text: 'Late minutes are not tracked until an administrator assigns you a shift.' });
      $('#shiftRows').innerHTML = data.assignments.length ? html`${data.assignments.map(a => html`<tr>
        <td class="cell-main">${a.shift.name}</td><td>${shiftHours(a.shift)}</td><td>${fmt.date(a.start_date)}</td>
        <td>${a.end_date ? fmt.date(a.end_date) : html`<span class="badge badge-success">Ongoing</span>`}</td><td>${a.notes || '—'}</td></tr>`)}`
        : App.emptyRow(5, { iconName: 'clock', title: 'No shift assignments yet' });
    } catch (error) {
      $('#shiftInfo').innerHTML = App.empty({ iconName: 'alert', title: 'Could not load your shift', text: error.message });
      $('#shiftRows').innerHTML = App.errorRow(5, error.message, false);
    }
  }

  async function loadMonth() {
    try {
      const data = await api.get('/dashboard/employee/');
      const a = data.attendance, o = data.overtime;
      $('#monthStats').innerHTML = html`
        <div class="card stat"><span class="stat-icon blue">${icon('pin')}</span><div><div class="stat-label">Days present</div><div class="stat-value">${a.days_present_this_month}</div><div class="stat-note">This month</div></div></div>
        <div class="card stat"><span class="stat-icon amber">${icon('clock')}</span><div><div class="stat-label">Late days</div><div class="stat-value">${a.late_days_this_month}</div><div class="stat-note">${fmt.number(a.late_minutes_this_month)} late minutes</div></div></div>
        <div class="card stat"><span class="stat-icon green">${icon('timer')}</span><div><div class="stat-label">Approved overtime</div><div class="stat-value">${fmt.number(o.approved_hours_this_month)} h</div><div class="stat-note">${fmt.money(o.approved_amount_this_month)}</div></div></div>
        <a class="card stat" href="overtime.html"><span class="stat-icon">${icon('layers')}</span><div><div class="stat-label">Pending overtime</div><div class="stat-value">${data.requests.pending_overtime}</div><div class="stat-note">Claims awaiting approval</div></div></a>`;
    } catch (error) { $('#monthStats').innerHTML = ''; }
  }

  async function loadHistory() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(7, 5);
    try {
      const list = await api.get('/attendance/history/', { limit: 30 });
      history = list;
      rows.innerHTML = list.length ? html`${list.map(r => html`<tr><td class="cell-main">${fmt.date(r.date)}${r.is_corrected ? html` ${App.badge('CORRECTED')}` : ''}</td><td>${r.shift_name || '—'}</td><td>${fmt.time(r.check_in_at)}</td><td class="right">${lateCell(r.late_minutes)}</td><td>${r.check_out_at ? fmt.time(r.check_out_at) : '—'}</td><td class="right num">${r.worked_minutes == null ? '—' : fmt.duration(r.worked_minutes)}</td><td>${App.badge(r.status)}</td>
        <td class="right"><button class="btn btn-sm" type="button" data-correct="${r.date}" aria-label="Request a correction for ${fmt.date(r.date)}">${icon('edit', 'icon-sm')} Correct</button></td></tr>`)}`
        : App.emptyRow(8, { iconName: 'pin', title: 'No attendance yet', text: 'Your check-ins will be listed here. Use Request correction for a day you worked but could not check in.' });
      $$('[data-correct]', rows).forEach(b => b.addEventListener('click', () => requestCorrection(b.dataset.correct)));
    } catch (error) {
      rows.innerHTML = App.errorRow(8, error.message);
      $('[data-retry]', rows).addEventListener('click', loadHistory);
    }
  }
  /* ---- Attendance correction requests ---- */
  const clock = value => (value ? fmt.time(value) : '—');
  const hhmm = value => (value ? new Date(value).toTimeString().slice(0, 5) : '');

  function requestCorrection(day) {
    const record = history.find(r => r.date === day);
    const type = !record ? 'MISSED_DAY' : !record.check_out_at ? 'MISSED_CHECK_OUT' : 'WRONG_TIMES';
    const min = new Date(); min.setDate(min.getDate() - 60);
    App.modal({
      title: 'Request attendance correction', submitLabel: 'Send request',
      body: html`<div class="form-grid">
        <div class="span-2 alert alert-info">${icon('info')}<span>Your attendance changes only if an administrator approves. You can cancel the request while it is pending.</span></div>
        ${field({ label: 'Date', name: 'date', type: 'date', required: true, value: day || App.todayISO(), attrs: `max="${App.todayISO()}" min="${fmt.iso(min)}"` })}
        ${field({ label: 'What needs correcting?', name: 'correction_type', type: 'select', options: TYPES, value: type })}
        <div class="span-2 muted" id="recorded" aria-live="polite"></div>
        ${field({ label: 'Correct check-in time', name: 'check_in', type: 'time', value: record ? hhmm(record.check_in_at) : '' })}
        ${field({ label: 'Correct check-out time', name: 'check_out', type: 'time', value: record ? hhmm(record.check_out_at) : '' })}
        ${field({ label: 'Check-out was on the next day (overnight shift)', name: 'check_out_next_day', type: 'checkbox', span2: true })}
        ${field({ label: 'Reason', name: 'reason', type: 'textarea', required: true, span2: true, placeholder: 'e.g. The GPS check-in failed at the gate; I arrived at 09:05.', attrs: 'maxlength="1000" minlength="5"' })}
      </div>`,
      onOpen: ({ dialog }) => {
        const form = $('form', dialog);
        const sync = () => {
          const kind = form.elements.correction_type.value;
          const current = history.find(r => r.date === form.elements.date.value);
          $('#recorded', dialog).textContent = current
            ? `Recorded: check-in ${clock(current.check_in_at)}, check-out ${clock(current.check_out_at)}.`
            : 'No attendance is recorded for this date in your last 30 records.';
          form.elements.check_in.closest('.field').hidden = kind === 'MISSED_CHECK_OUT';
          form.elements.check_in.required = ['MISSED_CHECK_IN', 'MISSED_DAY'].includes(kind);
          form.elements.check_out.required = ['MISSED_CHECK_OUT', 'MISSED_DAY'].includes(kind);
        };
        form.elements.correction_type.addEventListener('change', sync);
        form.elements.date.addEventListener('change', sync);
        sync();
      },
      onSubmit: async (formData, ctx) => {
        const kind = formData.get('correction_type');
        await api.post('/attendance/corrections/', {
          date: formData.get('date'), correction_type: kind, reason: formData.get('reason'),
          check_in: kind === 'MISSED_CHECK_OUT' ? null : (formData.get('check_in') || null),
          check_out: formData.get('check_out') || null,
          check_out_next_day: formData.get('check_out_next_day') === 'on',
        });
        ctx.close(); App.toast('Correction request sent for approval.'); loadCorrections();
      },
    });
  }

  async function loadCorrections() {
    const rows = $('#correctionRows');
    rows.innerHTML = App.skeletonRows(6, 3);
    try {
      const list = await api.get('/attendance/corrections/');
      rows.innerHTML = list.length ? html`${list.map(c => html`<tr>
        <td class="cell-main nowrap">${fmt.date(c.date)}</td>
        <td>${c.correction_type_label}<div class="cell-sub">${c.reason}</div></td>
        <td class="nowrap"><div>In: ${clock(c.original_check_in)} → <strong>${c.requested_check_in ? clock(c.requested_check_in) : 'unchanged'}</strong></div>
          <div>Out: ${clock(c.original_check_out)} → <strong>${c.requested_check_out ? clock(c.requested_check_out) : 'unchanged'}</strong></div></td>
        <td>${App.badge(c.status)}</td>
        <td>${c.review_note ? c.review_note : html`<span class="subtle">—</span>`}${c.reviewed_at ? html`<div class="cell-sub">${c.reviewed_by_name} · ${fmt.dateTime(c.reviewed_at)}</div>` : ''}</td>
        <td class="right">${c.status === 'PENDING' ? html`<button class="btn btn-sm btn-danger" type="button" data-cancel="${c.id}">Cancel</button>` : ''}</td></tr>`)}`
        : App.emptyRow(6, { iconName: 'edit', title: 'No correction requests', text: 'If you forgot to check in or out, use Request correction.' });
      $$('[data-cancel]', rows).forEach(b => b.addEventListener('click', async () => {
        const ok = await App.confirm({ title: 'Cancel this request?', message: 'The administrator will no longer see it as pending.', confirmLabel: 'Cancel request', danger: true });
        if (!ok) return;
        try { await api.post(`/attendance/corrections/${b.dataset.cancel}/cancel/`); App.toast('Request cancelled.'); loadCorrections(); } catch (error) { App.error(error); }
      }));
    } catch (error) {
      rows.innerHTML = App.errorRow(6, error.message);
      $('[data-retry]', rows).addEventListener('click', loadCorrections);
    }
  }
  $('#correctBtn').addEventListener('click', () => requestCorrection(App.todayISO()));

  loadStatus(); loadShift(); loadMonth(); loadHistory(); loadCorrections();
})();
