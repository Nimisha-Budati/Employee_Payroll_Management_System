(async function () {
  'use strict';
  const { $, html, icon, fmt, api } = App;
  const role = document.body.dataset.role;
  await App.boot({ role, nav: 'profile' });
  $('label[for=photo]').innerHTML = html`${icon('upload', 'icon-sm')} Change photo`;
  const form = $('#form'), errorBox = $('#formError');

  function fill(profile) {
    ['first_name', 'last_name', 'email', 'phone', 'address'].forEach(name => { form.elements[name].value = profile[name] || ''; });
    const name = `${profile.first_name || ''} ${profile.last_name || ''}`.trim() || profile.username;
    $('#pName').textContent = name;
    $('#pRole').textContent = `${role === 'ADMIN' ? 'Administrator' : 'Employee'} · ${profile.username}`;
    const avatar = $('#avatar');
    if (profile.profile_photo_url) { avatar.textContent = ''; avatar.style.backgroundImage = `url("${profile.profile_photo_url}")`; } else { avatar.style.backgroundImage = ''; avatar.textContent = fmt.initials(name); }
  }
  try { fill(await api.get('/profile/')); } catch (error) { App.error(error); }

  if (role === 'EMPLOYEE') {
    try {
      const { employee } = await api.get('/dashboard/employee/');
      if (employee) {
        $('#empCard').hidden = false;
        $('#empKv').innerHTML = html`<dt>Employee ID</dt><dd class="mono">${employee.employee_id}</dd><dt>Department</dt><dd>${employee.department}</dd><dt>Designation</dt><dd>${employee.designation}</dd><dt>Joined</dt><dd>${fmt.date(employee.joining_date)}</dd><dt>Status</dt><dd>${App.badge(employee.status)}</dd>`;
      }
    } catch (error) { /* employment card is optional */ }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    errorBox.hidden = true;
    const button = $('button[type=submit]', form); button.disabled = true;
    try {
      const updated = await api.put('/profile/', Object.fromEntries(new FormData(form)));
      fill(updated);
      const fullName = `${updated.first_name} ${updated.last_name}`.trim() || updated.username;
      $('#userName').textContent = fullName;
      App.session.set({ ...App.session.get(), fullName });
      App.toast('Profile saved.');
    } catch (error) {
      errorBox.textContent = error.fields && Object.keys(error.fields).length ? Object.values(error.fields).join(' ') : error.message;
      errorBox.hidden = false;
    } finally { button.disabled = false; }
  });

  $('#photo').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { App.toast('Profile photo must not exceed 2 MB.', 'error'); event.target.value = ''; return; }
    const data = new FormData(); data.append('profile_photo', file);
    try { fill(await api.upload('PUT', '/profile/', data)); App.toast('Photo updated.'); } catch (error) { App.error(error); }
    event.target.value = '';
  });
})();
