(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  await App.boot({ role: 'ADMIN', nav: 'shifts' });
  $('#addShift').innerHTML = html`${icon('plus')} New shift`;
  $('#assignBtn').innerHTML = html`${icon('users')} Assign shift`;
  $('#searchIcon').innerHTML = icon('search');

  const state = { page: 1, pageSize: 10, search: '', shift: '', current: false };
  let shifts = [];
  const hours = s => `${s.start_time.slice(0, 5)} – ${s.end_time.slice(0, 5)}${s.crosses_midnight ? ' (overnight)' : ''}`;

  async function loadShifts() {
    const rows = $('#shiftRows');
    try {
      shifts = await api.get('/shifts/');
    } catch (error) {
      rows.innerHTML = App.errorRow(8, error.message);
      $('[data-retry]', rows).addEventListener('click', loadShifts);
      return;
    }
    $('#shiftFilter').innerHTML = html`<option value="">All shifts</option>${shifts.map(s => html`<option value="${s.id}"${String(s.id) === state.shift ? App.raw(' selected') : ''}>${s.name}</option>`)}`;
    rows.innerHTML = shifts.length ? html`${shifts.map(s => html`<tr>
      <td><div class="cell-main">${s.name}${s.is_default ? html` <span class="badge badge-accent">Default</span>` : ''}</div>${s.description ? html`<div class="cell-sub">${s.description}</div>` : ''}</td>
      <td class="nowrap">${hours(s)}</td><td class="right num">${s.grace_minutes} min</td><td class="right num">${s.break_minutes} min</td>
      <td class="right num">${fmt.duration(s.standard_minutes)}</td><td class="right num">${s.active_assignments}</td>
      <td>${App.badge(s.is_active ? 'ACTIVE' : 'INACTIVE')}</td>
      <td><div class="actions"><button class="btn btn-sm" type="button" data-edit="${s.id}">${icon('edit', 'icon-sm')} Edit</button><button class="btn btn-sm btn-danger" type="button" data-delete="${s.id}" aria-label="Delete ${s.name}">${icon('trash', 'icon-sm')}</button></div></td>
    </tr>`)}` : App.emptyRow(8, { iconName: 'clock', title: 'No shifts yet', text: 'Create a shift such as "General 09:30 – 18:30", then assign employees to it.' });
    $$('[data-edit]', rows).forEach(b => b.addEventListener('click', () => openShift(shifts.find(s => String(s.id) === b.dataset.edit))));
    $$('[data-delete]', rows).forEach(b => b.addEventListener('click', () => removeShift(shifts.find(s => String(s.id) === b.dataset.delete))));
  }

  function openShift(shift) {
    const s = shift || { grace_minutes: 10, break_minutes: 60, is_active: true };
    App.modal({
      title: shift ? 'Edit shift' : 'New shift', submitLabel: shift ? 'Save changes' : 'Create shift',
      body: html`<div class="form-grid">
        ${field({ label: 'Name', name: 'name', value: s.name, required: true, span2: true, placeholder: 'General', attrs: 'maxlength="60"' })}
        ${field({ label: 'Start time', name: 'start_time', type: 'time', value: (s.start_time || '09:30').slice(0, 5), required: true })}
        ${field({ label: 'End time', name: 'end_time', type: 'time', value: (s.end_time || '18:30').slice(0, 5), required: true, hint: 'An end before the start means an overnight shift.' })}
        ${field({ label: 'Grace period (minutes)', name: 'grace_minutes', type: 'number', value: s.grace_minutes, required: true, attrs: 'min="0" max="240"', hint: 'Check-ins within this time count as on time.' })}
        ${field({ label: 'Unpaid break (minutes)', name: 'break_minutes', type: 'number', value: s.break_minutes, required: true, attrs: 'min="0" max="480"', hint: 'Subtracted to get the standard working day.' })}
        ${field({ label: 'Description', name: 'description', value: s.description, span2: true, attrs: 'maxlength="255"' })}
        ${field({ label: 'Default shift for employees without an assignment', name: 'is_default', type: 'checkbox', value: s.is_default, span2: true })}
        ${field({ label: 'Active (can be assigned)', name: 'is_active', type: 'checkbox', value: s.is_active, span2: true })}
      </div>`,
      onSubmit: async (formData, ctx) => {
        const payload = {
          name: formData.get('name'), start_time: formData.get('start_time'), end_time: formData.get('end_time'),
          grace_minutes: formData.get('grace_minutes'), break_minutes: formData.get('break_minutes'), description: formData.get('description') || '',
          is_default: formData.get('is_default') === 'on', is_active: formData.get('is_active') === 'on',
        };
        if (shift) await api.put(`/shifts/${shift.id}/`, payload); else await api.post('/shifts/', payload);
        ctx.close(); App.toast(shift ? 'Shift updated.' : 'Shift created.'); loadShifts();
      },
    });
  }

  async function removeShift(shift) {
    const ok = await App.confirm({ title: `Delete ${shift.name}?`, message: 'Shifts that have employee assignments are kept for their records; deactivate those instead.', confirmLabel: 'Delete', danger: true });
    if (!ok) return;
    try { await api.delete(`/shifts/${shift.id}/`); App.toast('Shift deleted.'); loadShifts(); } catch (error) { App.error(error); }
  }

  async function loadAssignments() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(6, 5);
    try {
      const data = await api.get('/shifts/assignments/', { page: state.page, page_size: state.pageSize, search: state.search, shift: state.shift, on: state.current ? App.todayISO() : '' });
      if (!data.results.length && state.page > 1) { state.page -= 1; return loadAssignments(); }
      const today = App.todayISO();
      rows.innerHTML = data.results.length ? html`${data.results.map(a => {
        const active = a.start_date <= today && (!a.end_date || a.end_date >= today);
        return html`<tr>
          <td><div class="cell-main">${a.employee_name}</div><div class="cell-sub mono">${a.employee_code}</div></td>
          <td><div>${a.shift.name}</div><div class="cell-sub">${hours(a.shift)}</div></td>
          <td class="nowrap">${fmt.date(a.start_date)}</td>
          <td class="nowrap">${a.end_date ? fmt.date(a.end_date) : html`<span class="badge badge-success">Ongoing</span>`}${active && a.end_date ? html` <span class="badge badge-info">Current</span>` : ''}</td>
          <td>${a.notes || '—'}</td>
          <td><div class="actions"><button class="btn btn-sm" type="button" data-edit="${a.id}">${icon('edit', 'icon-sm')} Edit</button><button class="btn btn-sm btn-danger" type="button" data-remove="${a.id}" aria-label="Remove assignment">${icon('trash', 'icon-sm')}</button></div></td>
        </tr>`;
      })}` : App.emptyRow(6, { iconName: 'users', title: state.search || state.shift || state.current ? 'No assignments match your filters' : 'No shift assignments yet', text: 'Use "Assign shift" to put employees on a shift.' });
      $$('[data-edit]', rows).forEach(b => b.addEventListener('click', () => editAssignment(data.results.find(a => String(a.id) === b.dataset.edit))));
      $$('[data-remove]', rows).forEach(b => b.addEventListener('click', () => removeAssignment(data.results.find(a => String(a.id) === b.dataset.remove))));
      App.pager($('#pager'), { page: state.page, count: data.count, pageSize: state.pageSize }, page => { state.page = page; loadAssignments(); });
    } catch (error) {
      rows.innerHTML = App.errorRow(6, error.message);
      $('[data-retry]', rows).addEventListener('click', loadAssignments);
      $('#pager').hidden = true;
    }
  }

  async function openAssign() {
    const active = shifts.filter(s => s.is_active);
    if (!active.length) { App.toast('Create an active shift first.', 'error'); return; }
    let employees;
    try { employees = await api.get('/employees/', { status: 'ACTIVE' }); } catch (error) { App.error(error); return; }
    App.modal({
      title: 'Assign shift', subtitle: 'Choose a shift, the employees and the dates.', wide: true, submitLabel: 'Assign',
      body: html`<div class="form-grid">
        ${field({ label: 'Shift', name: 'shift_id', type: 'select', options: active.map(s => [s.id, `${s.name} (${hours(s)})`]), span2: true })}
        ${field({ label: 'From', name: 'start_date', type: 'date', value: App.todayISO(), required: true })}
        ${field({ label: 'To (optional)', name: 'end_date', type: 'date', hint: 'Leave empty for an ongoing assignment.' })}
        <div class="field span-2"><label for="pickSearch">Employees <span class="subtle">*</span></label>
          <input class="input" id="pickSearch" type="search" placeholder="Filter employees" aria-label="Filter employees">
          <div class="checklist" id="picker" role="group" aria-label="Employees">${employees.map(e => html`<label class="check" data-text="${`${e.full_name} ${e.employee_id} ${e.department}`.toLowerCase()}"><input type="checkbox" name="employee_ids" value="${e.user_id}"> ${e.full_name} <span class="muted">· ${e.employee_id} · ${e.department}</span></label>`)}</div>
          <div class="row" style="gap:8px;margin-top:6px"><button class="link-btn" type="button" id="pickAll">Select shown</button><button class="link-btn" type="button" id="pickNone">Clear</button><span class="muted" id="pickCount">0 selected</span></div>
        </div>
        ${field({ label: 'Notes', name: 'notes', span2: true, attrs: 'maxlength="255"' })}
        ${field({ label: 'Replace current shift (end the earlier assignment the day before)', name: 'replace', type: 'checkbox', span2: true })}
      </div>`,
      onOpen: ({ dialog }) => {
        const boxes = () => $$('input[name=employee_ids]', dialog);
        const count = () => { $('#pickCount', dialog).textContent = `${boxes().filter(b => b.checked).length} selected`; };
        $('#picker', dialog).addEventListener('change', count);
        $('#pickSearch', dialog).addEventListener('input', event => {
          const term = event.target.value.trim().toLowerCase();
          $$('#picker label', dialog).forEach(label => { label.hidden = term && !label.dataset.text.includes(term); });
        });
        $('#pickAll', dialog).addEventListener('click', () => { $$('#picker label', dialog).forEach(label => { if (!label.hidden) $('input', label).checked = true; }); count(); });
        $('#pickNone', dialog).addEventListener('click', () => { boxes().forEach(b => { b.checked = false; }); count(); });
      },
      onSubmit: async (formData, ctx) => {
        const ids = formData.getAll('employee_ids').map(Number);
        if (!ids.length) throw new Error('Choose at least one employee.');
        const created = await api.post('/shifts/assignments/', {
          shift_id: Number(formData.get('shift_id')), employee_ids: ids, start_date: formData.get('start_date'),
          end_date: formData.get('end_date') || null, notes: formData.get('notes') || '', replace: formData.get('replace') === 'on',
        });
        ctx.close(); App.toast(`${created.length} employee${created.length === 1 ? '' : 's'} assigned.`);
        loadShifts(); loadAssignments();
      },
    });
  }

  function editAssignment(a) {
    App.modal({
      title: 'Edit shift assignment', subtitle: `${a.employee_name} · ${a.employee_code}`, submitLabel: 'Save changes',
      body: html`<div class="form-grid">
        ${field({ label: 'Shift', name: 'shift_id', type: 'select', value: a.shift.id, options: shifts.filter(s => s.is_active || s.id === a.shift.id).map(s => [s.id, `${s.name} (${hours(s)})`]), span2: true })}
        ${field({ label: 'From', name: 'start_date', type: 'date', value: a.start_date, required: true })}
        ${field({ label: 'To (optional)', name: 'end_date', type: 'date', value: a.end_date || '' })}
        ${field({ label: 'Notes', name: 'notes', value: a.notes, span2: true, attrs: 'maxlength="255"' })}
      </div>`,
      onSubmit: async (formData, ctx) => {
        await api.put(`/shifts/assignments/${a.id}/`, { shift_id: Number(formData.get('shift_id')), start_date: formData.get('start_date'), end_date: formData.get('end_date') || null, notes: formData.get('notes') || '' });
        ctx.close(); App.toast('Assignment updated.'); loadShifts(); loadAssignments();
      },
    });
  }

  async function removeAssignment(a) {
    const ok = await App.confirm({ title: 'Remove this assignment?', message: `${a.employee_name} will no longer be on ${a.shift.name} from ${fmt.date(a.start_date)}. Past attendance keeps its recorded shift.`, confirmLabel: 'Remove', danger: true });
    if (!ok) return;
    try { await api.delete(`/shifts/assignments/${a.id}/`); App.toast('Assignment removed.'); loadShifts(); loadAssignments(); } catch (error) { App.error(error); }
  }

  $('#addShift').addEventListener('click', () => openShift(null));
  $('#assignBtn').addEventListener('click', openAssign);
  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); state.page = 1; loadAssignments(); }));
  $('#shiftFilter').addEventListener('change', e => { state.shift = e.target.value; state.page = 1; loadAssignments(); });
  $('#currentOnly').addEventListener('change', e => { state.current = e.target.checked; state.page = 1; loadAssignments(); });
  await loadShifts();
  loadAssignments();
})();
