(async function () {
  'use strict';
  const { $, $$, html, icon, api, fmt, field } = App;
  const user = await App.boot({ nav: 'settings' });
  $('#who').textContent = user.username;
  $('#signOut').innerHTML = html`${icon('logout')} Sign out`;
  $('#signOut').addEventListener('click', () => App.session.logout());
  const form = $('#pwForm'), errorBox = $('#pwError');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    errorBox.hidden = true;
    const data = Object.fromEntries(new FormData(form));
    if (!data.current_password || !data.new_password) { errorBox.textContent = 'Please fill in all fields.'; errorBox.hidden = false; return; }
    if (data.new_password !== data.confirm_password) { errorBox.textContent = 'New passwords do not match.'; errorBox.hidden = false; return; }
    const button = $('button[type=submit]', form); button.disabled = true;
    try { await api.post('/password/change/', data); form.reset(); App.toast('Password updated.'); }
    catch (error) { errorBox.textContent = error.message; errorBox.hidden = false; }
    finally { button.disabled = false; }
  });

  /* ---- Google account (connect / disconnect) ---- */
  const gErr = $('#googleError'), gOk = $('#googleOk');
  const params = new URLSearchParams(location.search);
  if (params.get('google_error')) { gErr.textContent = App.googleErrorMessage(params.get('google_error')); gErr.hidden = false; }
  if (params.get('google') === 'linked') { gOk.textContent = 'Google account connected. You can now use "Continue with Google".'; gOk.hidden = false; }
  if (params.has('google') || params.has('google_error')) history.replaceState(null, '', location.pathname);

  async function loadGoogle() {
    const box = $('#googleStatus');
    try {
      const status = await api.get('/auth/google/link/');
      if (status.connected) {
        box.innerHTML = html`<div class="row" style="justify-content:space-between"><div class="row">${App.googleLogo()}<div><div style="font-weight:600">Connected</div><div class="muted">${status.email}</div></div></div><button class="btn btn-sm" id="gDisconnect" type="button">Disconnect</button></div>
          ${status.has_password ? '' : html`<p class="muted" style="margin:0">This account has no password. Use "Forgot password" on the sign-in page to add one before disconnecting Google.</p>`}`;
        $('#gDisconnect').addEventListener('click', async () => {
          gErr.hidden = true; gOk.hidden = true;
          const ok = await App.confirm({ title: 'Disconnect Google?', message: 'You will need your password to sign in.', confirmLabel: 'Disconnect', danger: true });
          if (!ok) return;
          try { await api.delete('/auth/google/link/'); gOk.textContent = 'Google account disconnected.'; gOk.hidden = false; loadGoogle(); } catch (error) { gErr.textContent = error.message; gErr.hidden = false; }
        });
      } else {
        box.innerHTML = html`<button class="btn btn-google" id="gConnect" type="button" ${status.enabled ? '' : App.raw('aria-disabled="true"')}>${App.googleLogo()}<span>Connect Google account</span></button>
          ${status.enabled ? '' : html`<p class="google-hint">Google sign-in has not been set up on this server yet.</p>`}`;
        $('#gConnect').addEventListener('click', async event => {
          gErr.hidden = true; gOk.hidden = true;
          if (!status.enabled) { gErr.textContent = 'Google sign-in has not been set up on this server yet.'; gErr.hidden = false; return; }
          const button = event.currentTarget; button.disabled = true;
          try { await App.startGoogle({ mode: 'link' }); } catch (error) { gErr.textContent = error.message; gErr.hidden = false; button.disabled = false; }
        });
      }
    } catch (error) { box.innerHTML = html`<p class="muted" style="margin:0">Could not load Google account status.</p>`; }
  }
  loadGoogle();

  /* ---- Notification preferences (security and other mandatory kinds cannot be switched off) ---- */
  // The cards are added here so settings.html (read-only in this checkout) does not need to change.
  const grid = $('#googleCard').parentElement;
  grid.insertAdjacentHTML('beforeend', String(html`
    <section class="card" id="notifications">
      <div class="card-header"><div><h2>Notifications</h2><p>Choose which optional notifications you receive in PayrollPro.</p></div></div>
      <form class="card-body stack-sm" id="prefForm"><span class="skeleton" style="width:60%"></span></form>
    </section>
    <section class="card" id="remindersCard" hidden>
      <div class="card-header"><div><h2>Automatic reminders</h2><p>Document expiry, requests waiting for approval and unfinished onboarding.</p></div></div>
      <form class="card-body form-grid" id="reminderForm"></form>
    </section>`));
  const prefForm = $('#prefForm');
  const MANDATORY_LABELS = {
    SECURITY: 'security alerts (password and Google sign-in changes)', EMPLOYEE: 'payslips and your employee record',
    PAYROLL: 'payroll', ONBOARDING: 'onboarding', GENERAL: 'messages sent to you by an administrator',
  };
  async function loadPrefs() {
    try {
      const data = await api.get('/notifications/preferences/');
      prefForm.innerHTML = html`<div class="pref-list">${data.optional.map(p => html`<label class="check"><span>${p.label}</span><input type="checkbox" name="${p.kind}"${p.enabled ? App.raw(' checked') : ''}></label>`)}</div>
        <p class="muted" style="margin:0">${icon('lock', 'icon-sm')} Always on: ${data.mandatory.map(m => MANDATORY_LABELS[m.kind] || m.label.toLowerCase()).join(', ')}.</p>
        <div><button class="btn btn-primary" type="submit">Save notification settings</button></div>`;
    } catch (error) { prefForm.innerHTML = html`<p class="muted" style="margin:0">Could not load notification settings. ${error.message}</p>`; }
  }
  prefForm.addEventListener('submit', async event => {
    event.preventDefault();
    const preferences = Object.fromEntries($$('input[type=checkbox]', prefForm).map(box => [box.name, box.checked]));
    try { await api.put('/notifications/preferences/', { preferences }); App.toast('Notification settings saved.'); } catch (error) { App.error(error); }
  });
  loadPrefs();
  if (location.hash === '#notifications') setTimeout(() => $('#notifications').scrollIntoView({ block: 'start' }), 300);

  /* ---- Administrators: automatic reminders ---- */
  if (user.role === 'ADMIN') {
    $('#remindersCard').hidden = false;
    const form = $('#reminderForm');
    const loadReminders = async () => {
      try {
        const s = await api.get('/reminders/settings/');
        form.innerHTML = html`
          ${field({ label: 'Send automatic reminders', name: 'enabled', type: 'checkbox', value: s.enabled, span2: true })}
          ${field({ label: 'Document expiry reminders (days before)', name: 'days', value: s.document_reminder_days.join(', '), hint: 'Comma-separated, e.g. 30, 7, 1. A reminder is also sent when a document expires.', span2: true, attrs: 'inputmode="numeric" pattern="[0-9, ]+"' })}
          ${field({ label: 'Remind about requests waiting at least (days)', name: 'pending_after_days', type: 'number', value: s.pending_after_days, attrs: 'min="1" max="60"', hint: 'Leave, WFH, attendance corrections, overtime and documents.' })}
          <div class="field"><span class="hint">Last run: ${s.last_run_at ? fmt.dateTime(s.last_run_at) : 'never'}. Reminders also run automatically when a dashboard is opened (at most every 6 hours), or daily with <code>manage.py send_reminders</code>.</span></div>
          <div class="span-2 actions" style="justify-content:flex-start"><button class="btn btn-primary" type="submit">Save reminders</button><button class="btn" type="button" id="runNow">${icon('bell')} Send due reminders now</button></div>`;
        $('#runNow').addEventListener('click', async () => {
          try {
            const r = await api.post('/reminders/run/');
            App.toast(r.enabled ? `Sent ${r.documents} document, ${r.pending_digest} pending and ${r.onboarding} onboarding reminder(s).` : 'Reminders are switched off.');
            loadReminders();
          } catch (error) { App.error(error); }
        });
      } catch (error) { form.innerHTML = html`<p class="muted span-2" style="margin:0">Could not load reminder settings. ${error.message}</p>`; }
    };
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const data = new FormData(form);
      const days = String(data.get('days') || '').split(',').map(v => v.trim()).filter(Boolean).map(Number);
      if (!days.length || days.some(d => !Number.isInteger(d) || d < 0 || d > 365)) { App.toast('Enter reminder days between 0 and 365, separated by commas.', 'error'); return; }
      try {
        await api.put('/reminders/settings/', { enabled: data.get('enabled') === 'on', document_reminder_days: days, pending_after_days: Number(data.get('pending_after_days')) });
        App.toast('Reminder settings saved.'); loadReminders();
      } catch (error) { App.error(error); }
    });
    loadReminders();
  }
})();
