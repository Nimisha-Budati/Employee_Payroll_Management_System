(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api } = App;
  await App.boot({ nav: 'notifications' });
  $('#markAll').innerHTML = html`${icon('check')} Mark all as read`;
  const ICONS = { LEAVE: 'calendar', WFH: 'home', DOCUMENT: 'file', ATTENDANCE: 'pin', HOLIDAY: 'calendar', ANNOUNCEMENT: 'flag', CHAT: 'chat', EMPLOYEE: 'user', PAYROLL: 'wallet', GENERAL: 'megaphone', SHIFT: 'clock', OVERTIME: 'timer' };

  async function load() {
    $('#list').innerHTML = html`<div class="notice"><span class="skeleton" style="width:60%"></span></div><div class="notice"><span class="skeleton" style="width:40%"></span></div>`;
    try {
      const { notifications, unread_count: unread } = await api.get('/notifications/');
      $('#markAll').disabled = !unread;
      $('#list').innerHTML = notifications.length ? html`${notifications.map(n => html`<a class="notice${n.is_read ? '' : ' unread'}" href="${n.target_url || '#'}" data-id="${n.id}">
        <span class="notice-icon">${icon(ICONS[n.kind] || 'bell')}</span>
        <div style="min-width:0"><div class="notice-title">${n.title}</div><div class="muted">${n.message}</div>${n.expires_at ? html`<div class="subtle" style="font-size:12px">Expires ${fmt.dateTime(n.expires_at)}</div>` : ''}</div>
        <span class="notice-time">${fmt.relative(n.created_at)}</span></a>`)}`
        : App.empty({ iconName: 'bell', title: 'You are all caught up', text: 'New notifications will show up here.' });
      $$('.notice[data-id]', $('#list')).forEach(a => a.addEventListener('click', event => {
        event.preventDefault();
        const href = a.getAttribute('href');
        const go = () => { if (href && href !== '#') location.href = href; };
        if (a.classList.contains('unread')) api.post(`/notifications/${a.dataset.id}/read/`).catch(() => {}).finally(go); else go();
      }));
      App.refreshBell();
    } catch (error) {
      $('#list').innerHTML = App.empty({ iconName: 'alert', title: 'Could not load notifications', text: error.message, action: html`<button class="btn btn-sm" id="retry">Try again</button>` });
      $('#retry').addEventListener('click', load);
    }
  }
  /* ---- Administrators: send a notification to employees, with an optional expiry ---- */
  if (App.user && App.user.role === 'ADMIN') {
    const send = $('#sendBtn');
    send.hidden = false;
    send.innerHTML = html`${icon('megaphone')} Send notification`;
    $('#sentCard').hidden = false;
    const loadSent = async () => {
      const rows = $('#sentRows');
      try {
        const list = await api.get('/notifications/broadcasts/');
        rows.innerHTML = list.length ? html`${list.map(b => html`<tr>
          <td style="max-width:320px"><div class="cell-main">${b.title}</div><div class="cell-sub truncate" title="${b.message}">${b.message}</div></td>
          <td>${b.target_label}</td><td class="right num">${b.recipient_count}</td><td class="right num">${b.read_count}</td>
          <td class="nowrap">${b.expires_at ? html`${fmt.dateTime(b.expires_at)} ${App.badge(b.is_expired ? 'EXPIRED' : 'LIVE')}` : html`<span class="muted">Never</span>`}</td>
          <td class="nowrap">${fmt.dateTime(b.created_at)}</td>
          <td><div class="actions"><button class="btn btn-sm btn-danger" type="button" data-withdraw="${b.id}">Withdraw</button></div></td></tr>`)}`
          : App.emptyRow(7, { iconName: 'megaphone', title: 'Nothing sent yet', text: 'Use "Send notification" to reach all employees, a department or chosen people.' });
        $$('[data-withdraw]', rows).forEach(button => button.addEventListener('click', async () => {
          const ok = await App.confirm({ title: 'Withdraw this notification?', message: 'It will be removed from every recipient\u2019s inbox.', confirmLabel: 'Withdraw', danger: true });
          if (!ok) return;
          try { await api.delete(`/notifications/broadcasts/${button.dataset.withdraw}/`); App.toast('Notification withdrawn.'); loadSent(); } catch (error) { App.error(error); }
        }));
      } catch (error) { rows.innerHTML = App.errorRow(7, error.message, false); }
    };
    send.addEventListener('click', async () => {
      let meta = { departments: [] }, people = [];
      try { [meta, people] = await Promise.all([api.get('/employees/meta/'), api.get('/employees/', { status: 'ACTIVE' })]); } catch (error) { return App.error(error); }
      App.modal({
        title: 'Send notification', subtitle: 'Recipients see it in their notification inbox until it expires.', wide: true, submitLabel: 'Send',
        body: html`<div class="form-grid">
          ${App.field({ label: 'Title', name: 'title', required: true, span2: true, attrs: 'maxlength="160"' })}
          ${App.field({ label: 'Message', name: 'message', type: 'textarea', required: true, span2: true, attrs: 'maxlength="2000"' })}
          ${App.field({ label: 'Send to', name: 'target_type', type: 'select', options: [['ALL', 'All active employees'], ['DEPARTMENT', 'A department'], ['EMPLOYEES', 'Selected employees']] })}
          ${App.field({ label: 'Expires (optional)', name: 'expires_at', type: 'datetime-local', hint: 'Leave empty to keep it until the employee clears it.' })}
          <div class="span-2" id="deptField" hidden>${App.field({ label: 'Department', name: 'department', type: 'select', options: meta.departments })}</div>
          <div class="field span-2" id="peopleField" hidden><label>Employees</label><div class="checklist">${people.map(p => html`<label class="check"><input type="checkbox" name="employee_ids" value="${p.user_id}"> ${p.full_name} <span class="muted">· ${p.employee_id} · ${p.department}</span></label>`)}</div></div>
        </div>`,
        onOpen: ({ form }) => {
          const sync = () => { $('#deptField').hidden = form.elements.target_type.value !== 'DEPARTMENT'; $('#peopleField').hidden = form.elements.target_type.value !== 'EMPLOYEES'; };
          form.elements.target_type.addEventListener('change', sync); sync();
        },
        onSubmit: async (formData, ctx) => {
          const payload = { title: formData.get('title'), message: formData.get('message'), target_type: formData.get('target_type') };
          if (payload.target_type === 'DEPARTMENT') payload.department = formData.get('department');
          if (payload.target_type === 'EMPLOYEES') payload.employee_ids = formData.getAll('employee_ids').map(Number);
          if (formData.get('expires_at')) payload.expires_at = new Date(formData.get('expires_at')).toISOString();
          const result = await api.post('/notifications/broadcasts/', payload);
          ctx.close(); App.toast(`Sent to ${result.recipient_count} employee${result.recipient_count === 1 ? '' : 's'}.`); loadSent();
        },
      });
    });
    loadSent();
  }

  $('#markAll').addEventListener('click', async () => {
    try { await api.post('/notifications/read-all/'); App.toast('All notifications marked as read.'); load(); } catch (error) { App.error(error); }
  });
  load();
})();
