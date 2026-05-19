checkAuth();
initShell();

const isAdmin = getRole() === 'admin';
let allProducts = [];

if (isAdmin) {
  document.getElementById('action-col').style.display = '';
}

async function load() {
  const spinner = document.getElementById('inv-spinner');
  try {
    const data = await apiFetch('/inventory/products');
    if (!data) return;
    allProducts = data;
    spinner.style.display = 'none';
    render();
  } catch (err) {
    spinner.style.display = 'none';
    console.error(err);
  }
}

function statusBadge(status) {
  const map = { at_risk: 'badge-urgent', ok: 'badge-success', overstocked: 'badge-warning' };
  const labels = { at_risk: 'At risk', ok: 'OK', overstocked: 'Overstocked' };
  return `<span class="badge ${map[status] || 'badge-low'}">${labels[status] || status}</span>`;
}

function render() {
  const search = document.getElementById('search').value.toLowerCase();
  const statusFilter = document.getElementById('status-filter').value;
  const sortBy = document.getElementById('sort-by').value;

  let items = allProducts.filter(p => {
    const matchSearch = !search || p.name?.toLowerCase().includes(search) || p.sku?.toLowerCase().includes(search);
    const matchStatus = !statusFilter || p.status === statusFilter;
    return matchSearch && matchStatus;
  });

  if (sortBy === 'days_asc') items.sort((a, b) => a.days_remaining - b.days_remaining);
  else if (sortBy === 'stock_desc') items.sort((a, b) => b.current_stock - a.current_stock);
  else if (sortBy === 'name_asc') items.sort((a, b) => a.name.localeCompare(b.name));

  document.getElementById('count-label').textContent = `${items.length} product${items.length !== 1 ? 's' : ''}`;

  const tbody = document.getElementById('inv-tbody');
  if (!items.length) { tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--color-text-hint);padding:32px;">No products found</td></tr>'; return; }

  tbody.innerHTML = items.map(p => `
    <tr class="${p.status === 'at_risk' ? 'row-at-risk' : ''}">
      <td style="font-family:monospace;font-size:12px;">${p.sku}</td>
      <td style="font-weight:500;">${p.name}</td>
      <td>${p.category || '—'}</td>
      <td>${p.current_stock} ${p.unit}</td>
      <td>${p.reorder_threshold}</td>
      <td class="days-remaining-cell">${p.days_remaining}</td>
      <td>${p.lead_time_days}d</td>
      <td>${p.supplier_name || '—'}</td>
      <td>${statusBadge(p.status)}</td>
      ${isAdmin ? `<td><div style="display:flex;gap:6px;">
        <button class="btn btn-secondary btn-sm" onclick="window.location.href='products.html'">Edit</button>
      </div></td>` : ''}
    </tr>`).join('');
}

document.getElementById('search').addEventListener('input', render);
document.getElementById('status-filter').addEventListener('change', render);
document.getElementById('sort-by').addEventListener('change', render);

load();
