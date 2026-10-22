(function () {
  'use strict';
  const form = document.querySelector('#companyRegisterForm');
  const errorBox = document.querySelector('#companyRegisterError');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    errorBox.hidden = true;
    const submit = form.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      const payload = Object.fromEntries(new FormData(form));
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
