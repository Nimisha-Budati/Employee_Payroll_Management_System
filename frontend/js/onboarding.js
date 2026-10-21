(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  await App.boot({ role: 'ADMIN', nav: 'onboarding' });
  $('#searchIcon').innerHTML = icon('search');
  $('#settingsBtn').innerHTML = html`${icon('sliders')} Checklist settings`;
  const DOC_TYPES = [['IDENTITY', 'Identity proof'], ['ADDRESS', 'Address proof'], ['EDUCATION', 'Education certificate'], ['RESUME', 'Resume']];
  const params = new URLSearchParams(location.search);
  const state = { state: params.get('state') || 'OPEN', search: '', department: '' };
  let data = null;

  try {
    const meta = await api.get('/employees/meta/');
    $('#department').innerHTML = html`<option value="">All departments</option>${meta.departments.map(d => html`<option value="${d}">${d}</option>`)}`;
  } catch (error) { /* department filter stays at "All" */ }
  const selectTab = () => $$('[data-state]').forEach(t => t.setAttribute('aria-selected', String(t.dataset.state === state.state)));
  selectTab();

  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(6, 4);
    try {
      data = await api.get('/onboarding/', { state: state.state, search: state.search, department: state.department });
    } catch (error) {
      rows.innerHTML = App.errorRow(6, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
      return;
    }
    const c = data.counts;
    $('#stats').innerHTML = html`
      <button class="card stat" type="button" data-jump="READY"><span class="stat-icon blue">${icon('checkCircle')}</span><div><div class="stat-label">Ready for review</div><div class="stat-value">${c.READY}</div><div class="stat-note">Everything provided</div></div></button>
      <button class="card stat" type="button" data-jump="IN_PROGRESS"><span class="stat-icon amber">${icon('clock')}</span><div><div class="stat-label">In progress</div><div class="stat-value">${c.IN_PROGRESS}</div><div class="stat-note">Items still missing</div></div></button>
      <button class="card stat" type="button" data-jump="COMPLETED"><span class="stat-icon green">${icon('check')}</span><div><div class="stat-label">Completed</div><div class="stat-value">${c.COMPLETED}</div><div class="stat-note">Active employees</div></div></button>`;
    $$('[data-jump]').forEach(b => b.addEventListener('click', () => { state.state = b.dataset.jump; selectTab(); load(); }));
    rows.innerHTML = data.results.length ? html`${data.results.map(r => {
      const percent = r.total ? Math.round((100 * r.done) / r.total) : 0;
      return html`<tr>
        <td><div class="cell-main">${r.employee_name}</div><div class="cell-sub mono">${r.employee_code} · ${r.department || '—'}</div></td>
        <td class="nowrap">${fmt.date(r.joining_date)}</td>
        <td><div class="progress-label"><span>${r.done} / ${r.total}</span><span>${percent}%</span></div><div class="progress" role="progressbar" aria-valuenow="${percent}" aria-valuemin="0" aria-valuemax="100" aria-label="Progress for ${r.employee_name}"><span style="width:${percent}%"></span></div></td>
        <td style="min-width:200px">${r.missing.length ? html`<span class="cell-sub">${r.missing.join(', ')}</span>` : html`<span class="subtle">Nothing</span>`}</td>
        <td>${App.badge(r.state)}${r.completed_at ? html`<div class="cell-sub">${r.completed_by || 'Administrator'} · ${fmt.date(r.completed_at)}</div>` : ''}</td>
        <td><div class="actions">
          <button class="btn btn-sm" type="button" data-view="${r.employee_pk}">${icon('eye', 'icon-sm')} Checklist</button>
          ${r.state === 'READY' ? html`<button class="btn btn-sm btn-success" type="button" data-complete="${r.employee_pk}">Complete</button>` : ''}
          ${r.state === 'IN_PROGRESS' ? html`<button class="btn btn-sm" type="button" data-remind="${r.employee_pk}">${icon('bell', 'icon-sm')} Remind</button>` : ''}
          ${r.state === 'COMPLETED' ? html`<button class="btn btn-sm" type="button" data-reopen="${r.employee_pk}">Reopen</button>` : ''}
        </div></td></tr>`;
    })}` : App.emptyRow(6, state.search || state.department
      ? { iconName: 'search', title: 'No employees match your search' }
      : { iconName: 'checkCircle', title: { OPEN: 'No open onboarding', READY: 'No one is waiting for review', IN_PROGRESS: 'No onboarding in progress', COMPLETED: 'No completed onboarding yet' }[state.state], text: state.state === 'OPEN' ? 'New employees appear here until their onboarding is completed.' : '' });
    const find = pk => data.results.find(r => String(r.employee_pk) === pk);
    $$('[data-view]', rows).forEach(b => b.addEventListener('click', () => view(find(b.dataset.view))));
    $$('[data-complete]', rows).forEach(b => b.addEventListener('click', () => complete(find(b.dataset.complete))));
    $$('[data-remind]', rows).forEach(b => b.addEventListener('click', () => remind(find(b.dataset.remind))));
    $$('[data-reopen]', rows).forEach(b => b.addEventListener('click', () => reopen(find(b.dataset.reopen))));
  }

  const checklistHtml = r => html`<ul class="onboarding-list">${r.items.map(item => html`<li class="${item.done ? 'done' : ''}">
    <span class="check-mark" aria-hidden="true">${icon(item.done ? 'check' : 'clock')}</span>
    <div><div class="cell-main">${item.label} <span class="sr-only">${item.done ? 'done' : 'not done'}</span></div>
    <div class="cell-sub">${item.state}${item.hint ? ` · ${item.hint}` : ''} · ${item.owner === 'ADMIN' ? 'administrator' : 'employee'}</div></div></li>`)}</ul>`;

  function view(r) {
    App.modal({
      title: r.employee_name, subtitle: `${r.employee_code} · joined ${fmt.date(r.joining_date)}`, cancelLabel: 'Close', wide: true,
      body: html`${checklistHtml(r)}
        ${r.note ? html`<p class="muted" style="margin-top:12px">Note: ${r.note}</p>` : ''}
        <p class="muted" style="margin-top:12px">Documents are verified on <a href="admin-documents.html?expiry=">Documents</a>; salary structures on <a href="admin-salary.html">Salary structures</a>; department and designation on <a href="employee-management.html">Employees</a>.</p>`,
    });
  }

  function complete(r) {
    App.modal({
      title: 'Complete onboarding', subtitle: `${r.employee_name} · ${r.employee_code}`, submitLabel: 'Mark complete', submitVariant: 'success',
      body: html`<div class="form-grid"><div class="span-2">${checklistHtml(r)}</div>
        ${field({ label: 'Review note (optional)', name: 'note', type: 'textarea', span2: true, attrs: 'maxlength="255"' })}</div>`,
      onSubmit: async (formData, ctx) => {
        await api.post(`/onboarding/${r.employee_pk}/complete/`, { note: formData.get('note') || '' });
        ctx.close(); App.toast('Onboarding completed; the employee was notified.'); load();
      },
    });
  }

  async function remind(r) {
    try {
      const result = await api.post(`/onboarding/${r.employee_pk}/remind/`);
      App.toast(`Reminder sent: ${result.missing.join(', ')}.`);
    } catch (error) { App.error(error); }
  }

  function reopen(r) {
    App.modal({
      title: 'Reopen onboarding', subtitle: `${r.employee_name} · ${r.employee_code}`, submitLabel: 'Reopen',
      body: html`<div class="form-grid">${field({ label: 'Reason (shown to the employee)', name: 'note', type: 'textarea', required: true, span2: true, attrs: 'maxlength="255"' })}</div>`,
      onSubmit: async (formData, ctx) => {
        await api.post(`/onboarding/${r.employee_pk}/reopen/`, { note: formData.get('note') });
        ctx.close(); App.toast('Onboarding reopened.'); load();
      },
    });
  }

  function settings() {
    const s = data ? data.settings : { required_document_types: [], require_address: true, require_profile_photo: false, require_salary_structure: true };
    App.modal({
      title: 'Onboarding checklist', submitLabel: 'Save checklist',
      body: html`<div class="form-grid">
        <p class="span-2 muted">Name, email, phone, department and designation are always required. Only ask for what you need: no extra personal information is collected.</p>
        <fieldset class="span-2" style="border:0;padding:0;margin:0"><legend style="font-weight:600;margin-bottom:8px">Required documents</legend>
          ${DOC_TYPES.map(([code, label]) => field({ label, name: `doc_${code}`, type: 'checkbox', value: s.required_document_types.includes(code) }))}</fieldset>
        ${field({ label: 'Postal address', name: 'require_address', type: 'checkbox', value: s.require_address, span2: true })}
        ${field({ label: 'Profile photo', name: 'require_profile_photo', type: 'checkbox', value: s.require_profile_photo, span2: true })}
        ${field({ label: 'Salary structure set by an administrator', name: 'require_salary_structure', type: 'checkbox', value: s.require_salary_structure, span2: true })}
      </div>`,
      onSubmit: async (formData, ctx) => {
        await api.put('/onboarding/settings/', {
          required_document_types: DOC_TYPES.map(([code]) => code).filter(code => formData.get(`doc_${code}`) === 'on'),
          require_address: formData.get('require_address') === 'on',
          require_profile_photo: formData.get('require_profile_photo') === 'on',
          require_salary_structure: formData.get('require_salary_structure') === 'on',
        });
        ctx.close(); App.toast('Checklist saved.'); load();
      },
    });
  }

  $$('[data-state]').forEach(tab => tab.addEventListener('click', () => { state.state = tab.dataset.state; selectTab(); load(); }));
  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); load(); }));
  $('#department').addEventListener('change', e => { state.department = e.target.value; load(); });
  $('#settingsBtn').addEventListener('click', settings);
  load();
})();
