/* Landing page after the backend finished the Google flow. The session cookie is already set by the
   server; we only read who is signed in (from the server, not from the URL) and go to the right home. */
(async function () {
  'use strict';
  const params = new URLSearchParams(location.search);
  if (params.get('status') !== 'ok') { location.replace('index.html?google_error=server_error'); return; }
  try {
    const profile = await App.api.get('/profile/', undefined, { auth: false });
    const fullName = `${profile.first_name || ''} ${profile.last_name || ''}`.trim() || profile.username;
    App.session.set({ username: profile.username, role: profile.role, fullName });
    location.replace(App.session.home(profile.role));
  } catch (error) {
    App.session.clear();
    location.replace('index.html?google_error=server_error');
  }
})();
