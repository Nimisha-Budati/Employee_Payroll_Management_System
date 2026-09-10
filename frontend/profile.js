const API_URL = 'http://127.0.0.1:8000/api';
const expectedRole = document.body.dataset.role;
if (localStorage.getItem('role') !== expectedRole) location.href = 'index.html';
if (expectedRole === 'EMPLOYEE') { const employeeNavigation = document.createElement('script'); employeeNavigation.src = 'employee-navigation.js'; document.head.appendChild(employeeNavigation); const employeeNavigationCss = document.createElement('link'); employeeNavigationCss.rel = 'stylesheet'; employeeNavigationCss.href = 'employee-navigation.css'; document.head.appendChild(employeeNavigationCss); }
const message = document.getElementById('message');
function showMessage(text, type) { message.textContent = text; message.className = `message ${type}`; }
function setValue(id, value) { document.getElementById(id).value = value || ''; }
function fullName(profile) { return `${profile.first_name || ''} ${profile.last_name || ''}`.trim() || profile.username; }
async function loadProfile() {
  const response = await fetch(`${API_URL}/profile/`, { credentials: 'include' });
  const profile = await response.json();
  if (!response.ok) { showMessage('Unable to load your profile.', 'error'); return; }
  setValue('username', profile.username); setValue('role', profile.role === 'ADMIN' ? 'Administrator' : 'Employee'); setValue('firstName', profile.first_name); setValue('lastName', profile.last_name); setValue('email', profile.email); setValue('phone', profile.phone); setValue('address', profile.address);
  document.getElementById('profileName').textContent = fullName(profile); document.getElementById('profileEmail').textContent = profile.email || 'No email address'; document.getElementById('profileAvatar').textContent = fullName(profile).charAt(0).toUpperCase();
}
document.getElementById('profileForm').addEventListener('submit', async event => { event.preventDefault(); const payload = { first_name: document.getElementById('firstName').value.trim(), last_name: document.getElementById('lastName').value.trim(), email: document.getElementById('email').value.trim(), phone: document.getElementById('phone').value.trim(), address: document.getElementById('address').value.trim() }; const response = await fetch(`${API_URL}/profile/`, { method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); const data = await response.json(); if (!response.ok) { showMessage(Object.values(data).flat().join(' ') || 'Unable to save changes.', 'error'); return; } showMessage('Profile updated successfully.', 'success'); loadProfile(); });
async function logoutUser() { await fetch(`${API_URL}/logout/`, { method: 'POST', credentials: 'include' }).catch(() => {}); localStorage.clear(); location.href = 'index.html'; }
const profilePhotoInput = document.createElement('input');
profilePhotoInput.type = 'file';
profilePhotoInput.id = 'profilePhoto';
profilePhotoInput.accept = '.jpg,.jpeg,.png,image/jpeg,image/png';
profilePhotoInput.style.cssText = 'width:100%; margin:12px 0 5px; font-size:11px;';
const photoLabel = document.createElement('label');
photoLabel.htmlFor = 'profilePhoto';
photoLabel.textContent = 'Profile photo (JPG or PNG, max 2 MB)';
document.getElementById('profileAvatar').after(profilePhotoInput);
profilePhotoInput.before(photoLabel);

async function showProfilePhoto() {
  const response = await fetch(`${API_URL}/profile/`, { credentials: 'include' });
  const profile = await response.json();
  if (profile.profile_photo_url) {
    const avatar = document.getElementById('profileAvatar');
    avatar.textContent = '';
    avatar.style.backgroundImage = `url("${profile.profile_photo_url}")`;
    avatar.style.backgroundSize = 'cover';
    avatar.style.backgroundPosition = 'center';
  }
}

profilePhotoInput.addEventListener('change', async () => {
  if (!profilePhotoInput.files[0]) return;
  const formData = new FormData();
  formData.append('profile_photo', profilePhotoInput.files[0]);
  const response = await fetch(`${API_URL}/profile/`, { method: 'PUT', credentials: 'include', body: formData });
  const data = await response.json();
  if (!response.ok) { showMessage(Object.values(data).flat().join(' ') || 'Unable to upload the profile photo.', 'error'); return; }
  showMessage('Profile photo updated successfully.', 'success');
  showProfilePhoto();
});

loadProfile();
showProfilePhoto();
const passwordPanel = document.createElement('section');
passwordPanel.className = 'panel';
passwordPanel.innerHTML = '<h2 class="panel-title">Change password</h2><p class="panel-subtitle">Use your current password to set a new one.</p><form id="passwordForm"><div class="form-grid"><div><label for="currentPassword">Current password</label><input id="currentPassword" type="password" required></div><div><label for="newPassword">New password</label><input id="newPassword" type="password" required></div><div><label for="confirmNewPassword">Confirm new password</label><input id="confirmNewPassword" type="password" required></div></div><button class="primary-btn" type="submit">Change password</button></form>';
document.querySelector('.profile-layout').appendChild(passwordPanel);
document.getElementById('passwordForm').addEventListener('submit', async event => {
  event.preventDefault();
  const response = await fetch(`${API_URL}/password/change/`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ current_password: document.getElementById('currentPassword').value, new_password: document.getElementById('newPassword').value, confirm_password: document.getElementById('confirmNewPassword').value }) });
  const data = await response.json();
  showMessage(data.message || data.error || 'Unable to change password.', response.ok ? 'success' : 'error');
  if (response.ok) document.getElementById('passwordForm').reset();
});
