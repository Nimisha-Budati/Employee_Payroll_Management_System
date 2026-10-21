(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api } = App;
  const user = await App.boot({ nav: 'calendar' });
  const admin = user.role === 'ADMIN';
  const TYPES = [['leave', 'Leave'], ['wfh', 'Work from home'], ['shift', 'Shifts'], ['holiday', 'Holidays']];
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const now = new Date();
  const state = { year: now.getFullYear(), month: now.getMonth(), scope: 'mine', types: new Set(TYPES.map(t => t[0])), department: '', employee: '', from: '', to: '' };
  let events = [];

  $('#prev').innerHTML = icon('left');
  $('#next').innerHTML = icon('right');
  $('#types').innerHTML = html`<legend class="sr-only">Event types</legend>${TYPES.map(([key, label]) => html`<label class="check tc-type ev-${key}"><input type="checkbox" value="${key}" checked> <span class="tc-swatch"></span>${label}</label>`)}`;
  if (admin) {
    $('#intro').textContent = 'Approved leave, approved work from home, shift assignments and holidays for every active employee.';
    $('#adminFilters').hidden = false;
    try {
      const [meta, people] = await Promise.all([api.get('/employees/meta/'), api.get('/employees/', { status: 'ACTIVE' })]);
      $('#department').innerHTML = html`<option value="">All departments</option>${meta.departments.map(d => html`<option value="${d}">${d}</option>`)}`;
      $('#employee').innerHTML = html`<option value="">All employees</option>${people.map(p => html`<option value="${p.user_id}">${p.full_name} · ${p.employee_id}</option>`)}`;
    } catch (error) { /* filters stay at "All" */ }
  } else {
    $('#intro').textContent = 'Your approved leave, work from home, shift and holidays, and which colleagues in your department are away.';
    $('#scopeTabs').hidden = false;
  }

  const iso = fmt.iso;
  const parse = value => new Date(`${value}T00:00:00`);
  function gridRange() {
    const first = new Date(state.year, state.month, 1);
    const start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7));   // Monday on or before the 1st
    const end = new Date(start); end.setDate(start.getDate() + 41);
    return { start, end };
  }
  const usingRange = () => admin && state.from && state.to;

  async function load() {
    const { start, end } = gridRange();
    const range = usingRange() ? { start: state.from, end: state.to } : { start: iso(start), end: iso(end) };
    $('#title').textContent = usingRange() ? `${fmt.date(state.from)} – ${fmt.date(state.to)}` : `${fmt.months[state.month]} ${state.year}`;
    $('#prev').disabled = $('#next').disabled = $('#today').disabled = Boolean(usingRange());
    $('#clearRange').hidden = !usingRange();
    $('#grid').hidden = Boolean(usingRange());
    $('#grid').innerHTML = html`<div class="tc-loading">${App.raw('<span class="spinner"></span>')} Loading calendar…</div>`;
    $('#agenda').innerHTML = '';
    if (!state.types.size) { events = []; render(); return; }
    try {
      const data = await api.get('/calendar/', {
        start: range.start, end: range.end, types: [...state.types].join(','),
        scope: admin ? undefined : state.scope, department: admin ? state.department : undefined, employee: admin ? state.employee : undefined,
      });
      events = data.events;
      const notes = [];
      if (data.default_shift) notes.push(`Employees without an assignment work the default shift ${data.default_shift}; only assigned shifts are shown.`);
      if (!admin && state.scope === 'team') notes.push(`Showing colleagues in ${data.department || 'your department'} who are on leave or working from home. Leave types and reasons are private.`);
      $('#note').hidden = !notes.length;
      $('#note').innerHTML = html`${icon('info')}<span>${notes.join(' ')}</span>`;
      render();
    } catch (error) {
      $('#grid').innerHTML = App.empty({ iconName: 'alert', title: 'Could not load the calendar', text: error.message, action: html`<button class="btn btn-sm" id="retry" type="button">Try again</button>` });
      $('#retry').addEventListener('click', load);
    }
  }

  const covers = (event, day) => event.start <= day && day <= event.end;
  // Names are shown to administrators and in team view; "My schedule" only contains the user's own events.
  const who = event => (event.employee_name && (admin || state.scope === 'team') ? `${event.employee_name}: ` : '');
  const chip = event => html`<li class="tc-chip ev-${event.type}" title="${who(event)}${event.title}${event.detail ? ` – ${event.detail}` : ''}">${who(event)}${event.title}</li>`;

  function render() {
    if (!usingRange()) {
      const { start } = gridRange();
      const today = iso(new Date());
      const cells = Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d; });
      $('#grid').innerHTML = html`<div class="tc-grid" role="grid" aria-label="${fmt.months[state.month]} ${state.year}">
        ${DAYS.map(d => html`<div class="tc-head" role="columnheader">${d}</div>`)}
        ${cells.map(d => {
          const key = iso(d);
          const dayEvents = events.filter(e => covers(e, key));
          const outside = d.getMonth() !== state.month;
          return html`<div class="tc-cell${outside ? ' outside' : ''}${key === today ? ' today' : ''}${dayEvents.some(e => e.type === 'holiday') ? ' holiday' : ''}" role="gridcell">
            <button class="tc-day" type="button" data-day="${key}" aria-label="${fmt.dateLong(key)}, ${dayEvents.length} event${dayEvents.length === 1 ? '' : 's'}">${d.getDate()}</button>
            <ul class="tc-chips">${dayEvents.slice(0, 3).map(chip)}${dayEvents.length > 3 ? html`<li class="tc-more"><button type="button" data-day="${key}">+${dayEvents.length - 3} more</button></li>` : ''}</ul>
          </div>`;
        })}
      </div>`;
      $$('[data-day]', $('#grid')).forEach(b => b.addEventListener('click', () => showDay(b.dataset.day)));
    }
    renderAgenda();
  }

  function renderAgenda() {
    const monthStart = iso(new Date(state.year, state.month, 1));
    const monthEnd = iso(new Date(state.year, state.month + 1, 0));
    const visible = usingRange() ? events : events.filter(e => e.end >= monthStart && e.start <= monthEnd);
    $('#agendaTitle').textContent = usingRange() ? 'Events in this range' : `Events in ${fmt.months[state.month]}`;
    if (!visible.length) {
      $('#agenda').innerHTML = App.empty({ iconName: 'calendar', title: 'Nothing scheduled', text: state.types.size ? 'No approved leave, work from home, shifts or holidays in this period.' : 'Choose at least one event type.' });
      return;
    }
    $('#agenda').innerHTML = html`<ul class="tc-agenda">${visible.map(e => html`<li class="ev-${e.type}">
      <span class="tc-swatch" aria-hidden="true"></span>
      <div><div class="cell-main">${who(e)}${e.title}</div><div class="cell-sub">${e.start === e.end ? fmt.date(e.start) : `${fmt.date(e.start)} – ${fmt.date(e.end)}`}${e.detail ? ` · ${e.detail}` : ''}${admin && e.department ? ` · ${e.department}` : ''}</div></div>
    </li>`)}</ul>`;
  }

  function showDay(day) {
    const list = events.filter(e => covers(e, day));
    App.modal({
      title: fmt.dateLong(day), cancelLabel: 'Close',
      body: list.length ? html`<ul class="tc-agenda">${list.map(e => html`<li class="ev-${e.type}"><span class="tc-swatch" aria-hidden="true"></span><div><div class="cell-main">${who(e)}${e.title}</div>${e.detail ? html`<div class="cell-sub">${e.detail}</div>` : ''}</div></li>`)}</ul>`
        : App.empty({ iconName: 'calendar', title: 'Nothing on this day' }),
    });
  }

  const move = delta => { const d = new Date(state.year, state.month + delta, 1); state.year = d.getFullYear(); state.month = d.getMonth(); load(); };
  $('#prev').addEventListener('click', () => move(-1));
  $('#next').addEventListener('click', () => move(1));
  $('#today').addEventListener('click', () => { state.year = now.getFullYear(); state.month = now.getMonth(); load(); });
  $$('#types input').forEach(box => box.addEventListener('change', () => { box.checked ? state.types.add(box.value) : state.types.delete(box.value); load(); }));
  $$('[data-scope]').forEach(tab => tab.addEventListener('click', () => {
    state.scope = tab.dataset.scope;
    $$('[data-scope]').forEach(t => t.setAttribute('aria-selected', String(t === tab)));
    load();
  }));
  if (admin) {
    $('#department').addEventListener('change', e => { state.department = e.target.value; load(); });
    $('#employee').addEventListener('change', e => { state.employee = e.target.value; load(); });
    const rangeChanged = () => {
      state.from = $('#from').value; state.to = $('#to').value;
      if (state.from && state.to) {
        const days = (parse(state.to) - parse(state.from)) / 86400000 + 1;
        if (days < 1 || days > 62) { App.toast('Choose a range of 1 to 62 days.', 'error'); return; }
      }
      load();
    };
    $('#from').addEventListener('change', rangeChanged);
    $('#to').addEventListener('change', rangeChanged);
    $('#clearRange').addEventListener('click', () => { $('#from').value = $('#to').value = ''; state.from = state.to = ''; load(); });
  }
  load();
})();
