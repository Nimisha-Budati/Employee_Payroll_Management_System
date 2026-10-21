(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  await App.boot({ role: 'ADMIN', nav: 'payroll', title: 'Payroll review' });
  $('#searchIcon').innerHTML = icon('search');

  const params = new URLSearchParams(location.search);
  const now = new Date();
  const last = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const state = {
    year: Number(params.get('year')) || last.getFullYear(), month: Number(params.get('month')) || last.getMonth() + 1,
    show: 'flagged', search: '', open: new Set(),
  };
  $('#month').innerHTML = html`${fmt.months.map((name, i) => html`<option value="${i + 1}"${i + 1 === state.month ? App.raw(' selected') : ''}>${name}</option>`)}`;
  $('#year').innerHTML = html`${Array.from({ length: 6 }, (_, i) => now.getFullYear() - i).map(y => html`<option value="${y}"${y === state.year ? App.raw(' selected') : ''}>${y}</option>`)}`;
  let data = null;

  const money = value => (value == null ? '—' : fmt.money(value));
  const pct = value => (value == null ? '' : `${Number(value) > 0 ? '+' : ''}${fmt.number(value)}%`);
  const changeCell = (change, percent) => {
    if (change == null) return html`<span class="subtle">—</span>`;
    const n = Number(change);
    return html`<span class="${n > 0 ? 'change-up' : n < 0 ? 'change-down' : ''}">${n > 0 ? '+' : ''}${fmt.money(n)}</span>${percent != null ? html`<div class="cell-sub">${pct(percent)}</div>` : ''}`;
  };
  const flagBadges = (flags, change) => (flags.length ? html`<div class="variance-flags">${flags.map(f => html`<span class="badge badge-${f.severity === 'high' ? 'danger' : f.severity === 'medium' ? 'warning' : 'info'}" title="${f.message}">${f.code.replace('_', ' ').toLowerCase()}</span>`)}</div>`
    : Number(change) ? html`<span class="badge badge-success" title="Change is below the review threshold">Within range</span>` : html`<span class="badge badge-success">No change</span>`);

  async function load() {
    history.replaceState(null, '', `?year=${state.year}&month=${state.month}`);
    $('#rows').innerHTML = App.skeletonRows(7, 6);
    $('#stats').innerHTML = html`${[0, 1, 2, 3].map(() => html`<div class="card stat"><span class="skeleton" style="width:100%;height:56px"></span></div>`)}`;
    try {
      data = await api.get('/payroll/variance/', { year: state.year, month: state.month });
    } catch (error) {
      $('#stats').innerHTML = '';
      $('#reviewBox').innerHTML = '';
      $('#rows').innerHTML = App.errorRow(7, error.message);
      $('[data-retry]', $('#rows')).addEventListener('click', load);
      return;
    }
    renderStats(); renderReview(); renderRows();
  }

  function renderStats() {
    const c = data.counts, t = data.totals;
    $('#prevHead').textContent = `${data.previous_period} net`;
    $('#stats').innerHTML = html`
      <div class="card stat"><span class="stat-icon">${icon('users')}</span><div><div class="stat-label">Payslips</div><div class="stat-value">${c.current}</div><div class="stat-note">${c.drafts} draft · ${c.paid} paid · ${c.previous} last month</div></div></div>
      <div class="card stat"><span class="stat-icon ${c.high ? 'amber' : 'green'}">${icon('alert')}</span><div><div class="stat-label">Flagged</div><div class="stat-value">${c.flagged}</div><div class="stat-note">${c.high} high · ${c.medium} to check (±${fmt.number(data.threshold_percent)}% net)</div></div></div>
      <div class="card stat"><span class="stat-icon green">${icon('wallet')}</span><div><div class="stat-label">Net payable</div><div class="stat-value">${fmt.compactMoney(t.net_salary.current)}</div><div class="stat-note">${pct(t.net_salary.percent) || 'no previous month'} vs ${fmt.compactMoney(t.net_salary.previous)}</div></div></div>
      <div class="card stat"><span class="stat-icon blue">${icon('rupee')}</span><div><div class="stat-label">Gross earnings</div><div class="stat-value">${fmt.compactMoney(t.gross_earnings.current)}</div><div class="stat-note">Overtime ${fmt.compactMoney(t.overtime_pay.current)} · Bonus ${fmt.compactMoney(t.bonus.current)}</div></div></div>`;
  }

  function renderReview() {
    const c = data.counts, review = data.review;
    const box = $('#reviewBox');
    if (!c.current) {
      box.innerHTML = html`<div class="alert alert-info" style="flex:1">${icon('info')}<span>No payslips for ${data.period} yet. Run payroll first, then review the variance here.</span></div>`;
      return;
    }
    if (!c.drafts) {
      box.innerHTML = html`<div class="alert alert-success" style="flex:1">${icon('check')}<span>${data.period} is finalised. This comparison is for reference only.</span></div>`;
      return;
    }
    const current = review && review.is_current;
    box.innerHTML = html`<div>
        <strong>${current ? 'Reviewed' : review ? 'Review out of date' : 'Not reviewed yet'}</strong>
        <div class="muted">${review ? html`Last review by ${review.reviewed_by} on ${fmt.dateTime(review.reviewed_at)}${review.note ? ` · “${review.note}”` : ''}.${current ? '' : ' Drafts changed afterwards, so review again.'}`
          : html`Check the flagged employees below, then mark the month as reviewed. Finalising is only possible after a review.`}</div>
      </div>
      <div class="actions">
        <button class="btn" type="button" id="reviewBtn">${icon('checkCircle')} ${current ? 'Review again' : 'Mark as reviewed'}</button>
        <button class="btn btn-success" type="button" id="finalizeBtn"${current ? '' : App.raw(' disabled')}>${icon('check')} Finalise ${c.drafts} draft${c.drafts === 1 ? '' : 's'}</button>
      </div>`;
    $('#reviewBtn').addEventListener('click', markReviewed);
    $('#finalizeBtn').addEventListener('click', finalize);
  }

  function filteredRows() {
    const q = state.search.toLowerCase();
    return data.rows.filter(r => (state.show === 'all' || r.anomaly)
      && (!q || `${r.employee_name} ${r.employee_code} ${r.department}`.toLowerCase().includes(q)));
  }

  function renderRows() {
    const rows = filteredRows();
    const tbody = $('#rows');
    if (!rows.length) {
      tbody.innerHTML = App.emptyRow(7, state.show === 'flagged' && !state.search && data.rows.length
        ? { iconName: 'checkCircle', title: 'Nothing flagged', text: 'No employee crossed a variance rule. Choose “All employees” to see every comparison.' }
        : { iconName: 'wallet', title: data.rows.length ? 'No employees match your search' : `No payslips for ${data.period}`, text: data.rows.length ? '' : 'Run payroll for this month first.' });
      return;
    }
    tbody.innerHTML = html`${rows.map(r => {
      const key = String(r.employee_user_id);
      const open = state.open.has(key);
      return html`<tr class="${r.severity === 'high' ? 'row-flag-high' : r.severity === 'medium' ? 'row-flag-medium' : ''}">
        <td><div class="cell-main">${r.employee_name}</div><div class="cell-sub mono">${r.employee_code}${r.department ? ` · ${r.department}` : ''}</div></td>
        <td>${r.status ? App.badge(r.status) : r.flags.some(f => f.code === 'LEFT') ? html`<span class="badge">Left</span>` : html`<span class="badge badge-danger">Missing</span>`}</td>
        <td class="right num">${money(r.previous_net)}</td>
        <td class="right num"><strong>${money(r.current_net)}</strong></td>
        <td class="right num">${changeCell(r.net_change, r.net_percent)}</td>
        <td>${flagBadges(r.flags, r.net_change)}</td>
        <td class="right"><button class="btn btn-sm" type="button" data-toggle="${key}" aria-expanded="${open}">${icon(open ? 'down' : 'right', 'icon-sm')} Details</button></td>
      </tr>${open ? html`<tr class="details-row"><td colspan="7">${details(r)}</td></tr>` : ''}`;
    })}`;
    $$('[data-toggle]', tbody).forEach(b => b.addEventListener('click', () => {
      state.open.has(b.dataset.toggle) ? state.open.delete(b.dataset.toggle) : state.open.add(b.dataset.toggle);
      renderRows();
    }));
  }

  function details(r) {
    const changed = r.components.filter(c => c.change != null && Number(c.change) !== 0);
    const quantity = c => (c.kind === 'quantity' ? (v => (v == null ? '—' : fmt.number(v))) : money);
    return html`<div class="grid grid-2" style="gap:16px">
      <div>
        <strong>Why it changed</strong>
        ${r.flags.length ? html`<ul class="variance-reasons">${r.flags.map(f => html`<li>${App.badge(f.severity)} ${f.message}</li>`)}</ul>` : ''}
        ${r.reasons.length ? html`<ul class="variance-reasons">${r.reasons.map(text => html`<li>${text}</li>`)}</ul>` : html`<p class="muted">No differences in the recorded data.</p>`}
        ${r.payslip_id ? html`<p style="margin-top:10px"><a href="admin-payroll.html" class="btn btn-sm">${icon('edit', 'icon-sm')} Open payroll runs to adjust or recalculate</a></p>` : ''}
      </div>
      <div class="table-wrap"><table class="component-table">
        <thead><tr><th>Component</th><th>${data.previous_period}</th><th>${data.period}</th><th>Change</th></tr></thead>
        <tbody>${(changed.length ? r.components : r.components.filter(c => ['gross_earnings', 'total_deductions', 'net_salary'].includes(c.field))).map(c => {
          const show = quantity(c);
          const isChanged = c.change != null && Number(c.change) !== 0;
          return html`<tr class="${isChanged ? 'is-changed' : ''}"><td>${c.label}</td><td>${show(c.previous)}</td><td>${show(c.current)}</td>
            <td>${c.change == null ? '—' : html`${Number(c.change) > 0 ? '+' : ''}${show(c.change)}${c.percent != null && isChanged ? html` <span class="subtle">(${pct(c.percent)})</span>` : ''}`}</td></tr>`;
        })}</tbody>
      </table></div>
    </div>`;
  }

  function markReviewed() {
    const flagged = data.counts.flagged;
    App.modal({
      title: `Review ${data.period}`, submitLabel: 'Record review',
      body: html`<div class="form-grid">
        <p class="span-2 muted">${data.counts.drafts} draft payslip(s), ${flagged} flagged. Recording the review lets you finalise. Changing a draft afterwards needs a new review.</p>
        ${flagged ? field({ label: `I have checked the ${flagged} flagged employee(s)`, name: 'acknowledge', type: 'checkbox', span2: true }) : ''}
        ${field({ label: 'Review note (optional)', name: 'note', type: 'textarea', span2: true, attrs: 'maxlength="300"', placeholder: 'e.g. Increases are the October salary revisions.' })}
      </div>`,
      onSubmit: async (formData, ctx) => {
        if (flagged && formData.get('acknowledge') !== 'on' && !formData.get('note')) throw new Error('Tick the confirmation or add a note about the flagged employees.');
        await api.post('/payroll/variance/review/', { year: state.year, month: state.month, note: formData.get('note') || '', acknowledge_flags: formData.get('acknowledge') === 'on' });
        ctx.close(); App.toast('Review recorded.'); load();
      },
    });
  }

  async function finalize() {
    const ok = await App.confirm({
      title: `Finalise ${data.period}?`,
      message: `All ${data.counts.drafts} draft payslip(s) will be marked paid and become visible to employees. Paid payslips can no longer be edited.`,
      confirmLabel: 'Finalise payroll',
    });
    if (!ok) return;
    try {
      const result = await api.post('/payroll/finalize/', { year: state.year, month: state.month });
      App.toast(`${result.finalized} payslip${result.finalized === 1 ? '' : 's'} finalised.`);
      load();
    } catch (error) { App.error(error); load(); }
  }

  $('#month').addEventListener('change', e => { state.month = Number(e.target.value); state.open.clear(); load(); });
  $('#year').addEventListener('change', e => { state.year = Number(e.target.value); state.open.clear(); load(); });
  $('#show').addEventListener('change', e => { state.show = e.target.value; renderRows(); });
  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); renderRows(); }, 200));
  load();
})();
