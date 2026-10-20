(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  const role = document.body.dataset.role;
  const admin = role === 'ADMIN';
  await App.boot({ role, nav: 'holidays' });
  $('#prev').innerHTML = icon('left'); $('#next').innerHTML = icon('right');
  if (admin) $('#addBtn').innerHTML = html`${icon('plus')} Add holiday`;
  const today = new Date();
  let year = today.getFullYear(), month = today.getMonth();
  let holidays = [];

  async function load() {
    try { holidays = await api.get('/holidays/'); render(); } catch (error) {
      $('#grid').innerHTML = html`<div style="grid-column:1/-1">${App.empty({ iconName: 'alert', title: 'Could not load holidays', text: error.message, action: html`<button class="btn btn-sm" id="retry">Try again</button>` })}</div>`;
      $('#retry').addEventListener('click', load);
    }
  }

  function render() {
    $('#monthTitle').textContent = `${fmt.months[month]} ${year}`;
    const first = new Date(year, month, 1).getDay();
    const days = new Date(year, month + 1, 0).getDate();
    const byDate = {};
    holidays.forEach(h => { (byDate[h.date] = byDate[h.date] || []).push(h); });
    const cells = [];
    for (let i = 0; i < first; i++) cells.push(html`<div class="cal-day blank"></div>`);
    for (let d = 1; d <= days; d++) {
      const iso = fmt.iso(new Date(year, month, d));
      const items = byDate[iso] || [];
      const isToday = iso === App.todayISO();
      const events = items.map(h => html`<span class="cal-event${h.holiday_type === 'TENTATIVE' ? ' tentative' : ''}" title="${h.name}">${h.name}</span>`);
      cells.push(admin
        ? html`<button class="cal-day${isToday ? ' today' : ''}" type="button" data-date="${iso}" aria-label="${fmt.dateLong(iso)}${items.length ? ': ' + items.map(h => h.name).join(', ') : ''}"><span class="cal-num">${d}</span>${events}</button>`
        : html`<div class="cal-day${isToday ? ' today' : ''}"><span class="cal-num">${d}</span>${events}</div>`);
    }
    $('#grid').innerHTML = html`${cells}`;
    $$('[data-date]', $('#grid')).forEach(b => b.addEventListener('click', () => {
      const existing = byDate[b.dataset.date];
      if (existing && existing.length) openForm(existing[0]); else openForm(null, b.dataset.date);
    }));

    const upcoming = holidays.filter(h => { const d = new Date(`${h.date}T00:00:00`); return d.getFullYear() === year && d.getMonth() === month; });
    $('#listTitle').textContent = `Holidays in ${fmt.months[month]}`;
    $('#list').innerHTML = upcoming.length ? html`${upcoming.map(h => html`<li class="row" style="justify-content:space-between;flex-wrap:nowrap"><div><div style="font-weight:600">${h.name}</div><div class="muted">${fmt.dateLong(h.date)}${h.description ? ` · ${h.description}` : ''}</div></div><div class="row">${App.badge(h.holiday_type)}${admin ? html`<button class="btn btn-sm" type="button" data-edit="${h.id}">${icon('edit', 'icon-sm')} Edit</button>` : ''}</div></li>`)}`
      : html`<li>${App.empty({ iconName: 'calendar', title: 'No holidays this month', text: admin ? 'Click a day on the calendar to add one.' : '' })}</li>`;
    $$('[data-edit]', $('#list')).forEach(b => b.addEventListener('click', () => openForm(holidays.find(h => String(h.id) === b.dataset.edit))));
  }

  function openForm(holiday, date) {
    const editing = Boolean(holiday);
    const h = holiday || {};
    App.modal({
      title: editing ? 'Edit holiday' : 'Add holiday', submitLabel: editing ? 'Save changes' : 'Add holiday',
      body: html`<div class="form-grid">
        ${field({ label: 'Name', name: 'name', value: h.name, required: true, span2: true, attrs: 'maxlength="100"' })}
        ${field({ label: 'Date', name: 'date', type: 'date', value: h.date || date || App.todayISO(), required: true })}
        ${field({ label: 'Type', name: 'holiday_type', type: 'select', value: h.holiday_type || 'FIXED', options: [['FIXED', 'Fixed'], ['TENTATIVE', 'Tentative']] })}
        ${field({ label: 'Description', name: 'description', type: 'textarea', value: h.description, span2: true })}
        ${editing ? html`<div class="span-2"><button class="btn btn-sm btn-danger" type="button" id="del">${icon('trash', 'icon-sm')} Delete holiday</button></div>` : ''}
      </div>`,
      onOpen: ({ close }) => {
        const del = $('#del');
        if (del) del.addEventListener('click', async () => {
          const ok = await App.confirm({ title: 'Delete holiday?', message: `${h.name} will be removed and employees will be notified.`, confirmLabel: 'Delete', danger: true });
          if (!ok) return;
          try { await api.delete(`/holidays/${h.id}/`); close(); App.toast('Holiday deleted.'); load(); } catch (error) { App.error(error); }
        });
      },
      onSubmit: async (formData, ctx) => {
        const payload = Object.fromEntries(formData);
        if (editing) await api.put(`/holidays/${h.id}/`, payload); else await api.post('/holidays/', payload);
        ctx.close(); App.toast(editing ? 'Holiday updated.' : 'Holiday added.'); load();
      },
    });
  }

  const step = delta => { month += delta; if (month < 0) { month = 11; year -= 1; } if (month > 11) { month = 0; year += 1; } render(); };
  $('#prev').addEventListener('click', () => step(-1));
  $('#next').addEventListener('click', () => step(1));
  $('#todayBtn').addEventListener('click', () => { year = today.getFullYear(); month = today.getMonth(); render(); });
  if (admin) $('#addBtn').addEventListener('click', () => openForm(null));
  load();
})();
