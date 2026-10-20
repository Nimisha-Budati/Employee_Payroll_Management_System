(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  await App.boot({ role: 'ADMIN', nav: 'salary' });
  $('#searchIcon').innerHTML = icon('search');
  const state = { page: 1, pageSize: 10, search: '', configured: '' };

  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(6, 6);
    try {
      const data = await api.get('/payroll/salary-structures/', { page: state.page, page_size: state.pageSize, search: state.search, configured: state.configured, status: 'ACTIVE' });
      if (!data.results.length && state.page > 1) { state.page -= 1; return load(); }
      rows.innerHTML = data.results.length ? html`${data.results.map(item => html`<tr>
        <td><div class="cell-main">${item.full_name}</div><div class="cell-sub mono">${item.employee_id}</div></td>
        <td><div>${item.department}</div><div class="cell-sub">${item.designation}</div></td>
        <td class="right num">${item.structure ? fmt.money(item.structure.basic) : '—'}</td>
        <td class="right num">${item.structure ? html`<strong>${fmt.money(item.structure.gross_monthly)}</strong>` : App.badge('PENDING', 'Not set')}</td>
        <td>${item.structure ? fmt.date(item.structure.effective_from) : '—'}</td>
        <td><div class="actions"><button class="btn btn-sm ${item.structure ? '' : 'btn-primary'}" type="button" data-edit="${item.employee_pk}">${icon(item.structure ? 'edit' : 'plus', 'icon-sm')} ${item.structure ? 'Edit' : 'Set up'}</button></div></td>
      </tr>`)}` : App.emptyRow(6, state.search || state.configured
        ? { iconName: 'search', title: 'No employees match your filters', text: 'Try a different search or clear the filters.' }
        : { iconName: 'users', title: 'No active employees', text: 'Add employees first, then set up their salary.' });
      $$('[data-edit]', rows).forEach(b => b.addEventListener('click', () => openForm(data.results.find(i => String(i.employee_pk) === b.dataset.edit))));
      App.pager($('#pager'), { page: state.page, count: data.count, pageSize: state.pageSize }, page => { state.page = page; load(); });
    } catch (error) {
      rows.innerHTML = App.errorRow(6, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
      $('#pager').hidden = true;
    }
  }

  const MONEY_FIELDS = [
    ['basic', 'Basic pay', true], ['hra', 'House rent allowance'], ['da', 'Dearness allowance (DA)'], ['conveyance_allowance', 'Conveyance allowance'],
    ['medical_allowance', 'Medical allowance'], ['special_allowance', 'Special allowance'], ['other_allowance', 'Other allowance'],
  ];
  const DEDUCTION_FIELDS = [['professional_tax', 'Professional tax / month'], ['tds', 'Income tax (TDS) / month'], ['other_deduction', 'Other fixed deduction / month']];

  function openForm(item) {
    const s = item.structure || {};
    const moneyAttrs = 'min="0" step="0.01" inputmode="decimal"';
    const body = html`<div class="form-grid">
      <span class="fieldset-title">Earnings (per month)</span>
      ${MONEY_FIELDS.map(([name, label, required]) => field({ label: `${label} (₹)`, name, type: 'number', value: s[name] ?? (required ? '' : '0'), required: Boolean(required), attrs: moneyAttrs }))}
      <span class="fieldset-title">Bonus and overtime</span>
      ${field({ label: 'Monthly bonus (₹)', name: 'bonus', type: 'number', value: s.bonus ?? '0', attrs: moneyAttrs, hint: 'Paid in full each month; not reduced for loss of pay. One-off bonuses can be added on a draft payslip.' })}
      ${field({ label: 'Overtime pay per approved hour (₹)', name: 'overtime_rate', type: 'number', value: s.overtime_rate ?? '0', attrs: moneyAttrs, hint: 'Default rate for new overtime records.' })}
      <span class="fieldset-title">Deductions</span>
      ${field({ label: 'Provident fund (% of basic + DA)', name: 'pf_percent', type: 'number', value: s.pf_percent ?? '12', required: true, attrs: 'min="0" max="100" step="0.01"' })}
      ${DEDUCTION_FIELDS.map(([name, label]) => field({ label: `${label} (₹)`, name, type: 'number', value: s[name] ?? '0', attrs: moneyAttrs }))}
      <span class="fieldset-title">Effective</span>
      ${field({ label: 'Effective from', name: 'effective_from', type: 'date', value: s.effective_from || App.todayISO(), required: true })}
      <div class="span-2 muted" id="grossPreview" aria-live="polite"></div>
    </div>`;
    App.modal({
      title: item.structure ? 'Edit salary structure' : 'Set up salary structure', subtitle: `${item.full_name} · ${item.employee_id}`,
      body, wide: true, submitLabel: 'Save structure',
      onOpen: ({ form }) => {
        const update = () => {
          const total = MONEY_FIELDS.reduce((sum, [name]) => sum + (Number(form.elements[name].value) || 0), 0);
          const bonus = Number(form.elements.bonus.value) || 0;
          const pf = ((Number(form.elements.basic.value) || 0) + (Number(form.elements.da.value) || 0)) * (Number(form.elements.pf_percent.value) || 0) / 100;
          $('#grossPreview').innerHTML = html`Monthly gross: <strong>${fmt.money(total)}</strong>${bonus ? html` + bonus ${fmt.money(bonus)}` : ''} · PF at full attendance: ${fmt.money(pf)}`;
        };
        form.addEventListener('input', update); update();
      },
      onSubmit: async (formData, ctx) => {
        await api.put(`/payroll/salary-structures/${item.employee_pk}/`, Object.fromEntries(formData));
        ctx.close(); App.toast('Salary structure saved.'); load();
      },
    });
  }

  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); state.page = 1; load(); }));
  $('#cfgFilter').addEventListener('change', e => { state.configured = e.target.value; state.page = 1; load(); });
  load();
})();
