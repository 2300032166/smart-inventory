const API_BASE = 'http://127.0.0.1:8001/api';

// ── Auth helpers ──────────────────────────────────────────────────────────────

function getToken() { return localStorage.getItem('token'); }
function getRole()  { return localStorage.getItem('role'); }
function getName()  { return localStorage.getItem('name'); }
function getUserId(){ return localStorage.getItem('user_id'); }

function parseJwt(token) {
  try {
    return JSON.parse(atob(token.split('.')[1]));
  } catch { return null; }
}

function isTokenExpired(token) {
  const p = parseJwt(token);
  if (!p || !p.exp) return true;
  return Date.now() >= p.exp * 1000;
}

function checkAuth() {
  const token = getToken();
  if (!token || isTokenExpired(token)) {
    localStorage.clear();
    window.location.href = '../pages/login.html';
    return false;
  }
  return true;
}

function requireRole(required) {
  if (!checkAuth()) return false;
  const role = getRole();
  if (role !== required) {
    window.location.href = role === 'admin'
      ? '../pages/admin-home.html'
      : '../pages/dashboard.html';
    return false;
  }
  return true;
}

function logout() {
  localStorage.clear();
  window.location.href = '../pages/login.html';
}

// ── API fetch wrapper ─────────────────────────────────────────────────────────

async function apiFetch(url, options = {}) {
  const token = getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    options.body = JSON.stringify(options.body);
  }

  if (options.body instanceof FormData) {
    delete headers['Content-Type'];
  }

  const res = await fetch(API_BASE + url, { ...options, headers });

  if (res.status === 401) {
    localStorage.clear();
    window.location.href = '../pages/login.html';
    return null;
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const err = await res.json(); detail = err.detail || JSON.stringify(err); } catch {}
    throw new Error(detail);
  }

  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res.text();
}

// ── Topbar injection ──────────────────────────────────────────────────────────

function injectTopbar() {
  const topbar = document.getElementById('topbar');
  if (!topbar) return;

  const name = getName() || 'User';
  const role = getRole() || 'manager';
  const initials = name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);

  topbar.innerHTML = `
    <button class="hamburger" id="hamburger" aria-label="Menu">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
      </svg>
    </button>
    <a href="${role === 'admin' ? 'admin-home.html' : 'dashboard.html'}" class="topbar-logo">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
      </svg>
      Inventory Advisor
    </a>
    <span class="topbar-spacer"></span>
    <div class="topbar-actions">
      <a href="alerts.html" class="alert-bell" id="alert-bell-btn" title="Alerts">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>
        </svg>
        <span class="alert-badge" id="alert-count" style="display:none">0</span>
      </a>
      <div class="user-avatar">${initials}</div>
      <div class="user-info">
        <span class="user-name">${name}</span>
        <span class="user-role-badge ${role === 'admin' ? 'role-admin' : 'role-manager'}">${role === 'admin' ? 'Admin' : 'Manager'}</span>
      </div>
      <button class="btn-logout" onclick="logout()">Sign out</button>
    </div>
  `;

  document.getElementById('hamburger')?.addEventListener('click', () => {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    sidebar?.classList.toggle('open');
    if (overlay) overlay.style.display = sidebar?.classList.contains('open') ? 'block' : 'none';
  });

  loadAlertCount();
}

async function loadAlertCount() {
  try {
    const alerts = await apiFetch('/alerts');
    if (!alerts) return;
    const unread = alerts.filter(a => !a.is_read).length;
    const badge = document.getElementById('alert-count');
    if (badge) {
      badge.textContent = unread;
      badge.style.display = unread > 0 ? 'inline-flex' : 'none';
    }
  } catch {}
}

// ── Sidebar injection ─────────────────────────────────────────────────────────

function injectSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  const role = getRole();
  const currentPage = location.pathname.split('/').pop();

  const managerLinks = [
    { href: 'dashboard.html', label: 'Dashboard', icon: iconGrid },
    { href: 'brief.html', label: 'Daily Brief', icon: iconClipboard },
    { href: 'review.html', label: 'Review Orders', icon: iconCheck },
    { href: 'inventory.html', label: 'Inventory', icon: iconBox },
    { href: 'trends.html', label: 'Sales Trends', icon: iconTrend },
    { href: 'order-history.html', label: 'Order History', icon: iconHistory },
    { href: 'alerts.html', label: 'Alerts', icon: iconBell },
    { href: 'settings.html', label: 'Settings', icon: iconSettings },
  ];

  const adminLinks = [
    { href: 'admin-home.html', label: 'Overview', icon: iconGrid },
    { href: 'products.html', label: 'Products', icon: iconBox },
    { href: 'suppliers.html', label: 'Suppliers', icon: iconTruck },
    { href: 'data-upload.html', label: 'Data Upload', icon: iconUpload },
    { href: 'users.html', label: 'Users', icon: iconUsers },
    { href: 'ai-config.html', label: 'AI Config', icon: iconAI },
    { href: 'override-analytics.html', label: 'Analytics', icon: iconTrend },
    { href: 'audit-log.html', label: 'Audit Log', icon: iconHistory },
    { href: 'settings.html', label: 'Settings', icon: iconSettings },
  ];

  const links = role === 'admin' ? adminLinks : managerLinks;

  sidebar.innerHTML = links.map(l => `
    <a href="${l.href}" class="${currentPage === l.href ? 'active' : ''}">
      ${l.icon()}
      <span>${l.label}</span>
    </a>
  `).join('');
}

// ── SVG Icons ─────────────────────────────────────────────────────────────────

const svg = (d, extra = '') => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ${extra}>${d}</svg>`;

const iconGrid = () => svg('<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>');
const iconClipboard = () => svg('<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/>');
const iconCheck = () => svg('<polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>');
const iconBox = () => svg('<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>');
const iconTrend = () => svg('<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>');
const iconHistory = () => svg('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>');
const iconBell = () => svg('<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>');
const iconSettings = () => svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>');
const iconTruck = () => svg('<rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>');
const iconUpload = () => svg('<polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/>');
const iconUsers = () => svg('<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>');
const iconAI = () => svg('<circle cx="12" cy="12" r="3"/><path d="M12 2v2M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>');

// ── UI helpers ────────────────────────────────────────────────────────────────

function showError(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.className = 'alert-msg alert-msg-error show';
}

function showSuccess(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.className = 'alert-msg alert-msg-success show';
}

function hideMsg(el) {
  if (el) el.className = 'alert-msg';
}

function setLoading(btn, loading, defaultText) {
  if (!btn) return;
  btn.disabled = loading;
  btn.textContent = loading ? 'Loading…' : defaultText;
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch { return iso; }
}

function formatDateTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}

function timeAgo(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function urgencyBadge(urgency) {
  const map = { urgent: 'badge-urgent', normal: 'badge-normal', low: 'badge-low' };
  return `<span class="badge ${map[urgency] || 'badge-low'}">${urgency || 'low'}</span>`;
}

function decisionBadge(decision) {
  const map = { approved: 'badge-success', overridden: 'badge-warning', skipped: 'badge-urgent' };
  return `<span class="badge ${map[decision] || 'badge-gray'}">${decision || ''}</span>`;
}

// ── Modal helpers ─────────────────────────────────────────────────────────────

function openModal(id) {
  document.getElementById(id)?.classList.add('open');
}

function closeModal(id) {
  document.getElementById(id)?.classList.remove('open');
}

// ── Export CSV ────────────────────────────────────────────────────────────────

function exportToCsv(headers, rows, filename) {
  const lines = [headers.join(',')];
  rows.forEach(row => lines.push(row.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')));
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
}

// ── Init shell ────────────────────────────────────────────────────────────────

function initShell() {
  injectTopbar();
  injectSidebar();
}
