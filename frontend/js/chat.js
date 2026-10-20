(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api } = App;
  const user = await App.boot({ nav: 'chat' });
  const admin = user.role === 'ADMIN';
  const params = new URLSearchParams(location.search);
  let conversations = [], activeId = Number(params.get('conversation')) || null, poll = null;

  const title = c => (admin ? c.employee_name : `${c.administrator_username} (Administrator)`);

  async function loadConversations() {
    try { conversations = await api.get('/chat/conversations/'); } catch (error) {
      $('#contacts').innerHTML = App.empty({ iconName: 'alert', title: 'Could not load conversations', text: error.message, action: html`<button class="btn btn-sm" id="retry">Try again</button>` });
      $('#retry').addEventListener('click', loadConversations);
      return;
    }
    renderContacts();
  }

  function renderContacts() {
    $('#contacts').innerHTML = conversations.length ? html`${conversations.map(c => html`<button class="contact" type="button" role="listitem" data-id="${c.id}"${c.id === activeId ? App.raw(' aria-current="true"') : ''}>
      <span class="avatar avatar-sm">${fmt.initials(title(c))}</span>
      <span class="contact-copy"><span class="contact-name">${title(c)}</span><span class="contact-preview">${c.last_message || 'No messages yet'}</span></span>
      ${c.unread_count ? html`<span class="badge badge-accent">${c.unread_count}</span>` : ''}</button>`)}`
      : App.empty({ iconName: 'chat', title: 'No conversations', text: admin ? 'Choose an employee above to start one.' : 'An administrator will start a conversation with you when needed.' });
    $$('.contact', $('#contacts')).forEach(b => b.addEventListener('click', () => open(Number(b.dataset.id))));
  }

  function emptyPane() {
    $('#chat').classList.remove('chat-open');
    $('#pane').innerHTML = App.empty({ iconName: 'chat', title: 'Select a conversation', text: 'Your messages will appear here.' });
  }

  async function open(id) {
    activeId = id;
    renderContacts();
    const conv = conversations.find(c => c.id === id);
    if (!conv) return emptyPane();
    $('#chat').classList.add('chat-open');
    $('#pane').innerHTML = html`<div class="chat-head"><button class="icon-btn" id="back" type="button" aria-label="Back to conversations">${icon('left')}</button><span class="avatar avatar-sm">${fmt.initials(title(conv))}</span><strong>${title(conv)}</strong></div>
      <div class="chat-messages" id="messages" aria-live="polite"></div>
      <form class="chat-form" id="sendForm"><input class="input" id="body" name="body" placeholder="Write a message" aria-label="Message" maxlength="4000" autocomplete="off"><button class="btn btn-primary" type="submit" aria-label="Send">${icon('send')}</button></form>`;
    $('#back').addEventListener('click', () => { activeId = null; emptyPane(); renderContacts(); clearInterval(poll); });
    $('#sendForm').addEventListener('submit', async event => {
      event.preventDefault();
      const input = $('#body'); const text = input.value.trim();
      if (!text) return;
      input.disabled = true;
      try { await api.post(`/chat/conversations/${id}/messages/`, { body: text }); input.value = ''; await loadMessages(id, true); } catch (error) { App.error(error); }
      input.disabled = false; input.focus();
    });
    await loadMessages(id, true);
    clearInterval(poll);
    poll = setInterval(() => { if (document.visibilityState === 'visible') loadMessages(id, false); }, 8000);
  }

  let lastCount = -1;
  async function loadMessages(id, scroll) {
    const box = $('#messages');
    if (!box || id !== activeId) return;
    try {
      const messages = await api.get(`/chat/conversations/${id}/messages/`);
      if (messages.length === lastCount && !scroll) return;
      const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
      box.innerHTML = messages.length ? html`${messages.map(m => html`<div class="bubble-row${m.is_own ? ' own' : ''}"><div class="bubble">${m.body}<time datetime="${m.created_at}">${fmt.dateTime(m.created_at)}</time></div></div>`)}` : App.empty({ iconName: 'chat', title: 'No messages yet', text: 'Say hello to start the conversation.' });
      if (scroll || atBottom) box.scrollTop = box.scrollHeight;
      lastCount = messages.length;
    } catch (error) { if (scroll) box.innerHTML = App.empty({ iconName: 'alert', title: 'Could not load messages', text: error.message }); }
  }

  if (admin) {
    $('#newChatBox').hidden = false;
    try {
      const people = await api.get('/chat/employees/');
      $('#newChat').innerHTML = html`<option value="">Start a conversation…</option>${people.map(p => html`<option value="${p.employee_id}">${p.display_name}${p.department ? ` · ${p.department}` : ''}</option>`)}`;
    } catch (error) { /* list stays empty */ }
    $('#newChat').addEventListener('change', async event => {
      const employeeId = event.target.value; if (!employeeId) return;
      try { const conv = await api.post('/chat/conversations/', { employee_id: Number(employeeId) }); await loadConversations(); await open(conv.id); } catch (error) { App.error(error); }
      event.target.value = '';
    });
  }
  emptyPane();
  await loadConversations();
  if (activeId) open(activeId);
})();
