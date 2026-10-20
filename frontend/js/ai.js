/* AI assistant: chatbot, leave policy, salary breakdown, attendance insights (+ knowledge base for admins). */
(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field, esc } = App;
  const user = await App.boot({ nav: 'ai' });
  const admin = user.role === 'ADMIN';

  const FEATURES = {
    CHAT: { label: 'Chatbot', iconName: 'chat', intro: 'Ask how PayrollPro works, or about your own payslip, leave, work from home, overtime and attendance.',
      chips: ['Breakdown my payslip', 'What is my WFH request status?', 'How many leave days do I have left?', 'How do I apply for work from home?'] },
    LEAVE: { label: 'Leave policy', iconName: 'calendar', intro: 'Understand leave types, balances and the rules that apply to you.',
      chips: ['How many leave days do I have left?', 'Show my leave requests', 'What happens if I take more leave than my balance?', 'Is sick leave paid?'] },
    SALARY: { label: 'Salary breakdown', iconName: 'rupee', intro: 'Get your salary components, deductions and net pay explained.',
      chips: ['Breakdown my payslip', 'Explain my net salary', 'Why was I paid less this month?', 'Show my latest payslip'] },
    ATTENDANCE: { label: 'Attendance insights', iconName: 'trending', intro: 'Patterns, punctuality and working hours from attendance records.' },
  };
  const params = new URLSearchParams(location.search);
  let tab = FEATURES[params.get('tab')] || (admin && params.get('tab') === 'KNOWLEDGE') ? params.get('tab') : 'CHAT';
  let status = { enabled: false };
  let employees = null;

  /* ---- safe, minimal Markdown (escape first, then add a few tags) ---- */
  function inline(text) {
    return esc(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[\s(])\*(?!\s)(.+?)\*(?=[\s).,!?]|$)/g, '$1<em>$2</em>')
      .replace(/(^|[\s(])_(?!\s)(.+?)_(?=[\s).,!?]|$)/g, '$1<em>$2</em>');
  }
  function markdown(text) {
    const out = [];
    let list = null;
    const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
    String(text || '').split(/\r?\n/).forEach(raw => {
      const line = raw.trimEnd();
      const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
      const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
      const heading = line.match(/^\s*#{1,6}\s+(.*)$/) || line.match(/^\s*\*\*([^*]+)\*\*:?\s*$/);
      if (bullet || numbered) {
        const kind = bullet ? 'ul' : 'ol';
        if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
        out.push(`<li>${inline((bullet || numbered)[1])}</li>`);
      } else if (heading) {
        closeList(); out.push(`<h4>${inline(heading[1])}</h4>`);
      } else if (!line.trim()) {
        closeList();
      } else {
        closeList(); out.push(`<p>${inline(line)}</p>`);
      }
    });
    closeList();
    return App.raw(out.join(''));
  }

  const MODES = {
    AI: ['sparkle', 'Gemini, from your PayrollPro records'],
    DATA: ['file', 'Shown directly from PayrollPro (AI unavailable)'],
    REFUSAL: ['lock', 'PayrollPro privacy rule'],
  };
  function bubble(message) {
    const own = message.role === 'user';
    if (own) return html`<div class="bubble-row own"><div class="bubble">${message.content}<time datetime="${message.created_at}">${fmt.dateTime(message.created_at)}</time></div></div>`;
    const [iconName, label] = MODES[message.mode] || MODES.AI;
    const sources = (message.sources || []).filter(Boolean);
    return html`<div class="bubble-row"><div class="bubble ai-answer${message.mode && message.mode !== 'AI' ? ` ai-${message.mode.toLowerCase()}` : ''}">${markdown(message.content)}
      ${sources.length ? html`<div class="ai-sources" aria-label="Records used">${icon('layers', 'icon-sm')} Based on: ${sources.join(' · ')}</div>` : ''}
      <time datetime="${message.created_at}" title="${label}">${icon(iconName, 'icon-sm')} ${fmt.dateTime(message.created_at)}</time></div></div>`;
  }

  async function loadEmployees() {
    if (employees || !admin) return employees || [];
    try { employees = await api.get('/employees/', { status: 'ACTIVE' }); } catch (error) { employees = []; }
    return employees;
  }

  function renderTabs() {
    const items = Object.entries(FEATURES).map(([key, f]) => [key, f.label, f.iconName]);
    if (admin) items.push(['KNOWLEDGE', 'Knowledge base', 'file']);
    $('#tabs').innerHTML = html`${items.map(([key, label, iconName]) => html`<button class="tab" role="tab" type="button" data-tab="${key}" aria-selected="${String(key === tab)}">${icon(iconName, 'icon-sm')} ${label}</button>`)}`;
    $$('[data-tab]', $('#tabs')).forEach(b => b.addEventListener('click', () => { tab = b.dataset.tab; history.replaceState(null, '', `?tab=${tab}`); renderTabs(); render(); }));
  }

  function render(openId = null) {
    closeMenu();
    if (tab === 'ATTENDANCE') return renderInsights(openId);
    if (tab === 'KNOWLEDGE') return renderKnowledge();
    return renderChat(tab, openId);
  }
  function switchTo(feature, openId) {
    tab = feature;
    history.replaceState(null, '', `?tab=${tab}`);
    renderTabs();
    render(openId);
  }

  /* ------------------------------------------------------------------ *
   * Chatbot / leave policy / salary breakdown
   * ------------------------------------------------------------------ */
  async function renderChat(feature, openId = null) {
    $('#panel').innerHTML = html`<div class="chat ai-chat" id="chat">
      <aside class="chat-side">
        <div class="stack-sm ai-side-head">
          <button class="btn btn-primary btn-block" id="newConv" type="button">${icon('plus')} New conversation</button>
          <div id="newOptions" class="stack-sm"></div>
          ${searchBox()}
        </div>
        <div class="chat-contacts" id="convs" role="list" aria-label="Conversations"></div>
      </aside>
      <section class="chat-pane" id="pane"></section>
    </div>`;
    if (feature === 'SALARY') await renderSalaryOptions();
    $('#newConv').addEventListener('click', () => openConversation(null, feature));
    wireSearch($('#chat'), () => listConversations(feature), feature);
    const conversations = await listConversations(feature);
    const target = openId || (conversations[0] && conversations[0].id);
    if (target) openConversation(Number(target), feature); else emptyPane(feature);
  }

  async function renderSalaryOptions() {
    const box = $('#newOptions');
    if (admin) {
      const people = await loadEmployees();
      box.innerHTML = html`<label class="sr-only" for="subject">Employee</label><select class="select" id="subject"><option value="">Choose an employee…</option>${people.map(e => html`<option value="${e.user_id}" data-code="${e.employee_id}">${e.full_name} · ${e.employee_id}</option>`)}</select>
        <select class="select" id="payslip" aria-label="Payslip"><option value="">Latest payslips</option></select>`;
      $('#subject').addEventListener('change', async event => {
        const option = event.target.selectedOptions[0];
        $('#payslip').innerHTML = html`<option value="">Latest payslips</option>`;
        if (!option || !option.value) return;
        try {
          const { results } = await api.get('/payroll/payslips/', { search: option.dataset.code });
          $('#payslip').innerHTML = html`<option value="">Latest payslips</option>${results.filter(s => String(s.employee_user_id) === option.value).map(s => html`<option value="${s.id}">${s.period_label} (${s.status === 'PAID' ? 'paid' : 'draft'})</option>`)}`;
        } catch (error) { /* keep default */ }
      });
    } else {
      try {
        const { results } = await api.get('/payroll/payslips/');
        box.innerHTML = html`<label class="muted" for="payslip" style="font-size:12.5px">Focus on a payslip</label><select class="select" id="payslip"><option value="">Latest payslips</option>${results.map(s => html`<option value="${s.id}">${s.period_label}</option>`)}</select>`;
      } catch (error) { box.innerHTML = ''; }
    }
  }

  /* ------------------------------------------------------------------ *
   * Conversation history: three-dot menu (rename, pin/unpin, delete), sections and search.
   * Everything is stored in PostgreSQL through the API; nothing is kept only in the browser.
   * ------------------------------------------------------------------ */
  let activeConversationId = null;
  const lists = new WeakMap();   // container element -> { items, refresh, open }
  const featureLabel = key => (FEATURES[key] ? FEATURES[key].label : key);

  function convRow(c, { showFeature = false } = {}) {
    const meta = [showFeature ? featureLabel(c.feature) : '', c.subject_name, c.payslip_label ? `Payslip ${c.payslip_label}` : '', fmt.relative(c.updated_at)].filter(Boolean).join(' · ');
    return html`<div class="contact ai-conv${c.pinned ? ' pinned' : ''}" role="listitem" data-conv="${c.id}"${String(c.id) === String(activeConversationId) ? App.raw(' aria-current="true"') : ''}>
      <button class="contact-copy ai-conv-open" type="button" data-open="${c.id}" title="${c.title}">
        <span class="contact-name">${c.pinned ? html`${icon('pinTack', 'icon-sm ai-pin-mark')}<span class="sr-only">Pinned: </span>` : ''}<span class="ai-title-text">${c.title}</span></span>
        <span class="contact-preview">${meta}</span></button>
      <button class="icon-btn ai-more" type="button" data-menu="${c.id}" aria-haspopup="menu" aria-expanded="false" aria-label="Options for ${c.title}" title="More options">${icon('moreVertical', 'icon-sm')}</button>
    </div>`;
  }

  function renderSections(container, items, { emptyText = 'No conversations yet.', showFeature = false } = {}) {
    const pinned = items.filter(c => c.pinned), recent = items.filter(c => !c.pinned);
    container.innerHTML = items.length ? html`
      ${pinned.length ? html`<div class="ai-conv-group" role="presentation">${icon('pinTack', 'icon-sm')} Pinned</div>${pinned.map(c => convRow(c, { showFeature }))}` : ''}
      ${recent.length ? html`<div class="ai-conv-group" role="presentation">${icon('clock', 'icon-sm')} Recent chats</div>${recent.map(c => convRow(c, { showFeature }))}` : ''}`
      : html`<div class="ai-list-empty muted">${emptyText}</div>`;
  }

  function wireList(container, items, { open, refresh }) {
    lists.set(container, { items, open, refresh });
    $$('[data-open]', container).forEach(b => b.addEventListener('click', () => open(Number(b.dataset.open))));
    $$('[data-menu]', container).forEach(b => b.addEventListener('click', event => { event.stopPropagation(); toggleMenu(b, container); }));
  }

  function markActive(container) {
    $$('.ai-conv', container).forEach(row => (row.dataset.conv === String(activeConversationId) ? row.setAttribute('aria-current', 'true') : row.removeAttribute('aria-current')));
  }

  /* ---- three-dot menu (one floating menu, closes on outside click, Escape, scroll or choosing an item) ---- */
  let menu = null;
  function closeMenu(restoreFocus = false) {
    if (!menu) return;
    const { el, button } = menu;
    el.remove();
    button.setAttribute('aria-expanded', 'false');
    button.closest('.ai-conv') && button.closest('.ai-conv').classList.remove('menu-open');
    document.removeEventListener('pointerdown', onOutside, true);
    window.removeEventListener('resize', onViewportChange);
    document.removeEventListener('scroll', onViewportChange, true);
    menu = null;
    if (restoreFocus && document.body.contains(button)) button.focus();
  }
  function onOutside(event) { if (menu && !menu.el.contains(event.target) && event.target !== menu.button && !menu.button.contains(event.target)) closeMenu(); }
  function positionMenu() {
    if (!menu) return;
    const { el, button } = menu;
    const rect = button.getBoundingClientRect();
    if (!document.body.contains(button) || rect.bottom < 0 || rect.top > window.innerHeight) { closeMenu(); return; }   // button scrolled away
    const width = el.offsetWidth, height = el.offsetHeight;
    const left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.right - width));
    const below = rect.bottom + 4 + height <= window.innerHeight - 8;
    el.style.left = `${left}px`;
    el.style.top = `${below ? rect.bottom + 4 : Math.max(8, rect.top - height - 4)}px`;
  }
  function onViewportChange() { positionMenu(); }   // keep the menu attached to its button while the page scrolls

  function toggleMenu(button, container) {
    if (menu && menu.button === button) { closeMenu(true); return; }
    closeMenu();
    const state = lists.get(container);
    const c = state.items.find(item => String(item.id) === button.dataset.menu);
    if (!c) return;
    const el = document.createElement('div');
    el.className = 'ai-menu';
    el.setAttribute('role', 'menu');
    el.setAttribute('aria-label', `Options for ${c.title}`);
    el.innerHTML = html`
      <button type="button" role="menuitem" data-act="rename">${icon('edit', 'icon-sm')}<span>Rename</span></button>
      <button type="button" role="menuitem" data-act="${c.pinned ? 'unpin' : 'pin'}">${icon('pinTack', 'icon-sm')}<span>${c.pinned ? 'Unpin' : 'Pin'}</span></button>
      <div class="ai-menu-sep" role="separator"></div>
      <button type="button" role="menuitem" data-act="delete" class="danger">${icon('trash', 'icon-sm')}<span>Delete</span></button>`.toString();
    document.body.append(el);
    button.setAttribute('aria-expanded', 'true');
    button.closest('.ai-conv').classList.add('menu-open');
    menu = { el, button };
    positionMenu();
    const items = $$('[role="menuitem"]', el);
    items[0].focus({ preventScroll: true });
    el.addEventListener('keydown', event => {
      const index = items.indexOf(document.activeElement);
      if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); }
      else if (event.key === 'ArrowDown') { event.preventDefault(); items[(index + 1) % items.length].focus({ preventScroll: true }); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); items[(index - 1 + items.length) % items.length].focus({ preventScroll: true }); }
      else if (event.key === 'Tab') closeMenu();
    });
    items.forEach(item => item.addEventListener('click', () => {
      const action = item.dataset.act;
      closeMenu();
      if (action === 'rename') startRename(container, c);
      else if (action === 'pin' || action === 'unpin') setPinned(container, c, action === 'pin');
      else if (action === 'delete') deleteConversation(container, c);
    }));
    setTimeout(() => {
      document.addEventListener('pointerdown', onOutside, true);
      window.addEventListener('resize', onViewportChange);
      document.addEventListener('scroll', onViewportChange, true);
    });
  }

  /* ---- inline rename: Enter or Save saves, Escape or Cancel cancels ---- */
  function startRename(container, c) {
    const row = $(`.ai-conv[data-conv="${c.id}"]`, container);
    if (!row) return;
    const opener = $('.ai-conv-open', row);
    const original = opener.outerHTML;
    row.classList.add('renaming');
    $('.ai-more', row).hidden = true;
    opener.outerHTML = html`<form class="ai-rename" novalidate>
      <input class="input" name="title" value="${c.title}" maxlength="120" aria-label="Conversation name" autocomplete="off">
      <button class="icon-btn" type="submit" aria-label="Save name" title="Save (Enter)">${icon('check', 'icon-sm')}</button>
      <button class="icon-btn" type="button" data-cancel aria-label="Cancel renaming" title="Cancel (Esc)">${icon('x', 'icon-sm')}</button>
      <span class="ai-rename-error" role="alert" hidden></span></form>`.toString();
    const form = $('.ai-rename', row), input = $('input', form), error = $('.ai-rename-error', form);
    input.focus(); input.select();
    const cancel = () => {
      form.outerHTML = original;
      row.classList.remove('renaming');
      $('.ai-more', row).hidden = false;
      const state = lists.get(container);
      wireList(container, state.items, state);
      $('.ai-more', row).focus();
    };
    const fail = message => { error.textContent = message; error.hidden = false; input.setAttribute('aria-invalid', 'true'); input.focus(); };
    $('[data-cancel]', form).addEventListener('click', cancel);
    input.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); cancel(); } });
    input.addEventListener('input', () => { error.hidden = true; input.removeAttribute('aria-invalid'); });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const title = input.value.replace(/\s+/g, ' ').trim();
      if (!title) return fail('The name cannot be empty.');
      if (title.length > 120) return fail('Use 120 characters or fewer.');
      if (title === c.title) return cancel();
      $$('input, button', form).forEach(control => { control.disabled = true; });
      form.classList.add('busy');
      try {
        const updated = await api.patch(`/ai/conversations/${c.id}/`, { title });
        Object.assign(c, updated);
        App.toast('Conversation renamed.');
        lists.get(container).refresh();
      } catch (err) {
        $$('input, button', form).forEach(control => { control.disabled = false; });
        form.classList.remove('busy');
        fail(err.fields && err.fields.title ? err.fields.title : err.message);
      }
    });
  }

  async function setPinned(container, c, pinned) {
    const row = $(`.ai-conv[data-conv="${c.id}"]`, container);
    if (row) row.classList.add('busy');
    try {
      await api.patch(`/ai/conversations/${c.id}/`, { pinned });
      App.toast(pinned ? 'Pinned to the top.' : 'Moved back to Recent chats.');
    } catch (error) {
      App.error(error);   // e.g. already pinned in another tab: the list below is refreshed from the server
    } finally {
      lists.get(container).refresh();
    }
  }

  async function deleteConversation(container, c) {
    const ok = await App.confirm({ title: 'Delete conversation?', message: `“${c.title}” and its messages will be removed permanently.`, confirmLabel: 'Delete', danger: true });
    if (!ok) return;
    try {
      await api.delete(`/ai/conversations/${c.id}/`);
      App.toast('Conversation deleted.');
      const wasOpen = String(activeConversationId) === String(c.id);
      if (wasOpen) activeConversationId = null;
      await lists.get(container).refresh();
      if (wasOpen && container.id === 'convs') emptyPane(tab);
    } catch (error) { App.error(error); }
  }

  async function listConversations(feature) {
    const container = $('#convs');
    if (!container) return [];
    let conversations = [];
    try { conversations = await api.get('/ai/conversations/', { feature }); }
    catch (error) { container.innerHTML = html`<div class="ai-list-empty muted">${error.message}</div>`; return []; }
    if (searchActive(container)) return conversations;   // a search is showing; don't overwrite it
    renderSections(container, conversations);
    wireList(container, conversations, { open: id => openConversation(id, feature), refresh: () => listConversations(feature) });
    return conversations;
  }

  /* ---- search (titles, your questions and the assistant's answers) ---- */
  function searchBox() {
    return html`<div class="input-group ai-search" role="search">
      <span aria-hidden="true">${icon('search', 'icon-sm')}</span>
      <input class="input" type="search" data-search placeholder="Search chats and messages" aria-label="Search your conversations" maxlength="100" autocomplete="off">
      <span class="spinner ai-search-spin" hidden aria-hidden="true"></span>
      <button class="icon-btn" type="button" data-clear hidden aria-label="Clear search" title="Clear search">${icon('x', 'icon-sm')}</button></div>`;
  }
  function searchActive(container) {
    const box = container.closest('.chat-side, .card');
    const input = box && $('[data-search]', box);
    return Boolean(input && input.value.trim());
  }
  function highlight(text, query) {
    const safe = esc(text);
    const words = query.trim().split(/\s+/).filter(word => word.length > 1).map(word => esc(word).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    if (!words.length) return App.raw(safe);
    return App.raw(safe.replace(new RegExp(`(${words.join('|')})`, 'gi'), '<mark>$1</mark>'));
  }
  function wireSearch(scope, restore, currentFeature) {
    const input = $('[data-search]', scope), clear = $('[data-clear]', scope), spin = $('.ai-search-spin', scope);
    const container = $('#convs', scope) || $('#iHistory', scope);
    let sequence = 0;
    const run = App.debounce(async () => {
      const query = input.value.replace(/\s+/g, ' ').trim();
      const ticket = ++sequence;
      clear.hidden = !input.value;
      if (!query) { spin.hidden = true; restore(); return; }
      if (query.length < 2) { spin.hidden = true; container.innerHTML = html`<div class="ai-list-empty muted">Type at least 2 characters.</div>`; return; }
      spin.hidden = false;
      try {
        const results = await api.get('/ai/conversations/', { search: query });
        if (ticket !== sequence) return;   // a newer search has started
        container.innerHTML = results.length ? html`<div class="ai-conv-group" role="presentation">${icon('search', 'icon-sm')} ${results.length} result${results.length === 1 ? '' : 's'}</div>
          ${results.map(c => html`<button class="contact ai-result" type="button" role="listitem" data-result="${c.id}" data-feature="${c.feature}">
            <span class="contact-name">${c.pinned ? icon('pinTack', 'icon-sm ai-pin-mark') : ''}<span class="ai-title-text">${highlight(c.title, query)}</span></span>
            <span class="contact-preview">${c.feature !== currentFeature ? html`<span class="badge">${featureLabel(c.feature)}</span> ` : ''}${fmt.relative(c.updated_at)}${c.match.message_count ? ` · ${c.match.message_count} matching message${c.match.message_count === 1 ? '' : 's'}` : ''}</span>
            ${c.match.snippet ? html`<span class="ai-result-snippet"><strong>${c.match.role === 'user' ? 'You' : 'Assistant'}:</strong> ${highlight(c.match.snippet, query)}</span>` : ''}
          </button>`)}`
          : html`<div class="ai-list-empty">${icon('search', 'icon-lg')}<strong>No conversations found</strong><span class="muted">Nothing in your chat titles or messages matches “${query}”.</span></div>`;
        $$('[data-result]', container).forEach(b => b.addEventListener('click', () => {
          const id = Number(b.dataset.result), feature = b.dataset.feature;
          if (feature === currentFeature) {
            activeConversationId = id;
            $$('[data-result]', container).forEach(other => other.removeAttribute('aria-current'));
            b.setAttribute('aria-current', 'true');
            const state = lists.get(container);
            if (state) state.open(id); else (currentFeature === 'ATTENDANCE' ? openInsight(id) : openConversation(id, feature));
          } else {
            switchTo(feature, id);
          }
        }));
      } catch (error) {
        if (ticket === sequence) container.innerHTML = html`<div class="ai-list-empty muted">${error.message}</div>`;
      } finally {
        if (ticket === sequence) spin.hidden = true;
      }
    }, 250);
    input.addEventListener('input', run);
    input.addEventListener('keydown', event => { if (event.key === 'Escape' && input.value) { event.preventDefault(); input.value = ''; run(); } });
    clear.addEventListener('click', () => { input.value = ''; run(); input.focus(); });
  }

  function emptyPane(feature) {
    const f = FEATURES[feature];
    $('#pane').innerHTML = html`<div class="chat-messages" id="messages"><div class="ai-welcome">${App.empty({ iconName: 'sparkle', title: f.label, text: f.intro })}
      <div class="ai-chips">${f.chips.map(text => html`<button class="btn btn-sm" type="button" data-chip>${text}</button>`)}</div></div></div>${composer()}`;
    wireComposer(null, feature);
  }

  function composer() {
    return html`<form class="chat-form" id="askForm"><textarea class="input ai-input" id="question" rows="1" maxlength="2000" placeholder="${status.enabled ? 'Ask a question, e.g. “Breakdown my payslip”' : 'Ask about your payslip, leave or WFH (AI explanations are off)'}" aria-label="Your question"></textarea><button class="btn btn-primary" type="submit" aria-label="Send">${icon('send')}</button></form>`;
  }

  async function openConversation(id, feature) {
    activeConversationId = id;
    markActive($('#convs'));
    if (!id) { emptyPane(feature); return; }
    $('#pane').innerHTML = html`<div class="chat-messages" id="messages"><span class="skeleton" style="width:60%"></span></div>${composer()}`;
    try {
      const data = await api.get(`/ai/conversations/${id}/`);
      $('#messages').innerHTML = data.messages.length ? html`${data.messages.map(bubble)}` : html`<div class="ai-welcome">${App.empty({ iconName: 'sparkle', title: FEATURES[feature].label, text: 'Ask your first question below.' })}</div>`;
      $('#messages').scrollTop = $('#messages').scrollHeight;
    } catch (error) { $('#messages').innerHTML = App.empty({ iconName: 'alert', title: 'Could not load the conversation', text: error.message }); }
    wireComposer(id, feature);
  }

  function wireComposer(conversationId, feature) {
    let id = conversationId;
    const form = $('#askForm'), input = $('#question');
    const autosize = () => { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 160)}px`; };
    input.addEventListener('input', autosize);
    input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); } });
    $$('[data-chip]').forEach(chip => chip.addEventListener('click', () => { input.value = chip.textContent; autosize(); form.requestSubmit(); }));
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const question = input.value.trim();
      if (!question) return;
      const box = $('#messages');
      if ($('.ai-welcome', box)) box.innerHTML = '';
      box.insertAdjacentHTML('beforeend', bubble({ role: 'user', content: question, created_at: new Date().toISOString() }).toString());
      box.insertAdjacentHTML('beforeend', '<div class="bubble-row" id="typing"><div class="bubble ai-typing" aria-label="The assistant is typing"><span></span><span></span><span></span></div></div>');
      box.scrollTop = box.scrollHeight;
      input.value = ''; autosize(); input.disabled = true;
      try {
        if (!id) {
          const payload = { feature };
          const subject = $('#subject'), payslip = $('#payslip');
          if (subject && subject.value) payload.subject_id = Number(subject.value);
          if (payslip && payslip.value) payload.payslip_id = Number(payslip.value);
          id = (await api.post('/ai/conversations/', payload)).id;
          activeConversationId = id;
        }
        const result = await api.post(`/ai/conversations/${id}/messages/`, { message: question });
        $('#typing').remove();
        box.lastElementChild.remove();
        box.insertAdjacentHTML('beforeend', html`${result.messages.map(bubble)}`.toString());
        if (result.notice) box.insertAdjacentHTML('beforeend', html`<div class="alert alert-warning ai-notice" role="status">${icon('info')}<span>${result.notice}</span></div>`.toString());
        box.scrollTop = box.scrollHeight;
        if (!conversationId) { await listConversations(feature); markActive($('#convs')); conversationId = id; }
      } catch (error) {
        const typing = $('#typing'); if (typing) typing.remove();
        box.insertAdjacentHTML('beforeend', html`<div class="alert alert-danger" role="alert">${icon('alert')}<span>${error.message}</span></div>`.toString());
        input.value = question; autosize();
        box.scrollTop = box.scrollHeight;
      } finally { input.disabled = false; input.focus(); }
    });
  }

  /* ------------------------------------------------------------------ *
   * Attendance insights
   * ------------------------------------------------------------------ */
  async function renderInsights(openId = null) {
    const end = App.todayISO();
    const start = fmt.iso(new Date(Date.now() - 29 * 86400000));
    const people = await loadEmployees();
    $('#panel').innerHTML = html`<div class="card-body stack">
      <form class="toolbar" id="insightForm" style="padding:0;border:0">
        ${admin ? html`<select class="select" id="scope" aria-label="Whose attendance"><option value="COMPANY">Whole company</option>${people.map(e => html`<option value="${e.user_id}">${e.full_name} · ${e.employee_id}</option>`)}</select>` : ''}
        <label class="sr-only" for="iFrom">From</label><input class="input" type="date" id="iFrom" value="${start}" max="${end}" style="width:auto" aria-label="From">
        <label class="sr-only" for="iTo">To</label><input class="input" type="date" id="iTo" value="${end}" max="${end}" style="width:auto" aria-label="To">
        <button class="btn" type="button" id="statsBtn">${icon('chart')} Show figures</button>
        <button class="btn btn-primary" type="submit" id="genBtn" ${status.enabled ? '' : App.raw('disabled')}>${icon('sparkle')} Generate AI insights</button>
      </form>
      <div class="grid grid-4" id="iStats"></div>
      <div class="grid grid-main">
        <section class="card"><div class="card-header"><div><h2>AI insights</h2><p id="iNote">Generate insights for the chosen period.</p></div></div><div id="iChat"></div></section>
        <section class="card ai-history-card"><div class="card-header"><div><h2>Previous insights</h2></div></div><div class="ai-side-head">${searchBox()}</div><div class="chat-contacts" id="iHistory" role="list" aria-label="Previous insights"></div></section>
      </div>
    </div>`;
    const target = () => {
      const scope = $('#scope');
      if (!scope) return { scope: 'SELF' };
      return scope.value === 'COMPANY' ? { scope: 'COMPANY' } : { scope: 'EMPLOYEE', subject_id: Number(scope.value) };
    };
    const period = () => ({ from: $('#iFrom').value, to: $('#iTo').value });
    $('#statsBtn').addEventListener('click', () => showStats({ ...target(), ...period() }));
    $('#insightForm').addEventListener('submit', async event => {
      event.preventDefault();
      const button = $('#genBtn'); const original = button.innerHTML;
      button.disabled = true; button.innerHTML = '<span class="spinner"></span> Analysing…';
      $('#iChat').innerHTML = html`<div class="chat-messages" style="min-height:160px"><div class="bubble-row"><div class="bubble ai-typing"><span></span><span></span><span></span></div></div></div>`;
      try {
        const result = await api.post('/ai/attendance-insights/', { ...target(), ...period() });
        paintStats(result.stats);
        activeConversationId = result.conversation.id;
        showInsightConversation(result.conversation, result.messages);
        loadInsightHistory();
      } catch (error) {
        if (error.data && error.data.stats) paintStats(error.data.stats);
        $('#iChat').innerHTML = html`<div class="card-body"><div class="alert alert-danger" role="alert">${icon('alert')}<span>${error.message}</span></div></div>`;
      } finally { button.disabled = !status.enabled; button.innerHTML = original; }
    });
    showStats({ ...target(), ...period() });
    wireSearch($('.ai-history-card'), loadInsightHistory, 'ATTENDANCE');
    await loadInsightHistory();
    if (openId) openInsight(Number(openId));
    if (!status.enabled) $('#iChat').innerHTML = html`<div class="card-body muted">The figures above are calculated from attendance records. AI-written insights need a Gemini API key on the server.</div>`;
  }

  async function showStats(query) {
    $('#iStats').innerHTML = html`${[0, 1, 2, 3].map(() => html`<div class="card stat"><span class="skeleton" style="width:100%;height:56px"></span></div>`)}`;
    try { paintStats((await api.get('/ai/attendance-insights/stats/', query)).stats); } catch (error) { $('#iStats').innerHTML = html`<div class="alert alert-danger" style="grid-column:1/-1">${icon('alert')}<span>${error.message}</span></div>`; }
  }

  function paintStats(s) {
    if (!s) return;
    const card = (iconName, tone, label, value, note) => html`<div class="card stat"><span class="stat-icon ${tone}">${icon(iconName)}</span><div><div class="stat-label">${label}</div><div class="stat-value">${value}</div><div class="stat-note">${note}</div></div></div>`;
    if ('departments' in s) {
      $('#iStats').innerHTML = html`
        ${card('users', '', 'Check-ins', fmt.number(s.check_ins), `${s.active_employees} active employees · ${s.working_days} working days`)}
        ${card('clock', 'amber', 'Late check-ins', fmt.number(s.late_check_ins), s.check_ins ? `${Math.round(100 * s.late_check_ins / s.check_ins)}% of check-ins` : '—')}
        ${card('timer', 'amber', 'Late minutes', fmt.number(s.late_minutes_total), s.most_late.length ? `Most: ${s.most_late[0].name}` : 'No late arrivals')}
        ${card('calendar', 'blue', 'Late by weekday', Object.keys(s.late_by_weekday).length ? Object.entries(s.late_by_weekday).sort((a, b) => b[1] - a[1])[0][0] : '—', 'Day with most late check-ins')}`;
      return;
    }
    $('#iStats').innerHTML = html`
      ${card('pin', 'blue', 'Attendance rate', s.attendance_rate == null ? '—' : `${s.attendance_rate}%`, `${s.days_present} present · ${s.approved_leave_days} leave · ${s.wfh_days} WFH of ${s.working_days} days`)}
      ${card('alert', '', 'Absent days', s.absent_days, s.absent_days ? `Last: ${fmt.date(s.absent_dates[s.absent_dates.length - 1])}` : 'None')}
      ${card('clock', 'amber', 'Late days', s.late_days, `${fmt.number(s.late_minutes_total)} min total · ${s.late_minutes_average} min avg`)}
      ${card('briefcase', 'green', 'Average day', s.average_hours_worked == null ? '—' : `${s.average_hours_worked} h`, s.average_check_in ? `Typical check-in ${s.average_check_in}` : 'No check-ins')}`;
  }

  function showInsightConversation(conversation, messages) {
    $('#iNote').textContent = conversation.title;
    $('#iChat').innerHTML = html`<div class="chat-messages ai-insight" id="messages">${messages.filter(m => m.role === 'assistant' || messages.indexOf(m) > 0).map(bubble)}</div>${composer()}`;
    wireComposer(conversation.id, 'ATTENDANCE');
  }

  async function openInsight(id) {
    activeConversationId = id;
    markActive($('#iHistory'));
    try {
      const data = await api.get(`/ai/conversations/${id}/`);
      showInsightConversation(data.conversation, data.messages);
    } catch (error) { App.error(error); }
  }

  async function loadInsightHistory() {
    const container = $('#iHistory');
    if (!container) return;
    try {
      const list = await api.get('/ai/conversations/', { feature: 'ATTENDANCE' });
      if (searchActive(container)) return;
      renderSections(container, list, { emptyText: 'No insights generated yet.' });
      wireList(container, list, { open: openInsight, refresh: loadInsightHistory });
    } catch (error) { container.innerHTML = html`<div class="ai-list-empty muted">${error.message}</div>`; }
  }

  /* ------------------------------------------------------------------ *
   * Knowledge base (administrators)
   * ------------------------------------------------------------------ */
  async function renderKnowledge() {
    let kb;
    try { kb = await api.get('/ai/knowledge/'); } catch (error) { $('#panel').innerHTML = html`<div class="card-body">${App.empty({ iconName: 'alert', title: 'Could not load the knowledge base', text: error.message })}</div>`; return; }
    $('#panel').innerHTML = html`<form class="card-body form-grid" id="kbForm">
      <p class="span-2 muted" style="margin:0">The assistants quote this text when employees ask about your organisation. Keep it factual; do not include personal data. ${kb.updated_at ? `Last updated ${fmt.dateTime(kb.updated_at)}${kb.updated_by_username ? ` by ${kb.updated_by_username}` : ''}.` : ''}</p>
      ${field({ label: 'Company overview', name: 'company_overview', type: 'textarea', value: kb.company_overview, span2: true, attrs: 'rows="5" maxlength="8000"', hint: 'Who you are, office timings, contacts for HR and payroll.' })}
      ${field({ label: 'Leave policy', name: 'leave_policy', type: 'textarea', value: kb.leave_policy, span2: true, attrs: 'rows="7" maxlength="8000"', hint: 'Notice periods, documentation for sick leave, carry-forward rules, etc. System rules (entitlements, balances, unpaid "Other" leave) are added automatically.' })}
      ${field({ label: 'Frequently asked questions', name: 'faq', type: 'textarea', value: kb.faq, span2: true, attrs: 'rows="6" maxlength="8000"' })}
      <div class="span-2"><div class="alert alert-danger" id="kbError" hidden></div><button class="btn btn-primary" type="submit">${icon('check')} Save knowledge base</button></div>
    </form>`;
    $('#kbForm').addEventListener('submit', async event => {
      event.preventDefault();
      const button = $('button[type=submit]', event.target); button.disabled = true;
      $('#kbError').hidden = true;
      try { await api.put('/ai/knowledge/', Object.fromEntries(new FormData(event.target))); App.toast('Knowledge base saved.'); }
      catch (error) { $('#kbError').textContent = error.message; $('#kbError').hidden = false; }
      finally { button.disabled = false; }
    });
  }

  /* ---- start ---- */
  try { status = await api.get('/ai/status/'); } catch (error) { status = { enabled: false }; }
  $('#aiStatus').innerHTML = status.enabled
    ? html`<span class="badge badge-success" title="Model ${status.model}">${icon('sparkle', 'icon-sm')} Gemini connected</span>`
    : html`<span class="badge badge-warning">${icon('alert', 'icon-sm')} AI not configured</span>`;
  if (!status.enabled) {
    $('#notice').innerHTML = html`<div class="alert alert-warning" style="margin-bottom:16px">${icon('info')}<span>${admin ? 'Add GEMINI_API_KEY to backend/.env and restart the server to enable AI explanations. Until then, questions about payslips, leave, WFH and how PayrollPro works are answered directly from PayrollPro records and the guide, and attendance figures still work.' : 'AI explanations are not available yet. You can still ask about your payslip, leave, work from home and how PayrollPro works; answers come straight from your PayrollPro records and the guide.'}</span></div>`;
  }
  renderTabs();
  render();
})();
