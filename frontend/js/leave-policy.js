(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  await App.boot({ role: 'ADMIN', nav: 'leavePolicy' });
  $('#addType').innerHTML = html`${icon('plus')} New leave type`;

  let types = [];
  let rules = null;
  const days = n => `${n} day${Number(n) === 1 ? '' : 's'}`;

  /* ---- leave types ---- */
  async function loadTypes() {
    const rows = $('#typeRows');
    rows.innerHTML = App.skeletonRows(7, 4);
    try { types = await api.get('/leave-types/', { all: 'true' }); } catch (error) {
      rows.innerHTML = App.errorRow(7, error.message);
      $('[data-retry]', rows).addEventListener('click', loadTypes);
      return;
    }
    rows.innerHTML = types.length ? html`${types.map(t => html`<tr${t.is_active ? '' : App.raw(' class="row-muted"')}>
      <td><div class="cell-main">${t.name}</div>${t.description ? html`<div class="cell-sub">${t.description}</div>` : ''}</td>
      <td class="right num">${t.annual_days === null ? html`<span class="muted">No limit</span>` : html`<strong>${t.annual_days}</strong>`}</td>
      <td>${t.is_paid ? html`<span class="badge badge-success">Paid</span>` : html`<span class="badge badge-warning">Unpaid</span>`}</td>
      <td>${t.allow_carry_forward ? `Up to ${days(t.max_carry_forward_days)}` : html`<span class="muted">No</span>`}</td>
      <td class="right num">${t.request_count}</td>
      <td>${App.badge(t.is_active ? 'ACTIVE' : 'INACTIVE')}</td>
      <td><div class="actions">
        <button class="btn btn-sm" type="button" data-edit="${t.id}">${icon('edit', 'icon-sm')} Edit</button>
        <button class="btn btn-sm${t.is_active ? '' : ' btn-success'}" type="button" data-toggle="${t.id}">${t.is_active ? 'Deactivate' : 'Activate'}</button>
        ${t.request_count ? '' : html`<button class="btn btn-sm btn-danger" type="button" data-delete="${t.id}" aria-label="Delete ${t.name}">${icon('trash', 'icon-sm')}</button>`}
      </div></td></tr>`)}`
      : App.emptyRow(7, { iconName: 'calendar', title: 'No leave types yet', text: 'Create the leave types your organisation offers.' });
    const find = id => types.find(t => String(t.id) === id);
    $$('[data-edit]', rows).forEach(b => b.addEventListener('click', () => openType(find(b.dataset.edit))));
    $$('[data-toggle]', rows).forEach(b => b.addEventListener('click', () => toggleType(find(b.dataset.toggle))));
    $$('[data-delete]', rows).forEach(b => b.addEventListener('click', () => deleteType(find(b.dataset.delete))));
  }

  function openType(type) {
    const t = type || { is_paid: true, is_active: true, annual_days: 12, allow_carry_forward: false, max_carry_forward_days: 0, sort_order: (types.length + 1) * 10 };
    App.modal({
      title: type ? `Edit ${type.name}` : 'New leave type', wide: true, submitLabel: type ? 'Save changes' : 'Create leave type',
      body: html`<div class="form-grid">
        ${field({ label: 'Name', name: 'name', value: t.name, required: true, attrs: 'maxlength="50"', placeholder: 'e.g. Maternity Leave' })}
        ${field({ label: 'Display order', name: 'sort_order', type: 'number', value: t.sort_order, attrs: 'min="0" max="999"', hint: 'Lower numbers are listed first.' })}
        ${field({ label: 'Description', name: 'description', value: t.description, span2: true, attrs: 'maxlength="255"', hint: 'Shown to employees when they apply.' })}
        ${field({ label: 'Annual limit', name: 'limit_mode', type: 'select', value: t.annual_days === null ? 'none' : 'days', options: [['days', 'Limited number of days'], ['none', 'No annual limit']] })}
        ${field({ label: 'Allowed days per employee per leave year', name: 'annual_days', type: 'number', value: t.annual_days ?? '', attrs: 'min="0" max="366" step="1"' })}
        ${field({ label: 'Paid leave (unchecked = unpaid, counted as loss of pay)', name: 'is_paid', type: 'checkbox', value: t.is_paid, span2: true })}
        ${field({ label: 'Unused days can be carried forward to the next leave year', name: 'allow_carry_forward', type: 'checkbox', value: t.allow_carry_forward, span2: true })}
        ${field({ label: 'Maximum days carried forward', name: 'max_carry_forward_days', type: 'number', value: t.max_carry_forward_days || '', attrs: 'min="1" max="366" step="1"' })}
        ${field({ label: 'Active (employees can apply for it)', name: 'is_active', type: 'checkbox', value: t.is_active, span2: true })}
        ${type && type.request_count ? html`<p class="span-2 muted" style="margin:0">${days(type.request_count)} of requests use this type. Changing the allowance updates every employee's balance immediately; past requests are kept.</p>` : ''}
      </div>`,
      onOpen: ({ form }) => {
        const sync = () => {
          const limited = form.elements.limit_mode.value === 'days';
          form.elements.annual_days.disabled = !limited;
          form.elements.annual_days.required = limited;
          form.elements.allow_carry_forward.disabled = !limited;
          if (!limited) form.elements.allow_carry_forward.checked = false;
          form.elements.max_carry_forward_days.disabled = !form.elements.allow_carry_forward.checked;
          form.elements.max_carry_forward_days.required = form.elements.allow_carry_forward.checked;
        };
        form.elements.limit_mode.addEventListener('change', sync);
        form.elements.allow_carry_forward.addEventListener('change', sync);
        sync();
      },
      onSubmit: async (formData, ctx) => {
        const limited = formData.get('limit_mode') === 'days';
        const carry = formData.get('allow_carry_forward') === 'on';
        const payload = {
          name: formData.get('name'), description: formData.get('description') || '', sort_order: Number(formData.get('sort_order') || 0),
          annual_days: limited ? Number(formData.get('annual_days')) : null, is_paid: formData.get('is_paid') === 'on',
          is_active: formData.get('is_active') === 'on', allow_carry_forward: limited && carry,
          max_carry_forward_days: limited && carry ? Number(formData.get('max_carry_forward_days') || 0) : 0,
        };
        if (limited && (formData.get('annual_days') === '' || payload.annual_days < 0)) throw new Error('Enter the number of allowed days (0 or more).');
        if (type) await api.put(`/leave-types/${type.id}/`, payload); else await api.post('/leave-types/', payload);
        ctx.close();
        App.toast(type ? `${payload.name} updated. Employee balances now use the new settings.` : `${payload.name} created.`);
        loadTypes(); loadBalances();
      },
    });
  }

  async function toggleType(type) {
    const activate = !type.is_active;
    const ok = await App.confirm({
      title: `${activate ? 'Activate' : 'Deactivate'} ${type.name}?`,
      message: activate ? 'Employees will be able to apply for this leave type again.' : 'Employees can no longer apply for it. Existing requests and their history are kept.',
      confirmLabel: activate ? 'Activate' : 'Deactivate', danger: !activate,
    });
    if (!ok) return;
    try { await api.patch(`/leave-types/${type.id}/`, { is_active: activate }); App.toast(`${type.name} ${activate ? 'activated' : 'deactivated'}.`); loadTypes(); loadBalances(); }
    catch (error) { App.error(error); }
  }

  async function deleteType(type) {
    const ok = await App.confirm({ title: `Delete ${type.name}?`, message: 'It has no leave requests, so it can be removed permanently.', confirmLabel: 'Delete', danger: true });
    if (!ok) return;
    try { await api.delete(`/leave-types/${type.id}/`); App.toast(`${type.name} deleted.`); loadTypes(); } catch (error) { App.error(error); }
  }

  /* ---- leave rules ---- */
  async function loadRules() {
    try { rules = await api.get('/leave-policy/'); } catch (error) { $('#rulesForm').innerHTML = html`<div class="span-2 alert alert-danger">${icon('alert')}<span>${error.message}</span></div>`; return; }
    $('#yearNote').textContent = `Current leave year: ${rules.current_leave_year_label}`;
    $('#rulesForm').innerHTML = html`
      ${field({ label: 'Leave year starts in', name: 'leave_year_start_month', type: 'select', value: rules.leave_year_start_month, options: fmt.months.map((m, i) => [i + 1, m]), hint: 'January = calendar year; April = April to March.' })}
      ${field({ label: 'Minimum notice (days)', name: 'min_notice_days', type: 'number', value: rules.min_notice_days, attrs: 'min="0" max="365"', hint: '0 = employees can apply for today.' })}
      ${field({ label: 'Maximum days in one request', name: 'max_days_per_request', type: 'number', value: rules.max_days_per_request ?? '', attrs: 'min="1" max="366"', hint: 'Leave empty for no limit.' })}
      ${field({ label: 'Allow leave for past dates (e.g. sick leave after returning)', name: 'allow_past_dates', type: 'checkbox', value: rules.allow_past_dates, span2: true })}
      <div class="span-2"><div class="alert alert-danger" id="rulesError" hidden></div><button class="btn btn-primary" type="submit">${icon('check')} Save rules</button>
      ${rules.updated_at ? html`<span class="muted" style="margin-left:8px;font-size:12.5px">Last changed ${fmt.dateTime(rules.updated_at)}${rules.updated_by_username ? ` by ${rules.updated_by_username}` : ''}</span>` : ''}</div>`;
    $('#carryForm').innerHTML = html`
      ${field({ label: 'Carry unused days into leave year', name: 'year', type: 'number', value: rules.current_leave_year, required: true, attrs: 'min="2000" max="2100"', hint: 'Uses each type’s maximum and the employee’s unused days at the end of the previous leave year. Safe to run again.' })}
      <div class="span-2"><button class="btn" type="submit">${icon('refresh')} Carry forward</button></div>`;
    $('#balYear').value = $('#balYear').value || rules.current_leave_year;
  }

  $('#rulesForm').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.target, error = $('#rulesError');
    error.hidden = true;
    const button = $('button[type=submit]', form); button.disabled = true;
    try {
      await api.put('/leave-policy/', {
        leave_year_start_month: Number(form.elements.leave_year_start_month.value), min_notice_days: Number(form.elements.min_notice_days.value || 0),
        max_days_per_request: form.elements.max_days_per_request.value ? Number(form.elements.max_days_per_request.value) : null,
        allow_past_dates: form.elements.allow_past_dates.checked,
      });
      App.toast('Leave rules saved.');
      await loadRules(); loadBalances();
    } catch (err) {
      error.textContent = err.fields && Object.keys(err.fields).length ? Object.values(err.fields).join(' ') : err.message;
      error.hidden = false;
    } finally { button.disabled = false; }
  });

  $('#carryForm').addEventListener('submit', async event => {
    event.preventDefault();
    const year = Number(event.target.elements.year.value);
    const ok = await App.confirm({ title: `Carry unused leave into ${year}?`, message: `For every employee and each leave type that allows it, unused days from ${year - 1} (up to the type's maximum) are added to ${year}.`, confirmLabel: 'Carry forward' });
    if (!ok) return;
    try { const result = await api.post('/leave-policy/carry-forward/', { year }); App.toast(`Carry-forward recorded for ${result.balances_written} balance${result.balances_written === 1 ? '' : 's'}.`); loadBalances(); }
    catch (error) { App.error(error); }
  });

  /* ---- employee balances ---- */
  let people = [];
  async function loadPeople() {
    try { people = await api.get('/employees/', { status: 'ACTIVE' }); } catch (error) { people = []; }
    $('#balEmployee').innerHTML = html`<option value="">Choose an employee…</option>${people.map(p => html`<option value="${p.user_id}">${p.full_name} · ${p.employee_id}</option>`)}`;
  }

  async function loadBalances() {
    const rows = $('#balRows');
    const employee = $('#balEmployee').value;
    if (!employee) { rows.innerHTML = App.emptyRow(9, { iconName: 'users', title: 'Choose an employee', text: 'Their balance for each leave type appears here.' }); return; }
    rows.innerHTML = App.skeletonRows(9, 3);
    try {
      const data = await api.get('/leaves/balance/', { employee_id: employee, year: $('#balYear').value });
      const entries = Object.entries(data.balances);
      rows.innerHTML = entries.length ? html`${entries.map(([name, b]) => html`<tr>
        <td><div class="cell-main">${name}</div><div class="cell-sub">${b.is_paid ? 'Paid' : 'Unpaid'}${b.is_active ? '' : ' · inactive'}</div></td>
        <td class="right num">${b.unlimited ? '—' : b.entitled}</td><td class="right num">${b.carried_forward || '—'}</td>
        <td class="right num">${b.adjustment ? (b.adjustment > 0 ? `+${b.adjustment}` : b.adjustment) : '—'}</td>
        <td class="right num"><strong>${b.unlimited ? 'No limit' : b.total}</strong></td><td class="right num">${b.approved}</td>
        <td class="right num">${b.pending}</td><td class="right num"><strong>${b.unlimited ? '—' : b.available}</strong></td>
        <td><div class="actions">${b.unlimited ? '' : html`<button class="btn btn-sm" type="button" data-adjust="${b.id}" data-name="${name}" data-current="${b.adjustment}">Adjust</button>`}</div></td></tr>`)}`
        : App.emptyRow(9, { iconName: 'calendar', title: 'No leave types' });
      $$('[data-adjust]', rows).forEach(b => b.addEventListener('click', () => adjust(employee, b.dataset.adjust, b.dataset.name, b.dataset.current, data.year)));
    } catch (error) { rows.innerHTML = App.errorRow(9, error.message, false); }
  }

  function adjust(employee, typeId, name, current, year) {
    const person = people.find(p => String(p.user_id) === String(employee));
    App.modal({
      title: `Adjust ${name}`, subtitle: `${person ? person.full_name : ''} · leave year ${year}`, submitLabel: 'Save adjustment',
      body: html`<div class="form-grid">
        ${field({ label: 'Days to add (use a minus sign to remove)', name: 'adjustment', type: 'number', value: current, required: true, attrs: 'min="-366" max="366" step="1"' })}
        ${field({ label: 'Reason', name: 'note', span2: true, attrs: 'maxlength="255"', hint: 'Required when the adjustment is not 0. Recorded in the audit log.' })}
      </div>`,
      onSubmit: async (formData, ctx) => {
        await api.put('/leave-policy/balances/', { employee_id: Number(employee), leave_type_id: Number(typeId), year, adjustment: Number(formData.get('adjustment')), note: formData.get('note') });
        ctx.close(); App.toast('Balance adjusted.'); loadBalances();
      },
    });
  }

  $('#addType').addEventListener('click', () => openType(null));
  $('#balEmployee').addEventListener('change', loadBalances);
  $('#balYear').addEventListener('change', loadBalances);
  await Promise.all([loadTypes(), loadRules(), loadPeople()]);
  loadBalances();
})();
