requireRole('manager');
initShell();

let currentPage = 1;
let totalItems = 0;
const LIMIT = 20;
let allData = [];

async function load() {
  const spinner = document.getElementById('hist-spinner');
  spinner.style.display = 'flex';
  const sku = document.getElementById('search').value;
  const decision = document.getElementById('decision-filter').value;
  const dateFrom = document.getElementById('date-from').value;
  const dateTo = document.getElementById('date-to').value;

  let url = `/orders/history?page=${currentPage}&limit=${LIMIT}`;
  if (sku) url += `&sku=${encodeURIComponent(sku)}`;
  if (decision) url += `&decision=${decision}`;
  if (dateFrom) url += `&date_from=${dateFrom}`;
  if (dateTo) url += `&date_to=${dateTo}`;

  try {
    const data = await apiFetch(url);
    if (!data) return;
    totalItems = data.total;
    allData = data.items || [];
    spinner.style.display = 'none';
    render();
    renderPagination();
  } catch (err) {
    spinner.style.display = 'none';
  }
}

function render() {
  const tbody = document.getElementById('history-tbody');
  if (!allData.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--color-text-hint);padding:32px;">No records found</td></tr>'; return;
  }
  tbody.innerHTML = allData.map(o => `
    <tr>
      <td>${formatDateTime(o.timestamp)}</td>
      <td>${o.product_name || o.sku}</td>
      <td style="text-align:center;">${o.ai_suggested_qty}</td>
      <td style="text-align:center;">${o.actual_qty}</td>
      <td>${decisionBadge(o.decision)}</td>
      <td style="color:var(--color-text-secondary);">${o.reason_text || o.reason_category || '—'}</td>
      <td>${o.manager_name || '—'}</td>
    </tr>`).join('');
}

function renderPagination() {
  const totalPages = Math.ceil(totalItems / LIMIT);
  const p = document.getElementById('pagination');
  p.innerHTML = `
    <span class="page-info">Page ${currentPage} of ${totalPages || 1} (${totalItems} records)</span>
    <button class="btn btn-secondary btn-sm" onclick="changePage(-1)" ${currentPage <= 1 ? 'disabled' : ''}>← Prev</button>
    <button class="btn btn-secondary btn-sm" onclick="changePage(1)" ${currentPage >= totalPages ? 'disabled' : ''}>Next →</button>`;
}

function changePage(dir) { currentPage = Math.max(1, currentPage + dir); load(); }

document.getElementById('filter-btn').addEventListener('click', () => { currentPage = 1; load(); });

document.getElementById('export-btn').addEventListener('click', () => {
  exportToCsv(
    ['Date', 'Product', 'AI Suggested Qty', 'Actual Qty', 'Decision', 'Reason', 'Manager'],
    allData.map(o => [formatDateTime(o.timestamp), o.product_name || o.sku, o.ai_suggested_qty, o.actual_qty, o.decision, o.reason_text || o.reason_category || '', o.manager_name || '']),
    'order-history.csv'
  );
});

load();
