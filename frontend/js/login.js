(function () {
  'use strict';
  const { $, $$, icon, api } = App;
  $('#authTheme').innerHTML = App.themeToggleHtml();
  App.bindThemeToggle($('#authTheme'));
  let role = 'EMPLOYEE';
  let resetToken = '';

  ['pt1', 'pt2', 'pt3'].forEach((id, index) => { $(`#${id}`).innerHTML = icon(['wallet', 'receipt', 'shield'][index]); });

  function show(id) {
    ['loginSection', 'registerSection', 'recoverySection'].forEach(section => { $(`#${section}`).hidden = section !== id; });
    $$('.alert[role]').forEach(box => { box.hidden = true; });
    const focusTarget = $('input', $(`#${id}`));
    if (focusTarget) focusTarget.focus();
  }
  $$('[data-show]').forEach(button => button.addEventListener('click', () => {
    show(button.dataset.show);
    if (button.dataset.show === 'registerSection') loadCompanies();
  }));

  function note(id, message) {
    const box = $(`#${id}`);
    box.textContent = message || '';
    box.hidden = !message;
  }

  function setRole(next) {
    role = next;
    $('#employeeBtn').setAttribute('aria-pressed', String(role === 'EMPLOYEE'));
    $('#adminBtn').setAttribute('aria-pressed', String(role === 'ADMIN'));
    $('#loginSubmit').textContent = role === 'ADMIN' ? 'Sign in as administrator' : 'Sign in as employee';
    $('#registerLink').hidden = role === 'ADMIN';
  }
  $('#employeeBtn').addEventListener('click', () => setRole('EMPLOYEE'));
  $('#adminBtn').addEventListener('click', () => setRole('ADMIN'));
  setRole('EMPLOYEE');

  $$('[data-toggle-password]').forEach(button => {
    const input = $(`#${button.dataset.togglePassword}`);
    button.innerHTML = icon('eye');
    button.addEventListener('click', () => {
      const reveal = input.type === 'password';
      input.type = reveal ? 'text' : 'password';
      button.innerHTML = icon(reveal ? 'eyeOff' : 'eye');
      button.setAttribute('aria-label', reveal ? 'Hide password' : 'Show password');
    });
  });

  async function busy(button, label, work) {
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner"></span> ${label}`;
    try { return await work(); } finally { button.disabled = false; button.innerHTML = original; }
  }

  $('#loginForm').addEventListener('submit', async event => {
    event.preventDefault();
    note('loginError', '');
    const username = $('#loginUsername').value.trim();
    const password = $('#loginPassword').value;
    if (!username || !password) { note('loginError', 'Please enter your username and password.'); return; }
    try {
      const data = await busy($('#loginSubmit'), 'Signing in…', () => api.post('/login/', {
        username, password, role, remember_me: $('#rememberMe').checked,
      }, { auth: false }));
      api.resetCsrf();
      App.session.set({ username: data.username, role: data.role, fullName: data.full_name, companyName: data.company_name || '' });
      location.replace(App.session.home(data.role));
    } catch (error) {
      note('loginError', error.message);
    }
  });

  let companiesList = [];
  async function loadCompanies() {
    const select = $('#registerCompany');
    const field = $('#registerCompanyField');
    if (!select || !field) return;
    // Show the field immediately with a loading placeholder
    select.innerHTML = '<option value="">Loading companies…</option>';
    field.hidden = false;
    try {
      const data = await api.get('/companies/public/', undefined, { auth: false });
      companiesList = (data.companies || []).sort((a, b) => a.name.localeCompare(b.name));
      if (!companiesList.length) {
        field.hidden = true;
        return;
      }
      select.innerHTML = '<option value="">— Select your company —</option>' +
        companiesList.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
      if (companiesList.length === 1) {
        select.value = String(companiesList[0].id);
      }
      field.hidden = false;
    } catch {
      select.innerHTML = '<option value="">Could not load companies — please refresh</option>';
      field.hidden = false;
    }
  }

  $('#registerForm').addEventListener('submit', async event => {
    event.preventDefault();
    note('registerError', ''); note('registerOk', '');
    const form = event.target;
    const values = Object.fromEntries(new FormData(form));
    if (companiesList.length && !values.company_id) { note('registerError', 'Please select your company.'); return; }
    if (!values.username.trim() || !values.email.trim() || !values.password || !values.confirm_password) { note('registerError', 'Please fill in all fields.'); return; }
    if (values.password.length < 8) { note('registerError', 'Password must be at least 8 characters long.'); return; }
    if (values.password !== values.confirm_password) { note('registerError', 'Passwords do not match.'); return; }
    try {
      await busy($('button[type=submit]', form), 'Creating…', () => api.post('/register/', { ...values, role: 'EMPLOYEE' }, { auth: false }));
      form.reset();
      note('registerOk', 'Account created. You can sign in now.');
      setTimeout(() => show('loginSection'), 1400);
    } catch (error) {
      note('registerError', error.message);
    }
  });

  /* ---- Continue with Google ---- */
  let googleEnabled = false;
  const googleButtons = [['#googleLogin', 'login', 'Continue with Google'], ['#googleRegister', 'register', 'Sign up with Google']];
  googleButtons.forEach(([selector, , label]) => { $(selector).innerHTML = `${App.googleLogo().toString()}<span>${label}</span>`; });
  api.get('/auth/google/config/', undefined, { auth: false }).then(({ enabled }) => {
    googleEnabled = enabled;
    if (!enabled) {
      googleButtons.forEach(([selector]) => $(selector).setAttribute('aria-disabled', 'true'));
      const hint = $('#googleHint');
      hint.textContent = 'Google sign-in has not been set up on this server yet.';
      hint.hidden = false;
    }
  }).catch(() => { /* backend unreachable: the normal sign-in form shows its own error */ });
  googleButtons.forEach(([selector, mode]) => $(selector).addEventListener('click', async () => {
    const errorBox = mode === 'register' ? 'registerError' : 'loginError';
    note(errorBox, '');
    if (!googleEnabled) { note(errorBox, 'Google sign-in has not been set up on this server yet.'); return; }
    const button = $(selector);
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span> Redirecting to Google…';
    try {
      await App.startGoogle({ mode, role: mode === 'register' ? 'EMPLOYEE' : role, remember_me: $('#rememberMe').checked });
    } catch (error) {
      note(errorBox, error.message);
      button.disabled = false; button.innerHTML = original;
    }
  }));

  // Coming back from Google with a problem: show a fixed, known message for the error code.
  const params = new URLSearchParams(location.search);
  if (params.get('google_error')) {
    const registering = params.get('view') === 'register';
    if (registering) show('registerSection');
    note(registering ? 'registerError' : 'loginError', App.googleErrorMessage(params.get('google_error')));
    history.replaceState(null, '', location.pathname);
  }

  /* Password recovery: request code -> verify code -> choose new password */
  function recoveryStep(step) {
    ['recoveryStep1', 'recoveryStep2', 'recoveryStep3'].forEach((id, index) => { $(`#${id}`).hidden = index + 1 !== step; });
    $('#recoveryLead').textContent = ['Enter your username or email and we will send you a verification code.', 'Enter the 6-digit code we sent to your email.', 'Choose a new password for your account.'][step - 1];
  }
  async function requestCode() {
    note('recoveryError', ''); note('recoveryOk', '');
    const identifier = $('#recoveryEmail').value.trim();
    if (!identifier) { note('recoveryError', 'Enter your username or email.'); return false; }
    try {
      const data = await api.post('/password/forgot/', { email: identifier }, { auth: false });
      note('recoveryOk', data.message);
      recoveryStep(2);
      $('#recoveryOTP').focus();
      return true;
    } catch (error) { note('recoveryError', error.message); return false; }
  }
  $('#recoveryStep1').addEventListener('submit', async event => { event.preventDefault(); await busy($('button[type=submit]', event.target), 'Sending…', requestCode); });
  $('#resendCode').addEventListener('click', requestCode);
  $('#recoveryStep2').addEventListener('submit', async event => {
    event.preventDefault();
    note('recoveryError', ''); note('recoveryOk', '');
    try {
      const data = await busy($('button[type=submit]', event.target), 'Verifying…', () => api.post('/password/verify-otp/', { email: $('#recoveryEmail').value.trim(), otp: $('#recoveryOTP').value.trim() }, { auth: false }));
      resetToken = data.reset_token;
      recoveryStep(3);
      $('#recoveryPassword').focus();
    } catch (error) { note('recoveryError', error.message); }
  });
  $('#recoveryStep3').addEventListener('submit', async event => {
    event.preventDefault();
    note('recoveryError', ''); note('recoveryOk', '');
    const password = $('#recoveryPassword').value, confirm = $('#recoveryConfirm').value;
    if (password !== confirm) { note('recoveryError', 'Passwords do not match.'); return; }
    try {
      await busy($('button[type=submit]', event.target), 'Saving…', () => api.post('/password/reset/', { reset_token: resetToken, password, confirm_password: confirm }, { auth: false }));
      resetToken = '';
      event.target.reset();
      note('recoveryOk', 'Password reset. You can sign in now.');
      setTimeout(() => { recoveryStep(1); show('loginSection'); }, 1400);
    } catch (error) { note('recoveryError', error.message); }
  });

  if (new URLSearchParams(location.search).get('expired')) {
    note('expiredNotice', 'Your session has ended. Please sign in again.');
  }

  // Already signed in? Skip the form if the server still recognises the session.
  const stored = App.session.get();
  if (stored && stored.role && !new URLSearchParams(location.search).get('expired')) {
    api.get('/profile/', undefined, { auth: false }).then(profile => {
      if (profile.role === stored.role) location.replace(App.session.home(stored.role));
    }).catch(() => App.session.clear());
  }
})();
