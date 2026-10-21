(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  const role = document.body.dataset.role;
  const admin = role === 'ADMIN';
  await App.boot({ role, nav: 'documents' });
  const params = new URLSearchParams(location.search);
  const state = { status: '', search: '', type: '', expiry: params.get('expiry') || '' };
  const cols = admin ? 7 : 6;
  const TYPES = [['IDENTITY', 'Identity proof'], ['ADDRESS', 'Address proof'], ['EDUCATION', 'Education certificate'], ['RESUME', 'Resume'], ['OTHER', 'Other']];
  const EXPIRY = [['', 'Any expiry'], ['EXPIRED', 'Expired'], ['EXPIRING', 'Expiring soon'], ['VALID', 'Valid'], ['TRACKED', 'Has an expiry date'], ['NONE', 'No expiry date']];
  const typeLabel = doc => (doc.document_type === 'OTHER' && doc.custom_document_type ? doc.custom_document_type : (TYPES.find(t => t[0] === doc.document_type) || [, doc.document_type])[1]);

  // Expiry is shown separately from the review status.
  function expiryCell(doc) {
    if (!doc.expiry_date) return html`<span class="subtle">No expiry</span>`;
    const days = doc.days_to_expiry;
    const note = days < 0 ? `${-days} day${days === -1 ? '' : 's'} ago` : days === 0 ? 'today' : `in ${days} day${days === 1 ? '' : 's'}`;
    return html`<div class="nowrap">${fmt.date(doc.expiry_date)}</div><div class="cell-sub">${App.badge(doc.expiry_status)} ${note}</div>`;
  }

  $('#head').innerHTML = html`<tr>${admin ? html`<th>Employee</th>` : ''}<th>Document</th><th>Type</th><th>Uploaded</th><th>Review status</th><th>Expiry</th><th class="right">Actions</th></tr>`;
  if (!admin) $('#actions').innerHTML = html`<button class="btn btn-primary" id="uploadBtn" type="button">${icon('upload')} Upload document</button>`;

  async function load() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(cols, 5);
    try {
      const list = await api.get('/documents/', { status: state.status, search: state.search, document_type: state.type, expiry: state.expiry });
      renderSummary(list);
      rows.innerHTML = list.length ? html`${list.map(doc => html`<tr>
        ${admin ? html`<td><div class="cell-main">${doc.employee_name}</div><div class="cell-sub">${doc.employee_username}</div></td>` : ''}
        <td><div class="cell-main">${doc.title}</div>${doc.review_note ? html`<div class="cell-sub">Note: ${doc.review_note}</div>` : ''}</td>
        <td>${typeLabel(doc)}</td><td class="nowrap">${fmt.date(doc.uploaded_at)}</td><td>${App.badge(doc.status)}</td><td>${expiryCell(doc)}</td>
        <td><div class="actions">
          <button class="btn btn-sm" type="button" data-open="${doc.id}">${icon('eye', 'icon-sm')} View</button>
          ${admin && doc.status === 'PENDING' ? html`<button class="btn btn-sm btn-success" type="button" data-verify="${doc.id}">Verify</button><button class="btn btn-sm btn-danger" type="button" data-reject="${doc.id}">Reject</button>` : ''}
          ${admin ? html`<button class="btn btn-sm" type="button" data-expiry="${doc.id}">${icon('calendar', 'icon-sm')} Expiry</button>` : ''}
          ${!admin && doc.status === 'PENDING' ? html`<button class="btn btn-sm btn-danger" type="button" data-delete="${doc.id}">${icon('trash', 'icon-sm')} Delete</button>` : ''}
        </div></td></tr>`)}` : App.emptyRow(cols, state.status || state.expiry || state.type || state.search
        ? { iconName: 'search', title: 'No documents match these filters', text: 'Try a different filter.' }
        : { iconName: 'file', title: admin ? 'No documents uploaded yet' : 'No documents yet', text: admin ? 'Uploaded documents will appear here for review.' : 'Upload your first document using the button above.' });
      const find = id => list.find(d => String(d.id) === id);
      $$('[data-open]', rows).forEach(b => b.addEventListener('click', () => App.openFile(`/documents/${b.dataset.open}/file/`)));
      $$('[data-verify]', rows).forEach(b => b.addEventListener('click', () => verify(find(b.dataset.verify))));
      $$('[data-reject]', rows).forEach(b => b.addEventListener('click', () => reject(find(b.dataset.reject))));
      $$('[data-expiry]', rows).forEach(b => b.addEventListener('click', () => setExpiry(find(b.dataset.expiry))));
      $$('[data-delete]', rows).forEach(b => b.addEventListener('click', () => remove(find(b.dataset.delete))));
    } catch (error) {
      rows.innerHTML = App.errorRow(cols, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
    }
  }

  function renderSummary(list) {
    const box = $('#expirySummary');
    if (!box) return;
    const expired = list.filter(d => d.expiry_status === 'EXPIRED').length;
    const expiring = list.filter(d => d.expiry_status === 'EXPIRING').length;
    box.hidden = !(expired || expiring) || Boolean(state.expiry);
    box.innerHTML = html`${icon('alert')}<span>${expired ? html`<strong>${expired}</strong> expired` : ''}${expired && expiring ? ' · ' : ''}${expiring ? html`<strong>${expiring}</strong> expiring soon` : ''}
      in this list. ${admin ? 'Employees and administrators are reminded automatically.' : 'Upload a renewed copy before it expires.'}</span>`;
  }

  async function verify(doc) {
    App.modal({
      title: 'Verify document', subtitle: `${doc.employee_name} · ${doc.title}`, submitLabel: 'Verify',
      body: html`<div class="form-grid">
        <p class="span-2 muted">Check the file, then verify it. If the document has a validity end (passport, visa, licence), record it so reminders are sent before it expires.</p>
        ${field({ label: 'Expiry date (optional)', name: 'expiry_date', type: 'date', value: doc.expiry_date || '', span2: true, hint: 'Leave empty if the document does not expire.' })}
      </div>`,
      onSubmit: async (formData, ctx) => {
        await api.put(`/documents/${doc.id}/review/`, { status: 'VERIFIED', expiry_date: formData.get('expiry_date') || null });
        ctx.close(); App.toast('Document verified.'); load();
      },
    });
  }
  function reject(doc) {
    App.modal({
      title: 'Reject document', subtitle: `${doc.employee_name} · ${doc.title}`, submitLabel: 'Reject document', submitVariant: 'danger',
      body: html`<div class="form-grid">${field({ label: 'Reason (shown to the employee)', name: 'review_note', type: 'textarea', required: true, span2: true, attrs: 'maxlength="300"' })}</div>`,
      onSubmit: async (formData, ctx) => { await api.put(`/documents/${doc.id}/review/`, { status: 'REJECTED', review_note: formData.get('review_note') }); ctx.close(); App.toast('Document rejected.'); load(); },
    });
  }
  function setExpiry(doc) {
    App.modal({
      title: 'Document expiry', subtitle: `${doc.employee_name} · ${doc.title}`, submitLabel: 'Save expiry',
      body: html`<div class="form-grid">
        ${field({ label: 'Expiry date', name: 'expiry_date', type: 'date', value: doc.expiry_date || '', span2: true, hint: 'Clear the date if the document does not expire. The review status is not changed.' })}
      </div>`,
      onSubmit: async (formData, ctx) => {
        await api.put(`/documents/${doc.id}/expiry/`, { expiry_date: formData.get('expiry_date') || null });
        ctx.close(); App.toast('Expiry date saved.'); load();
      },
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
        ${field({ label: 'Title', name: 'title', required: true, span2: true, placeholder: 'e.g. Passport', attrs: 'maxlength="100"' })}
        ${field({ label: 'Document type', name: 'document_type', type: 'select', options: TYPES, span2: true })}
        ${field({ label: 'Specify type', name: 'custom_document_type', hint: 'Only needed when the type is Other.', span2: true })}
        ${field({ label: 'Expiry date (optional)', name: 'expiry_date', type: 'date', span2: true, hint: 'For documents with a validity end, such as a passport or visa. You will be reminded before it expires.', attrs: `min="${App.todayISO()}"` })}
        ${field({ label: 'File', name: 'file', type: 'file', required: true, span2: true, hint: 'PDF, JPG or PNG, up to 5 MB.', attrs: 'accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"' })}
      </div>`,
      onSubmit: async (formData, ctx) => {
        const file = formData.get('file');
        if (file && file.size > 5 * 1024 * 1024) throw new Error('File size must not exceed 5 MB.');
        if (!formData.get('expiry_date')) formData.delete('expiry_date');
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
  const expiryFilter = $('#expiryFilter');
  expiryFilter.innerHTML = html`${EXPIRY.map(([value, label]) => html`<option value="${value}"${value === state.expiry ? App.raw(' selected') : ''}>${label}</option>`)}`;
  expiryFilter.addEventListener('change', e => { state.expiry = e.target.value; load(); });
  const search = $('#search');
  if (search) {
    if (admin) { $('#searchIcon').innerHTML = icon('search'); search.addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); load(); })); }
    else search.closest('.input-group').hidden = true;
  }
  load();
})();
