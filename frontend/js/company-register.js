(function () {
  'use strict';
  const form = document.querySelector('#companyRegisterForm');
  const errorBox = document.querySelector('#companyRegisterError');
  form.addEventListener('input', () => {
    errorBox.textContent = '';
    errorBox.hidden = true;
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    errorBox.hidden = true;
    errorBox.textContent = '';

    const payload = Object.fromEntries(new FormData(form));
    const password = payload.password || '';
    const confirmPassword = payload.confirm_password || '';

    if (password.length < 8) {
      errorBox.textContent = 'Password must be at least 8 characters long.';
      errorBox.hidden = false;
      return;
    }
    if (password !== confirmPassword) {
      errorBox.textContent = 'Passwords do not match.';
      errorBox.hidden = false;
      return;
    }

    const submit = form.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      const result = await App.api.post('/companies/register/', payload, { auth: false });
      App.api.resetCsrf();
      App.session.set({ username: result.username, role: 'ADMIN', fullName: result.full_name, companyName: result.company_name });
      location.replace(App.session.home('ADMIN'));
    } catch (error) {
      errorBox.textContent = error.message || 'Company registration could not be completed.';
      errorBox.hidden = false;
      submit.disabled = false;
    }
  });
})();
