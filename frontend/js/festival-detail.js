// Festival Inventory Planner — detail page logic
requireRole('manager');

const params = new URLSearchParams(location.search);
const festivalId = params.get('id');

let currentProducts = [];

document.addEventListener('DOMContentLoaded', async () => {
  if (!festivalId) {
    location.href = 'festivals.html';
    return;
  }
  await loadFestivalDetail();
  document.getElementById('p-search').addEventListener('input', renderProductTable);
  document.getElementById('p-status').addEventListener('change', renderProductTable);
  document.getElementById('p-priority').addEventListener('change', renderProductTable);
});

async function loadFestivalDetail() {
  try {
    const data = await apiFetch(`/festival-planner/festivals/${festivalId}`);
    FestivalDetails(data.festival);
    FestivalStats(data.stats);
    FestivalAlerts(data.alerts);
    currentProducts = data.products || [];
    renderProductTable();
  } catch (e) {
    document.getElementById('detail-main').innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Festival not found</div></div>`;
  }
}

// ── FestivalDetails component ───────────────────────────────────────────────
function statusBadgeClass(status) {
  if (status === 'Ongoing') return 'badge-success';
  if (status === 'Upcoming') return 'badge-normal';
  return 'badge-gray';
}

function FestivalDetails(f) {
  document.title = `${f.festival_name} — SIRA`;
  const daysBlock = f.status === 'Upcoming'
    ? `<div class="fd-stat"><div class="fd-stat-label">Days Remaining</div><div class="fd-stat-val">${f.days_remaining}</div></div>`
    : '';

  document.getElementById('detail-header').innerHTML = `
    <div class="fd-top">
      <span class="badge ${statusBadgeClass(f.status)}">${f.status}</span>
      <span class="badge badge-gray">${f.category}</span>
    </div>
    <div class="fd-name">${f.festival_name}</div>
    <div class="fd-desc">${f.description || ''}</div>
    <div class="fd-stats-row">
      <div class="fd-stat"><div class="fd-stat-label">Start Date</div><div class="fd-stat-val">${formatDate(f.start_date)}</div></div>
      <div class="fd-stat"><div class="fd-stat-label">End Date</div><div class="fd-stat-val">${formatDate(f.end_date)}</div></div>
      <div class="fd-stat"><div class="fd-stat-label">Duration</div><div class="fd-stat-val">${f.duration_days} day${f.duration_days === 1 ? '' : 's'}</div></div>
      ${daysBlock}
    </div>`;
}

// ── FestivalStats component ─────────────────────────────────────────────────
function FestivalStats(stats) {
  document.getElementById('stats-grid').innerHTML = `
    <div class="disc-kpi"><div class="kpi-label">Total Products</div><div class="kpi-val">${stats.total_products}</div></div>
    <div class="disc-kpi"><div class="kpi-label">In Stock</div><div class="kpi-val" style="color:#16a34a">${stats.in_stock}</div></div>
    <div class="disc-kpi"><div class="kpi-label">Low Stock</div><div class="kpi-val" style="color:#d97706">${stats.low_stock}</div></div>
    <div class="disc-kpi"><div class="kpi-label">Out of Stock</div><div class="kpi-val" style="color:#dc2626">${stats.out_of_stock}</div></div>
  `;
}

// ── FestivalAlerts component ────────────────────────────────────────────────
function alertIcon(type) {
  if (type === 'out_of_stock') return '⛔';
  if (type === 'low_stock') return '⚠️';
  if (type === 'expiring_before_festival') return '⚠️';
  return 'ℹ️';
}

function FestivalAlerts(alerts) {
  const box = document.getElementById('alerts-box');
  if (!alerts || alerts.length === 0) {
    box.innerHTML = `<div class="empty-state" style="padding:24px;"><div class="empty-icon">✅</div><div class="empty-title">No festival-specific alerts</div></div>`;
    return;
  }
  box.innerHTML = alerts.map(a => `
    <div class="fest-alert fest-alert-${a.severity}">
      <span class="fest-alert-icon">${alertIcon(a.type)}</span>
      <span>${a.message}</span>
    </div>
  `).join('');
}

// ── FestivalProductTable component ──────────────────────────────────────────
function stockStatusBadge(status) {
  const map = {
    'In Stock': 'badge-success',
    'Low Stock': 'badge-warning',
    'Out of Stock': 'badge-urgent',
    'Not Available': 'badge-gray',
  };
  return `<span class="badge ${map[status] || 'badge-gray'}">${status}</span>`;
}

function priorityBadge(priority) {
  const map = { High: 'priority-high', Medium: 'priority-medium', Low: 'priority-low' };
  return `<span class="priority-badge ${map[priority] || 'priority-medium'}">${priority}</span>`;
}

function FestivalProductTable(products) {
  const tbody = document.getElementById('product-tbody');
  if (products.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="empty-icon">📦</div><div class="empty-title">No products match your filters</div></div></td></tr>`;
    return;
  }
  tbody.innerHTML = products.map(p => `
    <tr>
      <td class="sku-tag">${p.product_id}</td>
      <td class="product-name">${p.product_name}</td>
      <td>${priorityBadge(p.priority)}</td>
      <td>${p.current_stock !== null ? p.current_stock : '—'}</td>
      <td>${stockStatusBadge(p.stock_status)}</td>
      <td>${p.supplier || '—'}</td>
      <td>${p.expiry_date ? formatDate(p.expiry_date) : '—'}</td>
    </tr>
  `).join('');
}

function renderProductTable() {
  const search = document.getElementById('p-search').value.trim().toLowerCase();
  const status = document.getElementById('p-status').value;
  const priority = document.getElementById('p-priority').value;

  const filtered = currentProducts.filter(p => {
    if (search && !p.product_name.toLowerCase().includes(search) && !p.product_id.toLowerCase().includes(search)) return false;
    if (status && p.stock_status !== status) return false;
    if (priority && p.priority !== priority) return false;
    return true;
  });

  document.getElementById('product-count').textContent = `${filtered.length} of ${currentProducts.length} products`;
  FestivalProductTable(filtered);
}
