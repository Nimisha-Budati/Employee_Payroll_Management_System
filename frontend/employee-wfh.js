for (const [tag, href] of [['script', 'employee-navigation.js'], ['link', 'employee-navigation.css'], ['link', 'employee-wfh.css']]) { const asset = document.createElement(tag); if (tag === 'script') asset.src = href; else { asset.rel = 'stylesheet'; asset.href = href; } document.head.appendChild(asset); }
const API_URL = 'http://127.0.0.1:8000/api';
if (localStorage.getItem('role') !== 'EMPLOYEE') location.href = 'index.html';
const message = document.getElementById('message');
const escapeHTML = value => { const element = document.createElement('div'); element.textContent = value || ''; return element.innerHTML; };
const showMessage = (text, type) => { message.textContent = text; message.className = `message ${type}`; };

async function loadRequests() {
  const response = await fetch(`${API_URL}/wfh/`, { credentials: 'include' });
  const body = document.getElementById('wfhTable');
  if (!response.ok) { body.innerHTML = '<tr><td colspan="5">Unable to load requests.</td></tr>'; return; }
  const requests = await response.json();
  document.getElementById('pendingCount').textContent = requests.filter(item => item.status === 'PENDING').length;
  document.getElementById('approvedCount').textContent = requests.filter(item => item.status === 'APPROVED').length;
  document.getElementById('daysCount').textContent = requests.reduce((total, item) => total + item.number_of_days, 0);
  body.innerHTML = requests.length ? requests.map(item => `<tr><td>${item.start_date}<br>to ${item.end_date}<br><small>${item.number_of_days} day(s)</small></td><td>${escapeHTML(item.reason)}</td><td><span class="status ${item.status}">${item.status}</span></td><td>${escapeHTML(item.admin_note) || '—'}</td><td>${item.status === 'PENDING' ? `<button class="action-btn reject" onclick="cancelRequest(${item.id})">Cancel</button>` : ''}</td></tr>`).join('') : '<tr><td colspan="5">No WFH requests yet.</td></tr>';
}

document.getElementById('wfhForm').addEventListener('submit', async event => {
  event.preventDefault();
  const payload = { start_date: document.getElementById('startDate').value, end_date: document.getElementById('endDate').value, reason: document.getElementById('reason').value.trim() };
  const response = await fetch(`${API_URL}/wfh/`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const data = await response.json();
  if (!response.ok) { showMessage(data.detail || Object.values(data).flat().join(' ') || 'Unable to submit request.', 'error'); return; }
  event.target.reset(); showMessage('WFH request submitted for approval.', 'success'); loadRequests();
});
async function cancelRequest(id) { if (!confirm('Cancel this pending WFH request?')) return; const response = await fetch(`${API_URL}/wfh/${id}/`, { method: 'DELETE', credentials: 'include' }); if (!response.ok) { showMessage('Unable to cancel request.', 'error'); return; } showMessage('WFH request cancelled.', 'success'); loadRequests(); }
async function logoutUser() { await fetch(`${API_URL}/logout/`, { method: 'POST', credentials: 'include' }).catch(() => {}); localStorage.clear(); location.href = 'index.html'; }
loadRequests();
