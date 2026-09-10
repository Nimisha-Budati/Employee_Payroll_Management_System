const API_URL = 'http://127.0.0.1:8000/api';
if (localStorage.getItem('role') !== 'ADMIN') window.location.href = 'index.html';
const rows = document.getElementById('employeeRows');
const message = document.getElementById('message');
const form = document.getElementById('employeeForm');
const escapeHTML = value => { const node = document.createElement('div'); node.textContent = value || ''; return node.innerHTML; };
function showMessage(text, type) { message.textContent = text; message.className = `alert alert-${type}`; }
async function loadEmployees() {
  const response = await fetch(`${API_URL}/employees/`, { credentials: 'include' });
  if (!response.ok) { showMessage('Access denied or employees could not be loaded.', 'error'); return; }
  const employees = await response.json();
  rows.innerHTML = employees.map(employee => `<tr><td>${escapeHTML(employee.employee_id)}</td><td>${escapeHTML(employee.username)}</td><td>${escapeHTML(employee.department)}</td><td>${escapeHTML(employee.status)}</td><td>${employee.status === 'ACTIVE' ? `<button class="danger-btn" onclick="deactivateEmployee(${employee.id})">Deactivate</button>` : 'Inactive'}</td></tr>`).join('');
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(form));
  const response = await fetch(`${API_URL}/employees/`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const data = await response.json();
  if (!response.ok) { showMessage(data.detail || 'Unable to add employee.', 'error'); return; }
  form.reset(); showMessage('Employee added.', 'success'); loadEmployees();
});
async function deactivateEmployee(id) {
  if (!window.confirm('Deactivate this employee account?')) return;
  const response = await fetch(`${API_URL}/employees/${id}/`, { method: 'DELETE', credentials: 'include' });
  showMessage(response.ok ? 'Employee deactivated.' : 'Unable to deactivate employee.', response.ok ? 'success' : 'error');
  if (response.ok) loadEmployees();
}
async function logoutUser() { await fetch(`${API_URL}/logout/`, { method: 'POST', credentials: 'include' }).catch(() => {}); localStorage.clear(); window.location.href = 'index.html'; }
loadEmployees();