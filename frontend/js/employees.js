(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  await App.boot({ role: 'ADMIN', nav: 'employees' });

  $('#addEmployee').innerHTML = html`${icon('plus')} Add employee`;
  $('#deptBtn').innerHTML = html`${icon('layers')} Departments`;
  $('#excelBtn').innerHTML = html`${icon('spreadsheet')} Excel`;
  $('#searchIcon').innerHTML = icon('search');

  const state = { page: 1, pageSize: 10, search: '', status: '', department: '', ordering: 'employee_id' };
  let meta = { departments: [], pending_accounts: [] };

  async function loadMeta() {
    try { meta = await api.get('/employees/meta/'); } catch (error) { App.error(error); return; }
    const current = $('#deptFilter').value;
    $('#deptFilter').innerHTML = html`<option value="">All departments</option>${meta.departments.map(name => html`<option value="${name}"${name === current ? App.raw(' selected') : ''}>${name}</option>`)}`;
    const box = $('#pendingBox');
    box.hidden = !meta.pending_accounts.length;
    if (meta.pending_accounts.length) {
      box.innerHTML = html`<div class="row" style="justify-content:space-between"><div><strong>${meta.pending_accounts.length} registered account${meta.pending_accounts.length === 1 ? '' : 's'} waiting for an employee record</strong><div>These people signed up themselves and cannot appear in payroll until you complete their details.</div></div></div>
        <div class="row" style="margin-top:10px">${meta.pending_accounts.map(account => html`<button class="btn btn-sm" type="button" data-onboard="${account.user_id}">${icon('plus', 'icon-sm')} ${account.full_name} <span class="muted">(${account.username})</span></button>`)}</div>`;
      $$('[data-onboard]', box).forEach(button => button.addEventListener('click', () => openForm(null, meta.pending_accounts.find(a => String(a.user_id) === button.dataset.onboard))));
    }
  }

  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(7, 6);
    try {
      const data = await api.get('/employees/', { page: state.page, page_size: state.pageSize, search: state.search, status: state.status, department: state.department, ordering: state.ordering });
      if (!data.results.length && state.page > 1) { state.page -= 1; return load(); }
      rows.innerHTML = data.results.length ? html`${data.results.map(rowHtml)}` : App.emptyRow(7, {
        iconName: 'users', title: state.search || state.status || state.department ? 'No employees match your filters' : 'No employees yet',
        text: state.search || state.status || state.department ? 'Try a different search or clear the filters.' : 'Add your first employee to get started.',
      });
      $$('[data-edit]', rows).forEach(button => button.addEventListener('click', () => openForm(data.results.find(item => String(item.id) === button.dataset.edit))));
      $$('[data-toggle]', rows).forEach(button => button.addEventListener('click', () => toggleStatus(data.results.find(item => String(item.id) === button.dataset.toggle))));
      App.pager($('#pager'), { page: state.page, count: data.count, pageSize: state.pageSize }, page => { state.page = page; load(); });
    } catch (error) {
      rows.innerHTML = App.errorRow(7, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
      $('#pager').hidden = true;
    }
  }

  function rowHtml(employee) {
    const active = employee.status === 'ACTIVE';
    return html`<tr>
      <td><div class="row" style="flex-wrap:nowrap"><span class="avatar avatar-sm">${fmt.initials(employee.full_name)}</span><div><div class="cell-main">${employee.full_name}</div><div class="cell-sub">${employee.email}</div></div></div></td>
      <td class="mono">${employee.employee_id}</td>
      <td><div>${employee.department}</div><div class="cell-sub">${employee.designation}</div></td>
      <td class="nowrap">${fmt.date(employee.joining_date)}</td>
      <td>${App.badge(employee.status)}</td>
      <td>${employee.has_salary_structure ? App.badge('APPROVED', 'Configured') : html`<a href="admin-salary.html" class="badge badge-warning" title="Set up this employee's salary">Not set</a>`}</td>
      <td><div class="actions">
        <button class="btn btn-sm" type="button" data-edit="${employee.id}">${icon('edit', 'icon-sm')} Edit</button>
        <button class="btn btn-sm ${active ? '' : 'btn-success'}" type="button" data-toggle="${employee.id}">${active ? 'Deactivate' : 'Reactivate'}</button>
      </div></td>
    </tr>`;
  }

  function openForm(employee, pendingAccount) {
    const editing = Boolean(employee);
    const source = employee || {};
    const [firstName, ...rest] = (pendingAccount && pendingAccount.full_name !== pendingAccount.username ? pendingAccount.full_name : '').split(' ');
    const body = html`<div class="form-grid">
      ${editing ? '' : pendingAccount
        ? html`<div class="span-2 alert alert-info">${icon('info')}<span>Completing the employment record for <strong>${pendingAccount.username}</strong> (${pendingAccount.email}).</span></div><input type="hidden" name="user_id" value="${pendingAccount.user_id}">`
        : html`<span class="fieldset-title">Account</span>
          ${field({ label: 'Username', name: 'username', required: true, attrs: 'autocomplete="off"' })}
          ${field({ label: 'Email', name: 'email', type: 'email', required: true })}
          ${field({ label: 'Temporary password', name: 'password', type: 'password', required: true, hint: 'The employee can change it after signing in.', span2: true, attrs: 'autocomplete="new-password"' })}`}
      <span class="fieldset-title">Personal</span>
      ${field({ label: 'First name', name: 'first_name', value: source.first_name || firstName || '' })}
      ${field({ label: 'Last name', name: 'last_name', value: source.last_name || rest.join(' ') })}
      ${editing ? field({ label: 'Email', name: 'email', type: 'email', value: source.email, required: true }) : ''}
      ${field({ label: 'Phone', name: 'phone', type: 'tel', value: source.phone, required: true, placeholder: '9876543210' })}
      <span class="fieldset-title">Employment</span>
      ${field({ label: 'Employee ID', name: 'employee_id', value: source.employee_id, required: true, placeholder: 'EMP001' })}
      ${field({ label: 'Joining date', name: 'joining_date', type: 'date', value: source.joining_date, required: true })}
      <div class="field"><label for="f-department">Department <span class="subtle">*</span></label><input class="input" id="f-department" name="department" list="deptList" value="${source.department || ''}" required><datalist id="deptList">${meta.departments.map(name => html`<option value="${name}">`)}</datalist></div>
      ${field({ label: 'Designation', name: 'designation', value: source.designation, required: true })}
      ${editing ? field({ label: 'Status', name: 'status', type: 'select', value: source.status, options: [['ACTIVE', 'Active'], ['INACTIVE', 'Inactive']], hint: 'Inactive employees cannot sign in and are skipped in payroll.' }) : ''}
    </div>`;
    App.modal({
      title: editing ? 'Edit employee' : (pendingAccount ? 'Complete employee record' : 'Add employee'),
      subtitle: editing ? `${source.employee_id} · ${source.username}` : '',
      body, wide: true, submitLabel: editing ? 'Save changes' : 'Add employee',
      onSubmit: async (formData, ctx) => {
        const payload = Object.fromEntries(formData);
        if (payload.user_id) payload.user_id = Number(payload.user_id);
        if (editing) await api.put(`/employees/${employee.id}/`, payload);
        else await api.post('/employees/', payload);
        ctx.close();
        App.toast(editing ? 'Employee updated.' : 'Employee added.');
        await Promise.all([load(), loadMeta()]);
      },
    });
  }

  async function toggleStatus(employee) {
    const deactivate = employee.status === 'ACTIVE';
    const ok = await App.confirm({
      title: deactivate ? 'Deactivate employee?' : 'Reactivate employee?',
      message: deactivate ? `${employee.full_name} will no longer be able to sign in and will be skipped in payroll. Their records are kept.` : `${employee.full_name} will be able to sign in again.`,
      confirmLabel: deactivate ? 'Deactivate' : 'Reactivate', danger: deactivate,
    });
    if (!ok) return;
    try {
      if (deactivate) await api.delete(`/employees/${employee.id}/`); else await api.put(`/employees/${employee.id}/`, { status: 'ACTIVE' });
      App.toast(deactivate ? 'Employee deactivated.' : 'Employee reactivated.');
      load();
    } catch (error) { App.error(error); }
  }

  $('#addEmployee').addEventListener('click', () => openForm(null));
  $('#excelBtn').addEventListener('click', () => App.download('/reports/excel/employees/', `employees_${App.todayISO()}.xlsx`, { status: state.status, department: state.department, search: state.search }));
  $('#deptBtn').addEventListener('click', openDepartments);

  async function openDepartments() {
    let departments;
    try { departments = await api.get('/employees/departments/'); } catch (error) { return App.error(error); }
    const ctx = App.modal({
      title: 'Departments and designations', subtitle: 'Rename a department or designation for every employee at once (renaming to an existing name merges them).', wide: true, cancelLabel: 'Close',
      body: departments.length ? html`<div class="table-wrap"><table class="table"><thead><tr><th>Department</th><th class="right">Employees</th><th>Designations</th><th class="right">Actions</th></tr></thead><tbody>
        ${departments.map(d => html`<tr><td class="cell-main">${d.name}</td><td class="right num">${d.headcount}<div class="cell-sub">${d.active} active</div></td>
          <td>${d.designations.map(g => html`<button class="badge" type="button" data-rename-designation="${g.name}" title="Rename designation" style="cursor:pointer;margin:2px">${g.name} (${g.headcount}) ${icon('edit', 'icon-sm')}</button>`)}</td>
          <td><div class="actions"><button class="btn btn-sm" type="button" data-rename-department="${d.name}">${icon('edit', 'icon-sm')} Rename</button></div></td></tr>`)}
      </tbody></table></div>` : App.empty({ iconName: 'layers', title: 'No departments yet', text: 'Departments are created when you add employees.' }),
    });
    const rename = (kind, old) => App.modal({
      title: `Rename ${kind}`, subtitle: `Currently "${old}"`, submitLabel: 'Rename',
      body: html`<div class="form-grid">${field({ label: `New ${kind} name`, name: 'new', value: old, required: true, span2: true, attrs: 'maxlength="100"' })}</div>`,
      onSubmit: async (formData, inner) => {
        const result = await api.post('/employees/departments/rename/', { kind, old, new: formData.get('new') });
        inner.close(); ctx.close(); App.toast(`${result.updated} employee record${result.updated === 1 ? '' : 's'} updated.`);
        await Promise.all([load(), loadMeta()]); openDepartments();
      },
    });
    $$('[data-rename-department]', ctx.dialog).forEach(b => b.addEventListener('click', () => rename('department', b.dataset.renameDepartment)));
    $$('[data-rename-designation]', ctx.dialog).forEach(b => b.addEventListener('click', () => rename('designation', b.dataset.renameDesignation)));
  }
  $('#search').addEventListener('input', App.debounce(event => { state.search = event.target.value.trim(); state.page = 1; load(); }));
  $('#statusFilter').addEventListener('change', event => { state.status = event.target.value; state.page = 1; load(); });
  $('#deptFilter').addEventListener('change', event => { state.department = event.target.value; state.page = 1; load(); });
  $$('.sort-btn').forEach(button => button.addEventListener('click', () => {
    const key = button.dataset.sort;
    state.ordering = state.ordering === key ? `-${key}` : key;
    state.page = 1;
    $$('.sort-btn').forEach(other => other.removeAttribute('aria-sort'));
    button.setAttribute('aria-sort', state.ordering.startsWith('-') ? 'descending' : 'ascending');
    load();
  }));

  await loadMeta();
  load();
})();
