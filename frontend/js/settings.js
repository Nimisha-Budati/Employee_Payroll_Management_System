(async function () {
  'use strict';
  const { $, html, icon, api } = App;
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
})();
