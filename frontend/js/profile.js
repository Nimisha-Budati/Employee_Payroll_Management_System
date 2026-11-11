(async function () {
  'use strict';
  const { $, html, icon, fmt, api } = App;
  const form = $('#form'), errorBox = $('#formError');
  const saveButton = $('#saveProfileBtn', form);
  // Keep the static form from navigating/reloading while async profile data is loading.
  form.addEventListener('submit', event => event.preventDefault(), true);
  saveButton.disabled = true;
  const role = document.body.dataset.role;
  await App.boot({ role, nav: 'profile' });
  $('label[for=photo]').innerHTML = html`${icon('upload', 'icon-sm')} Change photo`;
  let savedEmail = '';

  function fill(profile) {
    ['first_name', 'last_name', 'email', 'phone', 'address'].forEach(name => { form.elements[name].value = profile[name] || ''; });
    const name = `${profile.first_name || ''} ${profile.last_name || ''}`.trim() || profile.username;
    $('#pName').textContent = name;
    $('#pRole').textContent = `${role === 'ADMIN' ? 'Administrator' : 'Employee'} · ${profile.username}`;
    const avatar = $('#avatar');
    if (profile.profile_photo_url) { avatar.textContent = ''; avatar.style.backgroundImage = `url("${profile.profile_photo_url}")`; } else { avatar.style.backgroundImage = ''; avatar.textContent = fmt.initials(name); }
  }
  try {
    const profile = await api.get('/profile/');
    savedEmail = (profile.email || '').trim();
    fill(profile);
  } catch (error) { App.error(error); }

  if (role === 'ADMIN') {
    const companyForm = $('#companyForm');
    try {
      const company = await api.get('/company/');
      companyForm.elements.name.value = company.name || '';
      companyForm.elements.email.value = company.email || '';
      companyForm.elements.phone.value = company.phone || '';
      companyForm.elements.address.value = company.address || '';
    } catch (error) { App.error(error); }
    companyForm.addEventListener('submit', async event => {
      event.preventDefault();
      const box = $('#companyError'); box.hidden = true;
      const button = $('button[type=submit]', companyForm); button.disabled = true;
      try {
        const company = await api.put('/company/', Object.fromEntries(new FormData(companyForm)));
        const header = $('#companyName'); if (header) header.textContent = company.name;
        App.session.set({ ...App.session.get(), companyName: company.name });
        App.toast('Company details saved.');
      } catch (error) { box.textContent = error.message; box.hidden = false; }
      finally { button.disabled = false; }
    });
  }

  const saveProfile = async event => {
    event.preventDefault();
    errorBox.hidden = true;
    const originalButtonText = saveButton.textContent;
    saveButton.disabled = true;
    saveButton.textContent = 'Saving…';
    try {
      const profileData = Object.fromEntries(new FormData(form));
      const submittedEmail = (profileData.email || '').trim();
      delete profileData.email;
      if (submittedEmail !== savedEmail) {
        const emailInput = form.elements.email;
        emailInput.setCustomValidity(submittedEmail ? '' : 'Enter an email address before changing it.');
        if (!emailInput.reportValidity()) return;
        profileData.email = submittedEmail;
      }
      const updated = await api.put('/profile/', profileData);
      savedEmail = (updated.email || '').trim();
      fill(updated);
      const fullName = `${updated.first_name} ${updated.last_name}`.trim() || updated.username;
      $('#userName').textContent = fullName;
      App.session.set({ ...App.session.get(), fullName });
      App.toast('Profile saved.');
    } catch (error) {
      const fieldMessages = Object.values(error.fields || {}).flatMap(value => {
        if (Array.isArray(value)) return value;
        if (typeof value === 'string') return [value];
        return value && typeof value === 'object' ? Object.values(value).flat() : [];
      }).filter(Boolean);
      errorBox.textContent = fieldMessages.length ? fieldMessages.join(' ') : (error.message || 'Profile could not be saved. Please try again.');
      errorBox.hidden = false;
    } finally {
      saveButton.disabled = false;
      saveButton.textContent = originalButtonText;
    }
  };

  form.addEventListener('submit', saveProfile);
  saveButton.addEventListener('click', event => {
    event.preventDefault();
    saveProfile(event);
  });
  form.elements.email.addEventListener('input', event => event.target.setCustomValidity(''));
  saveButton.disabled = false;

  // This request fills a separate, read-only card. It must not gate profile editing.
  if (role === 'EMPLOYEE') {
    try {
      const { employee } = await api.get('/dashboard/employee/');
      if (employee) {
        $('#empCard').hidden = false;
        $('#empKv').innerHTML = html`<dt>Employee ID</dt><dd class="mono">${employee.employee_id}</dd><dt>Department</dt><dd>${employee.department}</dd><dt>Designation</dt><dd>${employee.designation}</dd><dt>Joined</dt><dd>${fmt.date(employee.joining_date)}</dd><dt>Status</dt><dd>${App.badge(employee.status)}</dd>`;
      }
    } catch (error) { /* employment card is optional */ }
  }

  $('#photo').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { App.toast('Profile photo must not exceed 2 MB.', 'error'); event.target.value = ''; return; }
    const data = new FormData(); data.append('profile_photo', file);
    try { fill(await api.upload('PUT', '/profile/', data)); App.toast('Photo updated.'); } catch (error) { App.error(error); }
    event.target.value = '';
  });
})();
