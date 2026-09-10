(function () {
  const render = () => {
    if (localStorage.getItem('role') !== 'EMPLOYEE') return;
    const page = location.pathname.split('/').pop() || 'employee-dashboard.html';
    const links = [['employee-dashboard.html', '⌂', 'Dashboard'], ['employee-leave.html', '◷', 'Leave Management'], ['employee-attendance.html', '⌖', 'My Attendance'], ['employee-wfh.html', '⌂', 'Work From Home'], ['employee-documents.html', '▤', 'My Documents'], ['employee-profile.html', '●', 'My Profile'], ['employee-holidays.html', '□', 'Holiday Calendar']];
    const nav = document.querySelector('.sidebar nav');
    if (nav) nav.innerHTML = links.map(([href, icon, label]) => `<a class="nav-item ${page === href ? 'active' : ''}" href="${href}"><span class="nav-icon">${icon}</span>${label}</a>`).join('');
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', render); else render();
})();
