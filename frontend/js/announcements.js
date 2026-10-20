(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  const user = await App.boot({ nav: 'announcements' });
  const admin = user.role === 'ADMIN';
  if (admin) { const b = $('#addBtn'); b.hidden = false; b.innerHTML = html`${icon('plus')} New announcement`; b.addEventListener('click', openForm); }

  async function load() {
    $('#feed').innerHTML = html`<div class="card"><div class="card-body"><span class="skeleton" style="width:40%"></span><br><span class="skeleton" style="width:90%"></span></div></div>`;
    try {
      const list = await api.get('/announcements/');
      $('#feed').innerHTML = list.length ? html`${list.map(a => html`<article class="card"><div class="card-header"><div><h2>${a.title}</h2><p>${a.author_username || 'Administrator'} · ${fmt.dateTime(a.created_at)}</p></div>${admin ? html`<button class="btn btn-sm btn-danger" type="button" data-del="${a.id}" aria-label="Delete ${a.title}">${icon('trash', 'icon-sm')} Delete</button>` : ''}</div><div class="card-body" style="white-space:pre-wrap">${a.message}</div></article>`)}`
        : html`<div class="card">${App.empty({ iconName: 'flag', title: 'No announcements yet', text: admin ? 'Publish one to notify every employee.' : 'Company news will appear here.' })}</div>`;
      $$('[data-del]', $('#feed')).forEach(b => b.addEventListener('click', async () => {
        const ok = await App.confirm({ title: 'Delete announcement?', message: 'It will be removed for everyone.', confirmLabel: 'Delete', danger: true });
        if (!ok) return;
        try { await api.delete(`/announcements/${b.dataset.del}/`); App.toast('Announcement deleted.'); load(); } catch (error) { App.error(error); }
      }));
    } catch (error) {
      $('#feed').innerHTML = html`<div class="card">${App.empty({ iconName: 'alert', title: 'Could not load announcements', text: error.message, action: html`<button class="btn btn-sm" id="retry">Try again</button>` })}</div>`;
      $('#retry').addEventListener('click', load);
    }
  }

  function openForm() {
    App.modal({
      title: 'New announcement', subtitle: 'Every employee will be notified.', submitLabel: 'Publish',
      body: html`<div class="form-grid">${field({ label: 'Title', name: 'title', required: true, span2: true, attrs: 'maxlength="150"' })}${field({ label: 'Message', name: 'message', type: 'textarea', required: true, span2: true })}</div>`,
      onSubmit: async (formData, ctx) => { await api.post('/announcements/', Object.fromEntries(formData)); ctx.close(); App.toast('Announcement published.'); load(); },
    });
  }
  load();
})();
