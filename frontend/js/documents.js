(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  const role = document.body.dataset.role;
  const admin = role === 'ADMIN';
  await App.boot({ role, nav: 'documents' });
  const state = { status: '', search: '', type: '' };
  const cols = admin ? 6 : 5;
  const TYPES = [['IDENTITY', 'Identity proof'], ['ADDRESS', 'Address proof'], ['EDUCATION', 'Education certificate'], ['RESUME', 'Resume'], ['OTHER', 'Other']];
  const typeLabel = doc => (doc.document_type === 'OTHER' && doc.custom_document_type ? doc.custom_document_type : (TYPES.find(t => t[0] === doc.document_type) || [, doc.document_type])[1]);

  $('#head').innerHTML = html`<tr>${admin ? html`<th>Employee</th>` : ''}<th>Document</th><th>Type</th><th>Uploaded</th><th>Status</th><th class="right">Actions</th></tr>`;
  if (!admin) $('#actions').innerHTML = html`<button class="btn btn-primary" id="uploadBtn" type="button">${icon('upload')} Upload document</button>`;

  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(cols, 5);
    try {
      const list = await api.get('/documents/', { status: state.status, search: state.search, document_type: state.type });
      rows.innerHTML = list.length ? html`${list.map(doc => html`<tr>
        ${admin ? html`<td class="cell-main">${doc.employee_username}</td>` : ''}
        <td><div class="cell-main">${doc.title}</div>${doc.review_note ? html`<div class="cell-sub">Note: ${doc.review_note}</div>` : ''}</td>
        <td>${typeLabel(doc)}</td><td class="nowrap">${fmt.date(doc.uploaded_at)}</td><td>${App.badge(doc.status)}</td>
        <td><div class="actions">
          <button class="btn btn-sm" type="button" data-open="${doc.id}">${icon('eye', 'icon-sm')} View</button>
          ${admin && doc.status === 'PENDING' ? html`<button class="btn btn-sm btn-success" type="button" data-verify="${doc.id}">Verify</button><button class="btn btn-sm btn-danger" type="button" data-reject="${doc.id}">Reject</button>` : ''}
          ${!admin && doc.status === 'PENDING' ? html`<button class="btn btn-sm btn-danger" type="button" data-delete="${doc.id}">${icon('trash', 'icon-sm')} Delete</button>` : ''}
        </div></td></tr>`)}` : App.emptyRow(cols, state.status
        ? { iconName: 'search', title: 'No documents with this status' }
        : { iconName: 'file', title: admin ? 'No documents uploaded yet' : 'No documents yet', text: admin ? 'Uploaded documents will appear here for review.' : 'Upload your first document using the button above.' });
      const find = id => list.find(d => String(d.id) === id);
      $$('[data-open]', rows).forEach(b => b.addEventListener('click', () => App.openFile(`/documents/${b.dataset.open}/file/`)));
      $$('[data-verify]', rows).forEach(b => b.addEventListener('click', () => verify(find(b.dataset.verify))));
      $$('[data-reject]', rows).forEach(b => b.addEventListener('click', () => reject(find(b.dataset.reject))));
      $$('[data-delete]', rows).forEach(b => b.addEventListener('click', () => remove(find(b.dataset.delete))));
    } catch (error) {
      rows.innerHTML = App.errorRow(cols, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
    }
  }

  async function verify(doc) {
    const ok = await App.confirm({ title: 'Verify document?', message: `“${doc.title}” from ${doc.employee_username} will be marked verified.`, confirmLabel: 'Verify' });
    if (!ok) return;
    try { await api.put(`/documents/${doc.id}/review/`, { status: 'VERIFIED' }); App.toast('Document verified.'); load(); } catch (error) { App.error(error); }
  }
  function reject(doc) {
    App.modal({
      title: 'Reject document', subtitle: `${doc.employee_username} · ${doc.title}`, submitLabel: 'Reject document', submitVariant: 'danger',
      body: html`<div class="form-grid">${field({ label: 'Reason (shown to the employee)', name: 'review_note', type: 'textarea', required: true, span2: true, attrs: 'maxlength="300"' })}</div>`,
      onSubmit: async (formData, ctx) => { await api.put(`/documents/${doc.id}/review/`, { status: 'REJECTED', review_note: formData.get('review_note') }); ctx.close(); App.toast('Document rejected.'); load(); },
    });
  }
  async function remove(doc) {
    const ok = await App.confirm({ title: 'Delete document?', message: `“${doc.title}” will be permanently removed.`, confirmLabel: 'Delete', danger: true });
    if (!ok) return;
    try { await api.delete(`/documents/${doc.id}/`); App.toast('Document deleted.'); load(); } catch (error) { App.error(error); }
  }

  function upload() {
    App.modal({
      title: 'Upload document', submitLabel: 'Upload',
      body: html`<div class="form-grid">
        ${field({ label: 'Title', name: 'title', required: true, span2: true, placeholder: 'e.g. Passport', attrs: 'maxlength="150"' })}
        ${field({ label: 'Document type', name: 'document_type', type: 'select', options: TYPES, span2: true })}
        ${field({ label: 'Specify type', name: 'custom_document_type', hint: 'Only needed when the type is Other.', span2: true })}
        ${field({ label: 'File', name: 'file', type: 'file', required: true, span2: true, hint: 'PDF, JPG or PNG, up to 5 MB.', attrs: 'accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"' })}
      </div>`,
      onSubmit: async (formData, ctx) => {
        const file = formData.get('file');
        if (file && file.size > 5 * 1024 * 1024) throw new Error('File size must not exceed 5 MB.');
        await api.upload('POST', '/documents/', formData);
        ctx.close(); App.toast('Document uploaded for review.'); load();
      },
    });
  }

  const up = $('#uploadBtn'); if (up) up.addEventListener('click', upload);
  $('#statusFilter').addEventListener('change', e => { state.status = e.target.value; load(); });
  const typeFilter = $('#typeFilter');
  if (typeFilter) {
    typeFilter.innerHTML = html`<option value="">All types</option>${TYPES.map(([value, label]) => html`<option value="${value}">${label}</option>`)}`;
    typeFilter.addEventListener('change', e => { state.type = e.target.value; load(); });
  }
  const search = $('#search');
  if (search) {
    if (admin) { $('#searchIcon').innerHTML = icon('search'); search.addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); load(); })); }
    else search.closest('.input-group').hidden = true;
  }
  load();
})();
