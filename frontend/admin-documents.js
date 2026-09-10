const API = 'http://127.0.0.1:8000/api';
if (localStorage.getItem('role') !== 'ADMIN') location.href = 'index.html';
let documents = [];
const body = document.getElementById('documents');
const message = document.getElementById('message');
const filter = document.getElementById('filter');
const escapeHTML = value => { const element = document.createElement('div'); element.textContent = value || ''; return element.innerHTML; };
function showMessage(text, type) { message.textContent = text; message.className = `message ${type}`; }
function renderDocuments() {
  const visible = documents.filter(document => filter.value === 'ALL' || document.status === filter.value);
  body.innerHTML = visible.length ? visible.map(document => {
    const type = document.document_type === 'OTHER' ? document.custom_document_type : document.document_type;
    const actions = document.status === 'PENDING' ? `<button class="primary-btn" onclick="reviewDocument(${document.id}, 'VERIFIED')">Verify</button><button class="danger-btn" onclick="reviewDocument(${document.id}, 'REJECTED')">Reject</button>` : 'Reviewed';
    return `<tr><td>${escapeHTML(document.employee_username)}</td><td>${escapeHTML(document.title)}<br><small>${escapeHTML(type)}</small></td><td><a class="file" href="${encodeURI(document.file_url)}" target="_blank" rel="noopener">Open file</a></td><td><span class="status ${document.status}">${document.status}</span></td><td>${escapeHTML(document.review_note) || '—'}</td><td class="actions">${actions}</td></tr>`;
  }).join('') : '<tr><td colspan="6">No matching documents.</td></tr>';
}
async function loadDocuments() { const response = await fetch(`${API}/documents/`, { credentials: 'include' }); const data = await response.json(); if (!response.ok) { body.innerHTML = '<tr><td colspan="6">Unable to load documents.</td></tr>'; return; } documents = data; renderDocuments(); }
async function reviewDocument(id, status) { const review_note = status === 'REJECTED' ? prompt('Enter a rejection reason:') : (prompt('Optional verification note:') || ''); if (status === 'REJECTED' && !review_note) return; const response = await fetch(`${API}/documents/${id}/review/`, { method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, review_note }) }); const data = await response.json(); if (!response.ok) { showMessage(data.detail || 'Unable to update document.', 'error'); return; } showMessage(`Document ${status.toLowerCase()}.`, 'success'); loadDocuments(); }
async function logoutUser() { await fetch(`${API}/logout/`, { method: 'POST', credentials: 'include' }).catch(() => {}); localStorage.clear(); location.href = 'index.html'; }
filter.addEventListener('change', renderDocuments); loadDocuments();
