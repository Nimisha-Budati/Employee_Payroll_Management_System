const employeeNavigation = document.createElement('script'); employeeNavigation.src = 'employee-navigation.js'; document.head.appendChild(employeeNavigation);
const employeeNavigationCss = document.createElement('link'); employeeNavigationCss.rel = 'stylesheet'; employeeNavigationCss.href = 'employee-navigation.css'; document.head.appendChild(employeeNavigationCss);
const API_URL = 'http://127.0.0.1:8000/api';
if (localStorage.getItem('role') !== 'EMPLOYEE') location.href = 'index.html';

const message = document.getElementById('attendanceMessage');
let currentRecord = null;
let workTimer = null;

function showMessage(text, type) { message.textContent = text; message.className = `message ${type}`; }
function formatTime(value) { return value ? new Date(value).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '--'; }
function formatDuration(minutes) { const safeMinutes = Math.max(0, Math.floor(minutes || 0)); return `${Math.floor(safeMinutes / 60)}h ${String(safeMinutes % 60).padStart(2, '0')}m`; }
function distanceText(distance) { return distance === null || distance === undefined ? 'Awaiting check-in' : `${distance} m from office`; }
function setButtonState(record, enabled) { document.getElementById('checkInButton').disabled = !enabled || Boolean(record?.check_in_at); document.getElementById('checkOutButton').disabled = !enabled || !record?.check_in_at || Boolean(record?.check_out_at); }
function updateWorkedTime() { if (!currentRecord?.check_in_at) return; const end = currentRecord.check_out_at ? new Date(currentRecord.check_out_at) : new Date(); const minutes = (end - new Date(currentRecord.check_in_at)) / 60000; document.getElementById('workedTime').textContent = formatDuration(minutes); document.getElementById('workedNote').textContent = currentRecord.check_out_at ? 'Final recorded duration' : 'Live duration since check-in'; }

function renderStatus(data) {
  currentRecord = data.record;
  const record = currentRecord;
  document.getElementById('todayTitle').textContent = new Date(`${data.date}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' });
  document.getElementById('allowedRadius').textContent = data.attendance_enabled ? `${data.radius_meters} metres around your office` : 'Not configured by your administrator';
  document.getElementById('checkInTime').textContent = record?.check_in_at ? formatTime(record.check_in_at) : '--';
  document.getElementById('checkOutTime').textContent = record?.check_out_at ? formatTime(record.check_out_at) : '--';
  document.getElementById('checkInDistance').textContent = distanceText(record?.check_in_distance_meters);
  document.getElementById('checkOutDistance').textContent = record?.check_out_distance_meters === null || record?.check_out_distance_meters === undefined ? 'Awaiting check-out' : `${record.check_out_distance_meters} m from office`;
  const badge = document.getElementById('todayBadge');
  if (!data.attendance_enabled) { badge.textContent = 'Unavailable'; badge.className = 'state-badge'; document.getElementById('dayStatus').textContent = 'Attendance has not been enabled by your administrator.'; }
  else if (record?.check_out_at) { badge.textContent = 'Completed'; badge.className = 'state-badge enabled'; document.getElementById('dayStatus').textContent = 'Your attendance for today is complete.'; }
  else if (record?.check_in_at) { badge.textContent = 'Checked in'; badge.className = 'state-badge in-progress'; document.getElementById('dayStatus').textContent = 'You are checked in. Remember to check out when you finish.'; }
  else { badge.textContent = 'Not started'; badge.className = 'state-badge'; document.getElementById('dayStatus').textContent = 'Check in when you arrive at your workplace.'; }
  document.getElementById('attendanceHint').textContent = data.attendance_enabled ? 'Your GPS position is checked before every attendance action.' : 'Attendance has not been enabled by your administrator yet.';
  setButtonState(record, data.attendance_enabled);
  clearInterval(workTimer); updateWorkedTime(); if (record?.check_in_at && !record?.check_out_at) workTimer = setInterval(updateWorkedTime, 30000);
}

async function loadStatus() { const response = await fetch(`${API_URL}/attendance/status/`, { credentials: 'include' }); if (!response.ok) { showMessage('Unable to load attendance status.', 'error'); return; } renderStatus(await response.json()); }
function currentLocation() { return new Promise((resolve, reject) => { if (!navigator.geolocation) { reject(new Error('This browser does not support GPS location.')); return; } navigator.geolocation.getCurrentPosition(position => resolve(position.coords), () => reject(new Error('Location permission is required to mark attendance.')), { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }); }); }
async function markAttendance(action) { const button = action === 'check-in' ? document.getElementById('checkInButton') : document.getElementById('checkOutButton'); button.disabled = true; showMessage('Getting your GPS location...', 'success'); try { const coords = await currentLocation(); showMessage('Verifying your location...', 'success'); const response = await fetch(`${API_URL}/attendance/${action}/`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ latitude: coords.latitude, longitude: coords.longitude }) }); const data = await response.json().catch(() => null); if (!response.ok) throw new Error(data?.detail || 'Unable to mark attendance.'); showMessage(action === 'check-in' ? 'Check-in successful.' : 'Check-out successful.', 'success'); await Promise.all([loadStatus(), loadHistory()]); } catch (error) { showMessage(error.message, 'error'); await loadStatus(); } }
async function loadHistory() { const response = await fetch(`${API_URL}/attendance/history/?limit=14`, { credentials: 'include' }); const body = document.getElementById('historyTable'); if (!response.ok) { body.innerHTML = '<tr><td colspan="5">Unable to load attendance history.</td></tr>'; return; } const records = await response.json(); body.innerHTML = records.length ? records.map(record => `<tr><td>${new Date(`${record.date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</td><td>${formatTime(record.check_in_at)}</td><td>${formatTime(record.check_out_at)}</td><td>${record.worked_minutes === null ? (record.check_in_at ? 'In progress' : '--') : formatDuration(record.worked_minutes)}</td><td><span class="record-status ${record.status}">${record.status === 'CHECKED_OUT' ? 'Completed' : 'Checked in'}</span></td></tr>`).join('') : '<tr><td colspan="5">No attendance records yet.</td></tr>'; }
document.getElementById('checkInButton').addEventListener('click', () => markAttendance('check-in'));
document.getElementById('checkOutButton').addEventListener('click', () => markAttendance('check-out'));
document.getElementById('refreshHistory').addEventListener('click', loadHistory);
async function logoutUser() { await fetch(`${API_URL}/logout/`, { method: 'POST', credentials: 'include' }).catch(() => {}); localStorage.clear(); location.href = 'index.html'; }
loadStatus(); loadHistory();
