const API_URL = 'http://127.0.0.1:8000/api';
if (localStorage.getItem('role') !== 'ADMIN') location.href = 'index.html';

const message = document.getElementById('message');
const localDate = () => new Date().toLocaleDateString('en-CA');
const escapeHTML = value => { const node = document.createElement('div'); node.textContent = value || ''; return node.innerHTML; };
function showMessage(text, type) { message.textContent = text; message.className = `message ${type}`; }
function formatTime(value) { return value ? new Date(value).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '—'; }

async function loadSettings() {
  const response = await fetch(`${API_URL}/attendance/settings/`, { credentials: 'include' });
  if (!response.ok) { showMessage('Unable to load attendance settings.', 'error'); return; }
  const settings = await response.json();
  document.getElementById('latitude').value = settings.latitude ?? '';
  document.getElementById('longitude').value = settings.longitude ?? '';
  document.getElementById('radius').value = settings.radius_meters;
  document.getElementById('attendanceEnabled').checked = settings.is_enabled;
  const configured = settings.latitude !== null && settings.longitude !== null;
  const state = document.getElementById('locationState');
  state.textContent = settings.is_enabled && configured ? 'Attendance enabled' : configured ? 'Location saved, disabled' : 'Not configured';
  state.className = `state-badge ${settings.is_enabled && configured ? 'enabled' : ''}`;
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = { latitude: Number(document.getElementById('latitude').value), longitude: Number(document.getElementById('longitude').value), radius_meters: Number(document.getElementById('radius').value), is_enabled: document.getElementById('attendanceEnabled').checked };
  const response = await fetch(`${API_URL}/attendance/settings/`, { method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const data = await response.json().catch(() => null);
  if (!response.ok) { showMessage(data?.detail || Object.values(data || {}).flat().join(' ') || 'Unable to save settings.', 'error'); return; }
  showMessage('Attendance location settings saved.', 'success');
  loadSettings();
}

function useCurrentLocation() {
  if (!navigator.geolocation) { showMessage('This browser does not support location services.', 'error'); return; }
  showMessage('Getting your current location…', 'success');
  navigator.geolocation.getCurrentPosition(position => {
    document.getElementById('latitude').value = position.coords.latitude.toFixed(6);
    document.getElementById('longitude').value = position.coords.longitude.toFixed(6);
    showMessage('Current location added. Review it, then save settings.', 'success');
  }, () => showMessage('Location access was unavailable. Enter the office coordinates manually.', 'error'), { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
}

async function loadRecords() {
  const date = document.getElementById('attendanceDate').value;
  const response = await fetch(`${API_URL}/attendance/?date=${encodeURIComponent(date)}`, { credentials: 'include' });
  const table = document.getElementById('attendanceTable');
  if (!response.ok) { table.innerHTML = '<tr><td colspan="6">Unable to load attendance records.</td></tr>'; return; }
  const records = await response.json();
  document.getElementById('recordSummary').textContent = `${records.length} attendance record${records.length === 1 ? '' : 's'} for ${new Date(`${date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}.`;
  table.innerHTML = records.length ? records.map(record => `<tr><td><strong>${escapeHTML(record.employee_name)}</strong><br><small>${escapeHTML(record.employee_username)}</small></td><td>${record.date}</td><td>${formatTime(record.check_in_at)}</td><td>${formatTime(record.check_out_at)}</td><td><span class="record-status ${record.status}">${record.status === 'CHECKED_OUT' ? 'Completed' : 'Checked in'}</span></td><td>In: ${record.check_in_distance_meters ?? '—'} m<br>Out: ${record.check_out_distance_meters ?? '—'} m</td></tr>`).join('') : '<tr><td colspan="6">No attendance records for this date.</td></tr>';
}

document.getElementById('settingsForm').addEventListener('submit', saveSettings);
document.getElementById('useLocation').addEventListener('click', useCurrentLocation);
document.getElementById('refreshRecords').addEventListener('click', loadRecords);
document.getElementById('attendanceDate').addEventListener('change', loadRecords);
document.getElementById('attendanceDate').value = localDate();
async function logoutUser() { await fetch(`${API_URL}/logout/`, { method: 'POST', credentials: 'include' }).catch(() => {}); localStorage.clear(); location.href = 'index.html'; }
loadSettings(); loadRecords();
