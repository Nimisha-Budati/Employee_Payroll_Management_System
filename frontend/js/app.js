/* PayrollPro frontend core: API client, session, app shell and UI helpers.
   Loaded by every page. Page scripts call App.boot(...) and then use App.api / App.ui helpers. */
(function () {
  'use strict';

  const App = (window.App = {});

  /* ------------------------------------------------------------------ *
   * Configuration
   * ------------------------------------------------------------------ */
  const configured = window.APP_CONFIG && window.APP_CONFIG.apiUrl;
  // Frontend served by Django on :8000 uses a relative URL; a separate dev server (e.g. Live Server on :5500)
  // talks to Django on the same host, port 8000, so cookies stay "same-site".
  App.API_URL = configured || (location.port === '8000' ? '/api' : `${location.protocol}//${location.hostname}:8000/api`);
  const SESSION_KEY = 'pp_session';

  /* ------------------------------------------------------------------ *
   * Safe HTML templating: interpolated values are escaped unless wrapped with raw()
   * ------------------------------------------------------------------ */
  class Safe { constructor(value) { this.value = value; } toString() { return this.value; } }
  const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(value) {
    if (value === null || value === undefined || value === false) return '';
    if (value instanceof Safe) return value.value;
    if (Array.isArray(value)) return value.map(esc).join('');
    return String(value).replace(/[&<>"']/g, ch => ESCAPES[ch]);
  }
  App.raw = value => new Safe(String(value));
  App.esc = esc;
  App.html = function html(strings, ...values) {
    let out = strings[0];
    values.forEach((value, index) => { out += esc(value) + strings[index + 1]; });
    return new Safe(out);
  };
  const html = App.html;
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  App.$ = $; App.$$ = $$;

  /* ------------------------------------------------------------------ *
   * Icons (Feather-style, 24px grid)
   * ------------------------------------------------------------------ */
  const ICONS = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
    users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    home: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>',
    pin: '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
    chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    bell: '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/>',
    wallet: '<rect x="1" y="4" width="22" height="16" rx="2"/><path d="M1 10h22"/>',
    rupee: '<path d="M6 3h12M6 8h12M6 13l8.5 8M6 13h3a4.5 4.5 0 0 0 0-10"/>',
    receipt: '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1z"/><path d="M16 8H8M16 12H8M13 16H8"/>',
    chart: '<path d="M18 20V10M12 20V4M6 20v-6"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/>',
    check: '<path d="M20 6L9 17l-5-5"/>',
    checkCircle: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/>',
    x: '<path d="M18 6L6 18M6 6l12 12"/>',
    edit: '<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/>',
    trash: '<path d="M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
    menu: '<path d="M3 12h18M3 6h18M3 18h18"/>',
    left: '<path d="M15 18l-6-6 6-6"/>',
    right: '<path d="M9 18l6-6-6-6"/>',
    down: '<path d="M6 9l6 6 6-6"/>',
    eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19M14.12 14.12a3 3 0 1 1-4.24-4.24M1 1l22 22"/>',
    refresh: '<path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    briefcase: '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
    lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    send: '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    trending: '<path d="M23 6l-9.5 9.5-5-5L1 18"/><path d="M17 6h6v6"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>',
    moon: '<path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/>',
    layers: '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/>',
    moreVertical: '<circle cx="12" cy="5" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="19" r="1.6"/>',
    pinTack: '<path d="M9 4h6l-1 6 3 3H7l3-3-1-6z"/><path d="M12 13v8"/>',
    sparkle: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    timer: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5M9 2h6"/>',
    spreadsheet: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
    megaphone: '<path d="M3 11v2a1 1 0 0 0 1 1h3l5 4V6L7 10H4a1 1 0 0 0-1 1z"/><path d="M16 8a5 5 0 0 1 0 8M19 5a9 9 0 0 1 0 14"/>',
  };
  App.icon = function icon(name, extra = '') {
    return App.raw(`<svg class="icon ${extra}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICONS[name] || ''}</svg>`);
  };
  const icon = App.icon;

  /* Official multicolour Google "G" mark (fixed brand colours, identical in light and dark). */
  App.googleLogo = () => App.raw('<svg class="google-g" viewBox="0 0 48 48" aria-hidden="true" focusable="false"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>');

  /* Messages for the short error codes the backend puts in ?google_error= (no server text is ever rendered). */
  App.googleErrors = {
    cancelled: 'Google sign-in was cancelled.',
    google_denied: 'Google did not allow this sign-in. Please try again.',
    invalid_state: 'This sign-in attempt expired or was not started from this browser. Please try again.',
    google_unreachable: 'Could not reach Google. Check your connection and try again.',
    exchange_failed: 'Google rejected the sign-in request. Please try again.',
    invalid_token: 'Google returned an identity we could not verify. Please try again.',
    email_unverified: 'Your Google email address is not verified, so it cannot be used to sign in.',
    email_exists: 'An account with this email already exists. Sign in with your password, then connect Google from Settings.',
    no_admin_account: 'No administrator account is connected to this Google account. Sign in with your password and connect Google from Settings first.',
    wrong_role: 'This Google account is not registered for that login type. Switch between Employee and Administrator and try again.',
    inactive: 'This employee account is inactive.',
    no_profile: 'This account has no profile. Contact an administrator.',
    account_disabled: 'This account has been disabled.',
    google_in_use: 'That Google account is already connected to a different user.',
    already_linked: 'This account already has a Google account connected.',
    link_mismatch: 'You must stay signed in to the same account while connecting Google. Please try again.',
    throttled: 'Too many Google sign-in attempts. Please wait a few minutes and try again.',
    server_error: 'Something went wrong while signing in with Google. Please try again.',
  };
  App.googleErrorMessage = code => App.googleErrors[code] || App.googleErrors.server_error;

  /* Ask the server for Google's consent URL (CSRF-protected POST) and go there. */
  App.startGoogle = async function startGoogle(payload) {
    const { url } = await App.api.post('/auth/google/start/', payload, { auth: false });
    location.assign(url);
  };

  /* Theme toggle: Theme (js/theme.js) owns the state; this only renders and wires the button. */
  App.themeToggleHtml = (extraClass = '') => html`<button class="icon-btn theme-toggle ${extraClass}" type="button" data-theme-toggle>${icon('moon', 'i-moon')}${icon('sun', 'i-sun')}</button>`;
  App.bindThemeToggle = function bindThemeToggle(root = document) {
    const button = root.querySelector('[data-theme-toggle]');
    if (!button || !window.Theme) return;
    const sync = () => {
      const dark = window.Theme.get() === 'dark';
      button.setAttribute('aria-pressed', String(dark));
      button.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
      button.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
    };
    button.addEventListener('click', () => window.Theme.toggle());
    document.addEventListener('themechange', sync);
    sync();
  };

  /* ------------------------------------------------------------------ *
   * Formatting
   * ------------------------------------------------------------------ */
  const toDate = value => (value instanceof Date ? value : new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value));
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const fmt = (App.fmt = {
    months: MONTHS,
    money(value, { decimals = 2 } = {}) {
      const number = Number(value || 0);
      return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(number);
    },
    compactMoney(value) {
      const number = Number(value || 0);
      if (Math.abs(number) >= 10000000) return `₹${(number / 10000000).toFixed(1).replace(/\.0$/, '')}Cr`;
      if (Math.abs(number) >= 100000) return `₹${(number / 100000).toFixed(1).replace(/\.0$/, '')}L`;
      if (Math.abs(number) >= 1000) return `₹${(number / 1000).toFixed(1).replace(/\.0$/, '')}k`;
      return `₹${Math.round(number)}`;
    },
    number: value => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(Number(value || 0)),
    date(value) { return value ? toDate(value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'; },
    dateLong(value) { return value ? toDate(value).toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) : '—'; },
    dateTime(value) { return value ? toDate(value).toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'; },
    time(value) { return value ? toDate(value).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '—'; },
    iso(date) { return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`; },
    period(year, month) { return `${MONTHS[month - 1]} ${year}`; },
    duration(minutes) { const m = Math.max(0, Math.floor(minutes || 0)); return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`; },
    initials(name) { return (String(name || '?').trim().split(/\s+/).map(part => part[0]).slice(0, 2).join('') || '?').toUpperCase(); },
    relative(value) {
      const seconds = Math.round((Date.now() - toDate(value).getTime()) / 1000);
      if (seconds < 60) return 'just now';
      if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
      if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
      if (seconds < 86400 * 7) return `${Math.floor(seconds / 86400)} d ago`;
      return fmt.date(value);
    },
  });

  App.debounce = (fn, wait = 300) => { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); }; };
  App.todayISO = () => fmt.iso(new Date());

  const STATUS_BADGES = {
    PENDING: ['warning', 'Pending'], APPROVED: ['success', 'Approved'], REJECTED: ['danger', 'Rejected'], CANCELLED: [null, 'Cancelled'],
    ACTIVE: ['success', 'Active'], INACTIVE: [null, 'Inactive'], DRAFT: ['warning', 'Draft'], PAID: ['success', 'Paid'],
    VERIFIED: ['success', 'Verified'], CHECKED_IN: ['info', 'Checked in'], CHECKED_OUT: ['success', 'Completed'],
    FIXED: ['accent', 'Fixed'], TENTATIVE: ['warning', 'Tentative'],
    LATE: ['warning', 'Late'], ON_TIME: ['success', 'On time'], EXPIRED: [null, 'Expired'], LIVE: ['success', 'Active'],
  };
  App.badge = function badge(status, label) {
    const [tone, text] = STATUS_BADGES[status] || [null, status];
    return html`<span class="badge${tone ? ` badge-${tone}` : ''}">${label || text}</span>`;
  };

  /* ------------------------------------------------------------------ *
   * API client
   * ------------------------------------------------------------------ */
  class ApiError extends Error {
    constructor(message, status, data) { super(message); this.status = status; this.data = data; this.fields = fieldErrors(data); }
  }
  App.ApiError = ApiError;

  function fieldErrors(data) {
    const fields = {};
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      Object.entries(data).forEach(([key, value]) => {
        if (['detail', 'error', 'non_field_errors'].includes(key)) return;
        fields[key] = Array.isArray(value) ? value.join(' ') : (typeof value === 'string' ? value : '');
      });
    }
    return fields;
  }
  const LABELS = { employee_id: 'Employee ID', joining_date: 'Joining date', start_date: 'Start date', end_date: 'End date', leave_type: 'Leave type', effective_from: 'Effective from', pf_percent: 'PF %', lop_days: 'LOP days' };
  const humanize = key => LABELS[key] || key.replace(/_/g, ' ').replace(/^./, ch => ch.toUpperCase());
  function errorMessage(data, status) {
    if (typeof data === 'string' && data) return data;
    if (data && typeof data === 'object') {
      if (typeof data.detail === 'string') return data.detail;
      if (typeof data.error === 'string') return data.error;
      if (Array.isArray(data.non_field_errors)) return data.non_field_errors.join(' ');
      const parts = Object.entries(data).map(([key, value]) => {
        const text = Array.isArray(value) ? value.join(' ') : String(value);
        return `${humanize(key)}: ${text}`;
      });
      if (parts.length) return parts.join(' ');
    }
    if (status === 403) return 'You do not have permission to do that.';
    if (status === 404) return 'The requested item was not found.';
    if (status === 429) return 'Too many attempts. Please wait a moment and try again.';
    if (status >= 500) return 'The server ran into a problem. Please try again.';
    return 'Something went wrong. Please try again.';
  }

  let csrfToken = null;
  async function getCsrf(force = false) {
    if (csrfToken && !force) return csrfToken;
    const response = await fetch(`${App.API_URL}/csrf/`, { credentials: 'include' });
    csrfToken = (await response.json()).csrfToken;
    return csrfToken;
  }

  async function request(method, path, options = {}, retried = false) {
    const { body, form, params, raw, auth = true } = options;
    let url = `${App.API_URL}${path}`;
    if (params) {
      const query = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== '') query.set(key, value); });
      if ([...query].length) url += `?${query}`;
    }
    const headers = { Accept: 'application/json' };
    const init = { method, credentials: 'include', headers };
    try {
      if (!['GET', 'HEAD'].includes(method)) headers['X-CSRFToken'] = await getCsrf();
      if (form) init.body = form;
      else if (body !== undefined) { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
      var response = await fetch(url, init);
    } catch (error) {
      throw new ApiError('Unable to reach the server. Check your connection and try again.', 0, null);
    }

    const type = response.headers.get('content-type') || '';
    const data = response.status === 204 || raw || !type.includes('json') ? null : await response.json().catch(() => null);

    if (response.status === 403 && !retried && !['GET', 'HEAD'].includes(method) && data && /security token/i.test(data.error || data.detail || '')) {
      await getCsrf(true);
      return request(method, path, options, true);
    }
    if (!response.ok) {
      if (response.status === 401 && auth) App.session.expire();
      throw new ApiError(errorMessage(data, response.status), response.status, data);
    }
    return raw ? response : data;
  }

  App.api = {
    get: (path, params, options) => request('GET', path, { ...options, params }),
    post: (path, body, options) => request('POST', path, { ...options, body }),
    put: (path, body, options) => request('PUT', path, { ...options, body }),
    patch: (path, body, options) => request('PATCH', path, { ...options, body }),
    delete: (path, options) => request('DELETE', path, options),
    upload: (method, path, form) => request(method, path, { form }),
    resetCsrf() { csrfToken = null; },
    // Fetch a protected file (PDF/CSV/document) with the session cookie.
    async blob(path, params) {
      const response = await request('GET', path, { params, raw: true });
      return response.blob();
    },
  };

  /* ------------------------------------------------------------------ *
   * Session
   * ------------------------------------------------------------------ */
  App.session = {
    get() { try { return JSON.parse(localStorage.getItem(SESSION_KEY)); } catch (e) { return null; } },
    set(value) { try { localStorage.setItem(SESSION_KEY, JSON.stringify(value)); } catch (e) { /* storage unavailable */ } },
    clear() { try { localStorage.removeItem(SESSION_KEY); } catch (e) { /* storage unavailable */ } },
    expire() {
      App.session.clear();
      if (!/(^|\/)index\.html$|\/$/.test(location.pathname)) location.replace('index.html?expired=1');
    },
    home(role) { return role === 'ADMIN' ? 'admin-dashboard.html' : 'employee-dashboard.html'; },
    async logout() {
      try { await App.api.post('/logout/', undefined, { auth: false }); } catch (e) { /* already signed out */ }
      App.api.resetCsrf();
      App.session.clear();
      location.replace('index.html');
    },
  };

  /* ------------------------------------------------------------------ *
   * Toasts, modals, confirm
   * ------------------------------------------------------------------ */
  function toastRoot() {
    let root = $('.toasts');
    if (!root) {
      root = document.createElement('div');
      root.className = 'toasts';
      root.setAttribute('role', 'status');
      root.setAttribute('aria-live', 'polite');
      document.body.append(root);
    }
    return root;
  }
  App.toast = function toast(message, type = 'success') {
    const node = document.createElement('div');
    node.className = `toast toast-${type}`;
    node.innerHTML = html`${icon(type === 'error' ? 'alert' : 'checkCircle')}<span>${message}</span><button type="button" aria-label="Dismiss">${icon('x', 'icon-sm')}</button>`;
    const remove = () => node.remove();
    node.querySelector('button').addEventListener('click', remove);
    toastRoot().append(node);
    setTimeout(remove, type === 'error' ? 7000 : 4000);
  };
  App.error = (error, fallback = 'Something went wrong.') => App.toast(error && error.message ? error.message : fallback, 'error');

  /** Open a dialog with an optional form. onSubmit(formData, ctx) may throw ApiError to show errors. */
  App.modal = function modal({ title, subtitle = '', body = '', submitLabel = 'Save', submitVariant = 'primary', cancelLabel = 'Cancel', wide = false, onSubmit, onOpen, hideFooter = false }) {
    const dialog = document.createElement('dialog');
    dialog.className = `modal${wide ? ' wide' : ''}`;
    dialog.setAttribute('aria-labelledby', 'modal-title');
    dialog.innerHTML = html`
      <form method="dialog" novalidate>
        <div class="modal-head">
          <div><h2 id="modal-title">${title}</h2>${subtitle ? html`<p>${subtitle}</p>` : ''}</div>
          <button type="button" class="icon-btn" data-close aria-label="Close">${icon('x')}</button>
        </div>
        <div class="modal-body"><div class="alert alert-danger" data-error hidden></div>${body}</div>
        ${hideFooter ? '' : html`<div class="modal-foot">
          <button type="button" class="btn" data-close>${cancelLabel}</button>
          ${onSubmit ? html`<button type="submit" class="btn btn-${submitVariant}">${submitLabel}</button>` : ''}
        </div>`}
      </form>`;
    document.body.append(dialog);
    const form = $('form', dialog);
    const errorBox = $('[data-error]', dialog);
    const close = () => { dialog.close(); dialog.remove(); };
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
    $$('[data-close]', dialog).forEach(button => button.addEventListener('click', close));

    const ctx = {
      dialog, form, close,
      setError(message) { errorBox.textContent = message || ''; errorBox.hidden = !message; if (message) errorBox.scrollIntoView({ block: 'nearest' }); },
      setFieldErrors(fields = {}) {
        $$('[data-field-error]', dialog).forEach(node => node.remove());
        $$('[aria-invalid]', dialog).forEach(node => node.removeAttribute('aria-invalid'));
        Object.entries(fields).forEach(([name, message]) => {
          const control = form.elements[name];
          if (!control || !message) return;
          control.setAttribute('aria-invalid', 'true');
          const note = document.createElement('span');
          note.className = 'error-text';
          note.dataset.fieldError = '';
          note.textContent = message;
          (control.closest('.field') || control.parentNode).append(note);
        });
      },
    };
    if (onSubmit) {
      form.addEventListener('submit', async event => {
        event.preventDefault();
        ctx.setError(''); ctx.setFieldErrors({});
        if (!form.reportValidity()) return;
        const submit = $('button[type="submit"]', dialog);
        const original = submit.innerHTML;
        submit.disabled = true;
        submit.innerHTML = '<span class="spinner"></span> Working…';
        try {
          await onSubmit(new FormData(form), ctx);
        } catch (error) {
          if (error instanceof ApiError && Object.keys(error.fields).length) { ctx.setFieldErrors(error.fields); ctx.setError('Please correct the highlighted fields.'); }
          else ctx.setError(error.message || 'Something went wrong.');
        } finally {
          if (document.body.contains(dialog)) { submit.disabled = false; submit.innerHTML = original; }
        }
      });
    }
    dialog.showModal();
    const first = $('input:not([type=hidden]):not([readonly]), select, textarea', dialog);
    if (first) first.focus();
    if (onOpen) onOpen(ctx);
    return ctx;
  };

  App.confirm = function confirm({ title, message, confirmLabel = 'Confirm', danger = false }) {
    return new Promise(resolve => {
      let settled = false;
      const done = value => { if (!settled) { settled = true; resolve(value); } };
      const ctx = App.modal({
        title, body: html`<p class="muted">${message}</p>`, submitLabel: confirmLabel, submitVariant: danger ? 'danger' : 'primary',
        onSubmit: async (_, c) => { done(true); c.close(); },
      });
      ctx.dialog.addEventListener('close', () => done(false));
    });
  };

  /** Build a labelled form control. type: text | email | password | number | date | tel | select | textarea | checkbox */
  App.field = function field({ label, name, type = 'text', value = '', required = false, hint = '', options = [], placeholder = '', attrs = '', span2 = false, readonly = false }) {
    const cls = span2 ? 'field span-2' : 'field';
    const id = `f-${name}`;
    const common = `id="${esc(id)}" name="${esc(name)}"${required ? ' required' : ''}${readonly ? ' readonly' : ''} ${attrs}`;
    let control;
    if (type === 'select') {
      control = html`<select class="select" ${App.raw(common)}>${options.map(option => {
        const [optionValue, optionLabel] = Array.isArray(option) ? option : [option, option];
        return html`<option value="${optionValue}"${String(optionValue) === String(value) ? App.raw(' selected') : ''}>${optionLabel}</option>`;
      })}</select>`;
    } else if (type === 'textarea') {
      control = html`<textarea class="textarea" ${App.raw(common)} placeholder="${placeholder}">${value}</textarea>`;
    } else if (type === 'checkbox') {
      return html`<div class="${cls}"><label class="check"><input type="checkbox" ${App.raw(common)}${value ? App.raw(' checked') : ''}> ${label}</label>${hint ? html`<span class="hint">${hint}</span>` : ''}</div>`;
    } else {
      control = html`<input class="input" type="${type}" ${App.raw(common)} value="${value}" placeholder="${placeholder}">`;
    }
    return html`<div class="${cls}"><label for="${id}">${label}${required ? html` <span class="subtle">*</span>` : ''}</label>${control}${hint ? html`<span class="hint">${hint}</span>` : ''}</div>`;
  };

  /* ------------------------------------------------------------------ *
   * Table / list helpers
   * ------------------------------------------------------------------ */
  App.skeletonRows = (columns, rows = 5) => html`${Array.from({ length: rows }, () => html`<tr>${Array.from({ length: columns }, () => html`<td><span class="skeleton" style="width:${40 + Math.round(Math.random() * 50)}%"></span></td>`)}</tr>`)}`;
  App.empty = ({ iconName = 'inbox', title = 'Nothing here yet', text = '', action = '' }) =>
    html`<div class="empty"><div class="empty-icon">${icon(iconName, 'icon-lg')}</div><strong>${title}</strong>${text ? html`<p>${text}</p>` : ''}${action}</div>`;
  App.emptyRow = (columns, options) => html`<tr><td colspan="${columns}">${App.empty(options)}</td></tr>`;
  App.errorRow = (columns, message, retry = true) => html`<tr><td colspan="${columns}">${App.empty({ iconName: 'alert', title: 'Could not load data', text: message, action: retry ? html`<button class="btn btn-sm" data-retry>Try again</button>` : '' })}</td></tr>`;

  /** Render pagination controls into `container`. state = { page, count, pageSize }. */
  App.pager = function pager(container, { page, count, pageSize }, onChange) {
    const pages = Math.max(1, Math.ceil(count / pageSize));
    const from = count ? (page - 1) * pageSize + 1 : 0;
    const to = Math.min(count, page * pageSize);
    container.hidden = count === 0;
    container.innerHTML = html`<span>Showing ${from}–${to} of ${count}</span>
      <div class="pager-controls">
        <button class="btn btn-sm" data-page="${page - 1}" ${page <= 1 ? App.raw('disabled') : ''} aria-label="Previous page">${icon('left', 'icon-sm')} Prev</button>
        <span class="muted">Page ${page} of ${pages}</span>
        <button class="btn btn-sm" data-page="${page + 1}" ${page >= pages ? App.raw('disabled') : ''} aria-label="Next page">Next ${icon('right', 'icon-sm')}</button>
      </div>`;
    $$('[data-page]', container).forEach(button => button.addEventListener('click', () => onChange(Number(button.dataset.page))));
  };

  /** Download a protected file through fetch so the session cookie and errors are handled. */
  App.download = async function download(path, filename, params) {
    try {
      const blob = await App.api.blob(path, params);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = filename;
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (error) { App.error(error, 'Download failed.'); }
  };
  /** Open a protected file in a new tab. */
  App.openFile = async function openFile(path, params) {
    const tab = window.open('', '_blank');
    try {
      const blob = await App.api.blob(path, params);
      const url = URL.createObjectURL(blob);
      if (tab) tab.location.href = url; else location.href = url;
    } catch (error) { if (tab) tab.close(); App.error(error, 'Could not open the file.'); }
  };

  /* ------------------------------------------------------------------ *
   * Charts (dependency-free SVG / CSS)
   * ------------------------------------------------------------------ */
  App.barChart = function barChart(container, data, { format = fmt.compactMoney, label = 'Chart', muted = [] } = {}) {
    if (!data.length || data.every(item => !Number(item.value))) {
      container.innerHTML = App.empty({ iconName: 'chart', title: 'No data yet', text: 'Figures will appear here once there is activity to report.' });
      return;
    }
    const width = 600, height = 220, pad = { top: 12, right: 8, bottom: 28, left: 52 };
    const max = Math.max(...data.map(item => Number(item.value) || 0)) * 1.1 || 1;
    const innerW = width - pad.left - pad.right, innerH = height - pad.top - pad.bottom;
    const step = innerW / data.length, barW = Math.min(44, step * 0.58);
    const ticks = [0, 0.25, 0.5, 0.75, 1].map(fraction => fraction * max);
    container.innerHTML = html`<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${label}" preserveAspectRatio="xMidYMid meet">
      ${ticks.map(tick => { const y = pad.top + innerH - (tick / max) * innerH; return html`<line class="grid-line" x1="${pad.left}" x2="${width - pad.right}" y1="${y}" y2="${y}"/><text x="${pad.left - 8}" y="${y + 4}" text-anchor="end">${format(tick)}</text>`; })}
      ${data.map((item, index) => {
        const value = Number(item.value) || 0;
        const barH = (value / max) * innerH;
        const x = pad.left + step * index + (step - barW) / 2;
        const y = pad.top + innerH - barH;
        return html`<g><title>${item.label}: ${format(value)}</title><rect class="bar${muted.includes(index) ? ' bar-muted' : ''}" x="${x}" y="${y}" width="${barW}" height="${Math.max(barH, value ? 1 : 0)}" rx="4"/><text x="${x + barW / 2}" y="${height - 8}" text-anchor="middle">${item.label}</text></g>`;
      })}
    </svg>`;
  };
  App.hbars = function hbars(container, items, { format = value => value } = {}) {
    if (!items.length) { container.innerHTML = App.empty({ iconName: 'chart', title: 'No data yet' }); return; }
    const max = Math.max(...items.map(item => Number(item.value) || 0)) || 1;
    container.innerHTML = html`<div class="hbar">${items.map(item => html`<div class="hbar-row"><div class="hbar-label"><span>${item.label}</span><span>${format(item.value)}</span></div><div class="progress" role="progressbar" aria-valuenow="${item.value}" aria-valuemin="0" aria-valuemax="${max}"><span style="width:${Math.max(2, ((Number(item.value) || 0) / max) * 100)}%"></span></div></div>`)}</div>`;
  };

  /* ------------------------------------------------------------------ *
   * App shell
   * ------------------------------------------------------------------ */
  const NAV = {
    ADMIN: [
      ['Overview', [['dashboard', 'Dashboard', 'admin-dashboard.html', 'grid'], ['ai', 'AI assistant', 'ai-assistant.html', 'sparkle']]],
      ['People', [
        ['employees', 'Employees', 'employee-management.html', 'users'],
        ['attendance', 'Attendance', 'admin-attendance.html', 'pin'],
        ['shifts', 'Shifts', 'admin-shifts.html', 'clock'],
        ['overtime', 'Overtime', 'overtime.html', 'timer'],
        ['leave', 'Leave requests', 'admin-leave.html', 'calendar'],
        ['leavePolicy', 'Leave policy', 'admin-leave-policy.html', 'sliders'],
        ['wfh', 'Work from home', 'admin-wfh.html', 'home'],
        ['documents', 'Documents', 'admin-documents.html', 'file'],
      ]],
      ['Payroll', [
        ['payroll', 'Payroll runs', 'admin-payroll.html', 'wallet'],
        ['salary', 'Salary structures', 'admin-salary.html', 'rupee'],
        ['reports', 'Reports', 'admin-reports.html', 'chart'],
      ]],
      ['Company', [
        ['holidays', 'Holiday calendar', 'admin-holidays.html', 'calendar'],
        ['announcements', 'Announcements', 'announcements.html', 'flag'],
        ['chat', 'Messages', 'chat.html', 'chat'],
        ['audit', 'Audit log', 'admin-audit.html', 'activity'],
      ]],
    ],
    EMPLOYEE: [
      ['Overview', [['dashboard', 'Dashboard', 'employee-dashboard.html', 'grid'], ['ai', 'AI assistant', 'ai-assistant.html', 'sparkle']]],
      ['My work', [
        ['attendance', 'Attendance & shift', 'employee-attendance.html', 'pin'],
        ['overtime', 'Overtime', 'overtime.html', 'timer'],
        ['leave', 'Leave', 'employee-leave.html', 'calendar'],
        ['wfh', 'Work from home', 'employee-wfh.html', 'home'],
        ['documents', 'Documents', 'employee-documents.html', 'file'],
      ]],
      ['My pay', [['payslips', 'Payslips', 'employee-payslips.html', 'receipt']]],
      ['Company', [
        ['holidays', 'Holiday calendar', 'employee-holidays.html', 'calendar'],
        ['announcements', 'Announcements', 'announcements.html', 'flag'],
        ['chat', 'Messages', 'chat.html', 'chat'],
      ]],
    ],
  };

  function buildShell(session, current) {
    const role = session.role;
    const groups = NAV[role];
    let crumbGroup = '', crumbPage = current.title || '';
    const navHtml = groups.map(([group, items]) => html`<div class="nav-group"><div class="nav-title">${group}</div>${items.map(([id, label, href, iconName]) => {
      if (id === current.nav) { crumbGroup = group; crumbPage = crumbPage || label; }
      return html`<a class="nav-link" href="${href}"${id === current.nav ? App.raw(' aria-current="page"') : ''}>${icon(iconName)}<span>${label}</span></a>`;
    })}</div>`);
    const profileHref = role === 'ADMIN' ? 'admin-profile.html' : 'employee-profile.html';
    if (current.nav === 'profile') { crumbGroup = 'Account'; crumbPage = 'My profile'; }
    if (current.nav === 'settings') { crumbGroup = 'Account'; crumbPage = 'Settings'; }
    if (current.nav === 'notifications') { crumbGroup = 'Account'; crumbPage = 'Notifications'; }

    const content = $('#content');
    const app = document.createElement('div');
    app.className = 'app';
    app.innerHTML = html`
      <aside class="sidebar" id="sidebar" aria-label="Primary">
        <div class="brand"><div class="brand-mark">P</div><div class="brand-name">PayrollPro<small>${role === 'ADMIN' ? 'Administration' : 'Employee portal'}</small></div></div>
        <nav class="nav" aria-label="Main navigation">${navHtml}</nav>
        <div class="sidebar-foot">
          <a class="nav-link" href="${profileHref}"${current.nav === 'profile' ? App.raw(' aria-current="page"') : ''}>${icon('user')}<span>My profile</span></a>
          <a class="nav-link" href="settings.html"${current.nav === 'settings' ? App.raw(' aria-current="page"') : ''}>${icon('sliders')}<span>Settings</span></a>
        </div>
      </aside>
      <div class="scrim" id="scrim" hidden></div>
      <div class="main">
        <header class="topbar">
          <div class="topbar-left">
            <button class="icon-btn menu-toggle" id="menuToggle" type="button" aria-label="Open navigation" aria-controls="sidebar" aria-expanded="false">${icon('menu')}</button>
            <div class="crumbs">${crumbGroup ? html`<span>${crumbGroup}</span><span class="sep">/</span>` : ''}<strong>${crumbPage}</strong></div>
          </div>
          <div class="topbar-right">
            ${App.themeToggleHtml()}
            <a class="icon-btn" href="notifications.html" id="bell" aria-label="Notifications">${icon('bell')}<span class="dot-badge" id="bellBadge" hidden></span></a>
            <div class="user-menu">
              <button class="user-btn" id="userBtn" type="button" aria-haspopup="true" aria-expanded="false">
                <span class="avatar" id="userAvatar">${fmt.initials(session.fullName || session.username)}</span>
                <span class="user-meta"><strong class="truncate" id="userName">${session.fullName || session.username}</strong><span>${role === 'ADMIN' ? 'Administrator' : 'Employee'}</span></span>
                ${icon('down', 'icon-sm')}
              </button>
              <div class="menu-pop" id="userPop" hidden>
                <a href="${profileHref}">${icon('user')} My profile</a>
                <a href="settings.html">${icon('sliders')} Settings</a>
                <hr>
                <button type="button" id="logoutBtn">${icon('logout')} Sign out</button>
              </div>
            </div>
          </div>
        </header>
      </div>`;
    document.body.prepend(app);
    $('.main', app).append(content);
    content.classList.add('content');

    App.bindThemeToggle($('.topbar', app));
    const sidebar = $('#sidebar'), scrim = $('#scrim'), toggle = $('#menuToggle');
    const setNav = open => { sidebar.classList.toggle('open', open); scrim.hidden = !open; toggle.setAttribute('aria-expanded', String(open)); };
    toggle.addEventListener('click', () => setNav(!sidebar.classList.contains('open')));
    scrim.addEventListener('click', () => setNav(false));

    const pop = $('#userPop'), userBtn = $('#userBtn');
    const setPop = open => { pop.hidden = !open; userBtn.setAttribute('aria-expanded', String(open)); };
    userBtn.addEventListener('click', event => { event.stopPropagation(); setPop(pop.hidden); });
    document.addEventListener('click', event => { if (!pop.hidden && !pop.contains(event.target)) setPop(false); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') { setPop(false); setNav(false); } });
    $('#logoutBtn').addEventListener('click', () => App.session.logout());
  }

  async function refreshBell() {
    try {
      const { unread_count: unread } = await App.api.get('/notifications/');
      const badge = $('#bellBadge');
      if (!badge) return;
      badge.hidden = !unread;
      badge.textContent = unread > 9 ? '9+' : String(unread);
      $('#bell').setAttribute('aria-label', unread ? `Notifications, ${unread} unread` : 'Notifications');
    } catch (e) { /* the bell is non-critical */ }
  }
  App.refreshBell = refreshBell;

  /**
   * Guard the page, render the shell and load the signed-in profile.
   * options: { role: 'ADMIN'|'EMPLOYEE'|undefined (either), nav: id, title }
   */
  App.boot = async function boot(options = {}) {
    const stored = App.session.get();
    if (!stored || !stored.role) { location.replace('index.html'); return new Promise(() => {}); }
    if (options.role && stored.role !== options.role) { location.replace(App.session.home(stored.role)); return new Promise(() => {}); }

    buildShell(stored, options);
    let profile;
    try {
      profile = await App.api.get('/profile/');
    } catch (error) {
      if (error.status === 0) App.toast(error.message, 'error');
      else { App.session.expire(); return new Promise(() => {}); }
      profile = { username: stored.username, role: stored.role, first_name: '', last_name: '' };
    }
    if (profile.role !== stored.role) { App.session.clear(); location.replace('index.html'); return new Promise(() => {}); }
    const fullName = `${profile.first_name || ''} ${profile.last_name || ''}`.trim() || profile.username;
    App.session.set({ username: profile.username, role: profile.role, fullName });
    const name = $('#userName'); if (name) name.textContent = fullName;
    const avatar = $('#userAvatar');
    if (avatar) {
      if (profile.profile_photo_url) { avatar.textContent = ''; avatar.style.backgroundImage = `url("${profile.profile_photo_url}")`; }
      else avatar.textContent = fmt.initials(fullName);
    }
    refreshBell();
    setInterval(() => { if (document.visibilityState === 'visible') refreshBell(); }, 60000);
    App.user = { ...profile, fullName };
    return App.user;
  };

  /** Convenience for pages: show a loading state, run `load`, and show errors with a retry button. */
  App.guard = async function guard(container, load) {
    try { return await load(); } catch (error) {
      if (container) {
        container.innerHTML = App.empty({ iconName: 'alert', title: 'Could not load this page', text: error.message, action: html`<button class="btn btn-sm" onclick="location.reload()">Reload</button>` });
      } else App.error(error);
      return null;
    }
  };
})();
