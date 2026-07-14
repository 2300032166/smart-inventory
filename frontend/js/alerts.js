checkAuth();
initShell();

async function load() {
  const spinner = document.getElementById('alerts-spinner');
  try {
    const data = await apiFetch('/alerts');
    if (!data) return;
    spinner.style.display = 'none';
    render(data);
  } catch { spinner.style.display = 'none'; }
}

const iconMap = {
  stockout: { icon: '⚠️', cls: 'alert-icon-danger' },
  info: { icon: '🔔', cls: 'alert-icon-info' },
  success: { icon: '✓', cls: 'alert-icon-success' },
  system: { icon: '⚙', cls: 'alert-icon-gray' },
};

function render(data) {
  const list = document.getElementById('alerts-list');
  if (!data.length) {
    list.innerHTML = '<div class="card" style="font-size:13px;color:var(--color-text-hint);padding:24px;">No alerts yet.</div>'; return;
  }
  list.innerHTML = data.map(a => {
    const ico = iconMap[a.type] || iconMap.system;
    return `
    <div class="alert-card ${a.is_read ? '' : 'unread'}" id="alert-${a.id}" onclick="markRead('${a.id}',this)">
      <div class="alert-icon ${ico.cls}">${ico.icon}</div>
      <div class="alert-content">
        <div class="alert-title">${a.title}</div>
        <div class="alert-message">${a.message}</div>
        <div class="alert-time">${timeAgo(a.created_at)}</div>
      </div>
    </div>`;
  }).join('');
}

async function markRead(id, el) {
  try {
    await apiFetch(`/alerts/${id}/read`, { method: 'POST' });
    el?.classList.remove('unread');
    loadAlertCount();
  } catch {}
}

document.getElementById('mark-all-btn').addEventListener('click', async () => {
  const msg = document.getElementById('msg');
  try {
    await apiFetch('/alerts/read-all', { method: 'POST' });
    document.querySelectorAll('.alert-card').forEach(c => c.classList.remove('unread'));
    showSuccess(msg, 'All alerts marked as read');
    loadAlertCount();
  } catch (err) { showError(msg, err.message); }
});

load();
