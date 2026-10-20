(async function () {
  'use strict';
  const { $, html, icon, fmt, api } = App;
  await App.boot({ role: 'ADMIN', nav: 'audit' });
  $('#searchIcon').innerHTML = icon('search');
  const state = { page: 1, pageSize: 20, search: '', entity: '', from: '', to: '' };
  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(6, 8);
    try {
      const data = await api.get('/audit-logs/', { page: state.page, page_size: state.pageSize, search: state.search, module: state.entity, from: state.from, to: state.to });
      if (!data.results.length && state.page > 1) { state.page -= 1; return load(); }
      rows.innerHTML = data.results.length ? html`${data.results.map(log => html`<tr>
        <td class="nowrap">${fmt.dateTime(log.created_at)}</td><td>${log.actor_name || html`<span class="muted">Anonymous</span>`}</td>
        <td>${log.module || log.entity_type}</td><td><span class="badge">${log.action}</span></td>
        <td style="max-width:420px">${log.summary}</td><td class="mono nowrap">${log.ip_address || '—'}</td></tr>`)}` : App.emptyRow(6, { iconName: 'activity', title: 'No activity found', text: state.search || state.entity ? 'Try a different search or filter.' : 'Sensitive actions will be recorded here.' });
      App.pager($('#pager'), { page: state.page, count: data.count, pageSize: state.pageSize }, page => { state.page = page; load(); });
    } catch (error) {
      rows.innerHTML = App.errorRow(6, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
      $('#pager').hidden = true;
    }
  }
  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); state.page = 1; load(); }));
  $('#entity').addEventListener('change', e => { state.entity = e.target.value; state.page = 1; load(); });
  $('#from').addEventListener('change', e => { state.from = e.target.value; state.page = 1; load(); });
  $('#to').addEventListener('change', e => { state.to = e.target.value; state.page = 1; load(); });
  load();
})();
