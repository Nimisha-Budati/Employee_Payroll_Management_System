const employeeNavigation = document.createElement('script'); employeeNavigation.src = 'employee-navigation.js'; document.head.appendChild(employeeNavigation);
const employeeNavigationCss = document.createElement('link'); employeeNavigationCss.rel = 'stylesheet'; employeeNavigationCss.href = 'employee-navigation.css'; document.head.appendChild(employeeNavigationCss);
const API = 'http://127.0.0.1:8000/api';
if (localStorage.getItem('role') !== 'EMPLOYEE') location.href = 'index.html';
const body = document.getElementById('documents');
const message = document.getElementById('message');
const documentType = document.getElementById('documentType');
const customTypeGroup = document.getElementById('customTypeGroup');
const customDocumentType = document.getElementById('customDocumentType');
const escapeHTML = value => { const element = document.createElement('div'); element.textContent = value || ''; return element.innerHTML; };

function showMessage(text, type) { message.textContent = text; message.className = `message ${type}`; }
function updateCustomTypeField() { const isOther = documentType.value === 'OTHER'; customTypeGroup.hidden = !isOther; customDocumentType.required = isOther; if (!isOther) customDocumentType.value = ''; }

async function loadDocuments() {
  const response = await fetch(`${API}/documents/`, { credentials: 'include' });
  const documents = await response.json();
  if (!response.ok) { body.innerHTML = '<tr><td colspan="5">Unable to load documents.</td></tr>'; return; }
  body.innerHTML = documents.length ? documents.map(document => {
    const type = document.document_type === 'OTHER' ? document.custom_document_type : document.document_type;
    return `<tr><td>${escapeHTML(document.title)}<br><small>${escapeHTML(type)}</small></td><td><a class="file" href="${encodeURI(document.file_url)}" target="_blank" rel="noopener">Open file</a></td><td><span class="status ${document.status}">${document.status}</span></td><td>${escapeHTML(document.review_note) || '—'}</td><td>${document.status === 'PENDING' ? `<button class="danger-btn" onclick="removeDocument(${document.id})">Delete</button>` : ''}</td></tr>`;
  }).join('') : '<tr><td colspan="5">No documents uploaded yet.</td></tr>';
}

documentType.addEventListener('change', updateCustomTypeField);
document.getElementById('uploadForm').addEventListener('submit', async event => {
  event.preventDefault();
  const form = new FormData();
  form.append('title', document.getElementById('title').value.trim());
  form.append('document_type', documentType.value);
  form.append('custom_document_type', customDocumentType.value.trim());
  form.append('file', document.getElementById('file').files[0]);
  const response = await fetch(`${API}/documents/`, { method: 'POST', credentials: 'include', body: form });
  const data = await response.json();
  if (!response.ok) { showMessage(Object.values(data).flat().join(' ') || 'Upload failed.', 'error'); return; }
  event.target.reset(); updateCustomTypeField(); showMessage('Document uploaded for review.', 'success'); loadDocuments();
});
async function removeDocument(id) { if (!confirm('Delete this pending document?')) return; const response = await fetch(`${API}/documents/${id}/`, { method: 'DELETE', credentials: 'include' }); if (response.ok) { showMessage('Document deleted.', 'success'); loadDocuments(); } else showMessage('Document could not be deleted.', 'error'); }
async function logoutUser() { await fetch(`${API}/logout/`, { method: 'POST', credentials: 'include' }).catch(() => {}); localStorage.clear(); location.href = 'index.html'; }
updateCustomTypeField(); loadDocuments();
