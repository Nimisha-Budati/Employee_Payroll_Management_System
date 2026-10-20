/* Applies the saved theme before first paint. Load this in <head>, before the stylesheet. */
(function () {
  'use strict';
  var KEY = 'payrollpro-theme';
  var root = document.documentElement;
  var COLORS = { light: '#f4f8f6', dark: '#0b1210' };

  function read() {
    try { var value = localStorage.getItem(KEY); return value === 'dark' || value === 'light' ? value : null; } catch (e) { return null; }
  }
  function apply(theme) {
    root.setAttribute('data-theme', theme);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', COLORS[theme]);
  }
  function announce(theme) {
    try { document.dispatchEvent(new CustomEvent('themechange', { detail: theme })); } catch (e) { /* old browser */ }
  }

  apply(read() || 'light');   // first-time visitors get Light Mode

  window.Theme = {
    get: function () { return root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'; },
    set: function (theme) {
      apply(theme);
      try { localStorage.setItem(KEY, theme); } catch (e) { /* storage blocked: theme still applies for this page */ }
      announce(theme);
    },
    toggle: function () { this.set(this.get() === 'dark' ? 'light' : 'dark'); },
  };
  // Keep other open tabs in sync.
  window.addEventListener('storage', function (event) {
    if (event.key === KEY) { var theme = read() || 'light'; apply(theme); announce(theme); }
  });
})();
