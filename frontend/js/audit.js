(async function () {
  'use strict';
  const { $, html, icon, fmt, api } = App;
  await App.boot({ role: 'ADMIN', nav: 'audit' });
  $('#searchIcon').innerHTML = icon('search');
  const params = new URLSearchParams(location.search);
  const state = { page: 1, pageSize: 20, search: '', module: params.get('module') || '', action: '', employee: '', from: '', to: '' };

  // Filter options come from what is actually recorded, so new modules and actions appear automatically.
  try {
    const [meta, people] = await Promise.all([api.get('/audit-logs/meta/'), api.get('/employees/')]);
    const modules = [...new Set([...meta.modules, state.module].filter(Boolean))].sort();
    $('#module').innerHTML = html`<option value="">All modules</option>${modules.map(m => html`<option value="${m}"${m === state.module ? App.raw(' selected') : ''}>${m}</option>`)}`;
    $('#action').innerHTML = html`<option value="">All actions</option>${meta.actions.map(a => html`<option value="${a}">${a.replace(/_/g, ' ').toLowerCase()}</option>`)}`;
    $('#employee').innerHTML = html`<option value="">All employees</option>${people.map(p => html`<option value="${p.user_id}">${p.full_name} · ${p.employee_id}</option>`)}`;
  } catch (error) { /* filters fall back to "All" */ }

  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(7, 8);
    try {
      const data = await api.get('/audit-logs/', {
        page: state.page, page_size: state.pageSize, search: state.search, module: state.module, action: state.action,
        employee: state.employee, from: state.from, to: state.to,
      });
      if (!data.results.length && state.page > 1) { state.page -= 1; return load(); }
      const filtered = state.search || state.module || state.action || state.employee || state.from || state.to;
      rows.innerHTML = data.results.length ? html`${data.results.map(log => html`<tr>
        <td class="nowrap">${fmt.dateTime(log.created_at)}</td><td>${log.actor_name || html`<span class="muted">Anonymous</span>`}</td>
        <td>${log.subject_name || html`<span class="subtle">—</span>`}</td>
        <td>${log.module || log.entity_type}</td><td><span class="badge">${log.action}</span></td>
        <td style="max-width:420px">${log.summary}</td><td class="mono nowrap">${log.ip_address || '—'}</td></tr>`)}`
        : App.emptyRow(7, { iconName: 'activity', title: 'No activity found', text: filtered ? 'Try a different search or filter.' : 'Sensitive actions will be recorded here.' });
      $('#count').textContent = `${data.count} entr${data.count === 1 ? 'y' : 'ies'}`;
      App.pager($('#pager'), { page: state.page, count: data.count, pageSize: state.pageSize }, page => { state.page = page; load(); });
    } catch (error) {
      rows.innerHTML = App.errorRow(7, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
      $('#pager').hidden = true;
    }
  }
  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); state.page = 1; load(); }));
  ['module', 'action', 'employee', 'from', 'to'].forEach(id => $(`#${id}`).addEventListener('change', e => { state[id] = e.target.value; state.page = 1; load(); }));
  load();
})();
