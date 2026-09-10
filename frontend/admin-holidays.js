const API_URL = 'http://127.0.0.1:8000/api';

if (localStorage.getItem('role') !== 'ADMIN') location.href = 'index.html';

let holidays = [];
let viewDate = new Date();
viewDate.setDate(1);

const form = document.getElementById('holidayForm');
const message = document.getElementById('message');
const holidayId = document.getElementById('holidayId');
const holidayName = document.getElementById('holidayName');
const holidayDate = document.getElementById('holidayDate');
const holidayType = document.getElementById('holidayType');
const holidayDescription = document.getElementById('holidayDescription');
const cancelEdit = document.getElementById('cancelEdit');

const dateKey = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const escapeHTML = value => {
  const element = document.createElement('div');
  element.textContent = value || '';
  return element.innerHTML;
};

function showMessage(text, type) {
  message.textContent = text;
  message.className = `message ${type}`;
}

function clearMessage() {
  message.textContent = '';
  message.className = 'message';
}

function formatDate(date) {
  return new Date(`${date}T00:00:00`).toLocaleDateString('en-IN', {
    day: 'numeric', month: 'short', year: 'numeric',
  });
}

function holidaysByDate() {
  return holidays.reduce((grouped, holiday) => {
    (grouped[holiday.date] ||= []).push(holiday);
    return grouped;
  }, {});
}

function renderCalendar() {
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = dateKey(new Date());
  const groupedHolidays = holidaysByDate();

  document.getElementById('monthTitle').textContent = viewDate.toLocaleString('en', {
    month: 'long', year: 'numeric',
  });

  const cells = [];
  for (let index = 0; index < firstDay; index += 1) cells.push('<div class="day blank" aria-hidden="true"></div>');
  for (let day = 1; day <= daysInMonth; day += 1) {
    const key = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const events = (groupedHolidays[key] || []).map(holiday =>
      `<div class="holiday ${holiday.holiday_type === 'TENTATIVE' ? 'tentative-holiday' : 'fixed-holiday'}" title="${escapeHTML(holiday.description || holiday.name)}">${escapeHTML(holiday.name)}</div>`,
    ).join('');
    cells.push(`<button class="day ${key === today ? 'today' : ''}" type="button" data-date="${key}" aria-label="Add holiday on ${key}"><span class="day-number">${day}</span>${events}</button>`);
  }
  document.getElementById('calendar').innerHTML = cells.join('');
}

function renderList() {
  const list = document.getElementById('holidayList');
  list.innerHTML = holidays.length ? holidays.map(holiday => `
    <article class="holiday-item">
      <strong>${escapeHTML(holiday.name)} <span class="status ${holiday.holiday_type}">${holiday.holiday_type}</span></strong>
      <time>${formatDate(holiday.date)}</time>
      ${holiday.description ? `<p>${escapeHTML(holiday.description)}</p>` : ''}
      <div class="actions">
        <button class="holiday-action edit-action" type="button" data-action="edit" data-id="${holiday.id}" aria-label="Edit ${escapeHTML(holiday.name)}"><span aria-hidden="true">&#9998;</span>Edit</button>
        <button class="holiday-action delete-action" type="button" data-action="delete" data-id="${holiday.id}" aria-label="Delete ${escapeHTML(holiday.name)}"><span aria-hidden="true">&#128465;</span>Delete</button>
      </div>
    </article>
  `).join('') : 'No holidays scheduled yet.';
}

async function loadHolidays() {
  try {
    const response = await fetch(`${API_URL}/holidays/`, { credentials: 'include' });
    if (!response.ok) throw new Error('Unable to load holidays.');
    holidays = await response.json();
    renderCalendar();
    renderList();
  } catch (error) {
    document.getElementById('holidayList').textContent = error.message;
    document.getElementById('calendar').innerHTML = '';
    showMessage(error.message, 'error');
  }
}

function resetForm() {
  form.reset();
  holidayId.value = '';
  document.getElementById('formTitle').textContent = 'Add a holiday';
  cancelEdit.classList.remove('visible');
}

function editHoliday(id) {
  const holiday = holidays.find(item => item.id === id);
  if (!holiday) return;
  holidayId.value = holiday.id;
  holidayName.value = holiday.name;
  holidayDate.value = holiday.date;
  holidayType.value = holiday.holiday_type;
  holidayDescription.value = holiday.description || '';
  document.getElementById('formTitle').textContent = 'Edit holiday';
  cancelEdit.classList.add('visible');
  clearMessage();
  holidayName.focus();
}

function responseMessage(data, fallback) {
  if (data && typeof data === 'object') {
    return data.detail || Object.values(data).flat().join(' ') || fallback;
  }
  return fallback;
}

async function saveHoliday(event) {
  event.preventDefault();
  const id = holidayId.value;
  const payload = {
    name: holidayName.value.trim(),
    date: holidayDate.value,
    holiday_type: holidayType.value,
    description: holidayDescription.value.trim(),
  };
  const response = await fetch(`${API_URL}/holidays/${id ? `${id}/` : ''}`, {
    method: id ? 'PUT' : 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    showMessage(responseMessage(data, 'Unable to save holiday.'), 'error');
    return;
  }
  showMessage(id ? 'Holiday updated successfully.' : 'Holiday added successfully.', 'success');
  viewDate = new Date(`${payload.date}T00:00:00`);
  viewDate.setDate(1);
  resetForm();
  await loadHolidays();
}

async function deleteHoliday(id) {
  const holiday = holidays.find(item => item.id === id);
  if (!holiday || !confirm(`Delete ${holiday.name} on ${formatDate(holiday.date)}?`)) return;
  const response = await fetch(`${API_URL}/holidays/${id}/`, {
    method: 'DELETE', credentials: 'include',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    showMessage(responseMessage(data, 'Unable to delete holiday.'), 'error');
    return;
  }
  if (String(holidayId.value) === String(id)) resetForm();
  showMessage('Holiday deleted successfully.', 'success');
  await loadHolidays();
}

document.getElementById('previousMonth').onclick = () => { viewDate.setMonth(viewDate.getMonth() - 1); renderCalendar(); };
document.getElementById('nextMonth').onclick = () => { viewDate.setMonth(viewDate.getMonth() + 1); renderCalendar(); };
document.getElementById('currentMonth').onclick = () => { viewDate = new Date(); viewDate.setDate(1); renderCalendar(); };
document.getElementById('calendar').addEventListener('click', event => {
  const day = event.target.closest('[data-date]');
  if (!day) return;
  resetForm();
  holidayDate.value = day.dataset.date;
  holidayName.focus();
});
document.getElementById('holidayList').addEventListener('click', event => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const id = Number(button.dataset.id);
  if (button.dataset.action === 'edit') editHoliday(id);
  if (button.dataset.action === 'delete') deleteHoliday(id);
});
form.addEventListener('submit', saveHoliday);
cancelEdit.addEventListener('click', () => { resetForm(); clearMessage(); });

async function logoutUser() {
  await fetch(`${API_URL}/logout/`, { method: 'POST', credentials: 'include' }).catch(() => {});
  localStorage.clear();
  location.href = 'index.html';
}

loadHolidays();
