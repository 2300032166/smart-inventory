requireRole('admin');
initShell();

async function loadStats() {
  try {
    const [products, users, uploadHistory, summary] = await Promise.all([
      apiFetch('/inventory/products'),
      apiFetch('/admin/users'),
      apiFetch('/admin/upload-history'),
      apiFetch('/sales/summary'),
    ]);

    if (products) document.getElementById('stat-products').textContent = products.length;
    if (users) document.getElementById('stat-users').textContent = users.filter(u => u.is_active).length;

    if (uploadHistory && uploadHistory.length > 0) {
      document.getElementById('stat-upload').textContent = formatDate(uploadHistory[0].date);
    } else {
      document.getElementById('stat-upload').textContent = 'Never';
    }

    const cfg = await apiFetch('/admin/ai-config');
    document.getElementById('stat-ai').textContent = cfg?.ai_provider === 'gemini'
      ? (cfg?.gemini_api_key ? '✓ Connected' : 'Not configured')
      : (cfg?.ai_provider === 'ollama' ? 'Ollama' : '—');
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
      DATA_UPLOAD: { icon: '📁', bg: '#E6F1FB' },
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
