requireRole('admin');
initShell();

async function loadStats() {
  try {
    const [sysStats, users] = await Promise.all([
      apiFetch('/admin/system-stats'),
      apiFetch('/admin/users'),
    ]);

    if (sysStats) {
      document.getElementById('stat-products').textContent = sysStats.product_count;
      document.getElementById('stat-ai').textContent = sysStats.ai_model || 'Gemini 1.5 Flash';
    }

    if (users) document.getElementById('stat-users').textContent = users.filter(u => u.is_active).length;
  } catch {}
}

async function loadActivity() {
  const feed = document.getElementById('activity-feed');
  try {
    const data = await apiFetch('/admin/audit-log?page=1&limit=5');
    if (!data || !data.items.length) { feed.innerHTML = '<div style="font-size:13px;color:var(--color-text-hint);">No activity yet.</div>'; return; }

    const iconMap = {
      LOGIN: { icon: '🔐', bg: '#E6F1FB' },
      ORDER_APPROVED: { icon: '✓', bg: '#E1F5EE' },
      ORDER_OVERRIDDEN: { icon: '✏️', bg: '#FAEEDA' },
      ORDER_SKIPPED: { icon: '✕', bg: '#FCEBEB' },
      USER_CREATE: { icon: '👤', bg: '#E6F1FB' },
      AI_CONFIG_UPDATE: { icon: '🤖', bg: '#E6F1FB' },
    };

    feed.innerHTML = data.items.map(a => {
      const ico = iconMap[a.action_type] || { icon: '◉', bg: '#EDEDEC' };
      return `<div class="activity-item">
        <div class="activity-icon" style="background:${ico.bg};">${ico.icon}</div>
        <div class="activity-desc">${a.description}</div>
        <div class="activity-time">${timeAgo(a.timestamp)}</div>
      </div>`;
    }).join('');
  } catch {}
}

loadStats();
loadActivity();
