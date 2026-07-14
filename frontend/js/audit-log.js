requireRole('admin');
initShell();

let currentPage = 1;
let totalItems = 0;
const LIMIT = 50;
let allData = [];

async function load() {
  const spinner = document.getElementById('audit-spinner');
  spinner.style.display = 'flex';

  const dateFrom = document.getElementById('date-from').value;
  const dateTo = document.getElementById('date-to').value;
  const action = document.getElementById('action-filter').value;

  let url = `/admin/audit-log?page=${currentPage}&limit=${LIMIT}`;
  if (dateFrom) url += `&date_from=${dateFrom}`;
  if (dateTo) url += `&date_to=${dateTo}`;
  if (action) url += `&action_type=${encodeURIComponent(action)}`;

  try {
    const data = await apiFetch(url);
    if (!data) return;
    totalItems = data.total;
    allData = data.items || [];
    spinner.style.display = 'none';
    render();
    renderPagination();
  } catch { spinner.style.display = 'none'; }
}

function render() {
  const tbody = document.getElementById('audit-tbody');
  if (!allData.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--color-text-hint);padding:32px;">No audit log entries</td></tr>'; return;
  }
  tbody.innerHTML = allData.map(a => `
    <tr>
      <td style="white-space:nowrap;font-size:12px;">${formatDateTime(a.timestamp)}</td>
      <td>${a.user_name || '—'}</td>
      <td><span class="badge ${a.role==='admin'?'badge-warning':'badge-normal'}">${a.role || ''}</span></td>
      <td><span class="badge badge-gray" style="font-size:11px;">${a.action_type}</span></td>
      <td style="color:var(--color-text-secondary);">${a.description}</td>
      <td style="font-size:12px;font-family:monospace;">${a.ip_address || '—'}</td>
    </tr>`).join('');
}

function renderPagination() {
  const totalPages = Math.ceil(totalItems / LIMIT);
  const p = document.getElementById('pagination');
  p.innerHTML = `
    <span class="page-info">Page ${currentPage} of ${totalPages || 1} (${totalItems} entries)</span>
    <button class="btn btn-secondary btn-sm" onclick="changePage(-1)" ${currentPage <= 1 ? 'disabled' : ''}>← Prev</button>
    <button class="btn btn-secondary btn-sm" onclick="changePage(1)" ${currentPage >= totalPages ? 'disabled' : ''}>Next →</button>`;
}

function changePage(dir) { currentPage = Math.max(1, currentPage + dir); load(); }

document.getElementById('filter-btn').addEventListener('click', () => { currentPage = 1; load(); });

document.getElementById('export-btn').addEventListener('click', () => {
  exportToCsv(
    ['Timestamp', 'User', 'Role', 'Action Type', 'Description', 'IP Address'],
    allData.map(a => [formatDateTime(a.timestamp), a.user_name || '', a.role || '', a.action_type, a.description, a.ip_address || '']),
    'audit-log.csv'
  );
});

load();
