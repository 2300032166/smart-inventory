requireRole('manager');
initShell();

const isAdmin = getRole() === 'admin';
let allProducts = [];
let allSuppliers = [];
let editSku = null;
let deleteSku = null;
let currentPage = 1;
const itemsPerPage = 50;
let filteredItems = [];

// Show actions for both admin and manager
document.getElementById('action-col').style.display = '';

function populateSupplierDropdown() {
  const sel = document.getElementById('f-supplier');
  if (sel) {
    sel.innerHTML = '<option value="">— Select supplier —</option>' +
      allSuppliers.map(s => `<option value="${s.name}">${s.name}</option>`).join('');
  }
}

async function load() {
  const spinner = document.getElementById('inv-spinner');
  try {
    const [products, suppliers] = await Promise.all([
      apiFetch(`/inventory/products?_=${Date.now()}`),
      apiFetch('/inventory/suppliers')
    ]);
    if (!products || !suppliers) return;
    allProducts = products;
    allSuppliers = suppliers;
    spinner.style.display = 'none';
    applyFilters();
    populateSupplierDropdown();
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

function applyFilters() {
    const search = document.getElementById('search').value.toLowerCase();
    const statusFilter = document.getElementById('status-filter').value;
    const sortBy = document.getElementById('sort-by').value;

    filteredItems = allProducts.filter(p => {
        const matchSearch = !search || p.name?.toLowerCase().includes(search) || p.sku?.toLowerCase().includes(search);
        const matchStatus = !statusFilter || p.status === statusFilter;
        return matchSearch && matchStatus;
    });

    if (sortBy === 'days_asc') filteredItems.sort((a, b) => a.days_remaining - b.days_remaining);
    else if (sortBy === 'stock_desc') filteredItems.sort((a, b) => b.current_stock - a.current_stock);
    else if (sortBy === 'name_asc') filteredItems.sort((a, b) => a.name.localeCompare(b.name));

    currentPage = 1;
    render();
}

function render() {
  const totalPages = Math.ceil(filteredItems.length / itemsPerPage) || 1;
  if (currentPage > totalPages) currentPage = totalPages;

  document.getElementById('count-label').textContent = `${filteredItems.length} product${filteredItems.length !== 1 ? 's' : ''}`;
  document.getElementById('page-info').textContent = `Page ${currentPage} of ${totalPages}`;
  document.getElementById('btn-prev').disabled = currentPage === 1;
  document.getElementById('btn-next').disabled = currentPage === totalPages;

  const start = (currentPage - 1) * itemsPerPage;
  const displayItems = filteredItems.slice(start, start + itemsPerPage);

  const tbody = document.getElementById('inv-tbody');
  if (!filteredItems.length) { 
      tbody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--color-text-hint);padding:32px;">No products found</td></tr>'; 
      return; 
  }

  tbody.innerHTML = displayItems.map(p => `
    <tr class="${p.status === 'at_risk' ? 'row-at-risk' : ''}" data-sku="${p.sku}">
      <td><input type="checkbox" class="bulk-cb" data-sku="${p.sku}"></td>
      <td style="font-family:monospace;font-size:12px;">${p.sku}</td>
      <td style="font-weight:500;">${p.name}</td>
      <td>${p.category || '—'}</td>
      <td style="font-weight:600;">${p.current_stock} ${p.unit}</td>
      <td style="color:var(--color-primary);font-weight:600;">+${p.incoming_stock || 0}</td>
      <td style="font-weight:700;color:var(--color-text-primary);background:var(--color-bg-page);">${p.effective_stock || p.current_stock}</td>
      <td>${p.reorder_threshold}</td>
      <td class="days-remaining-cell">${p.days_remaining}</td>
      <td>${p.lead_time_days}d</td>
      <td>${p.supplier_name || '—'}</td>
      <td>${statusBadge(p.status)}</td>
      <td>
        <div style="display:flex;gap:6px;">
          <button class="btn btn-secondary btn-sm" data-action="update-stock" data-sku="${p.sku}" data-name="${p.name}" data-stock="${p.current_stock}">Update Stock</button>
          <button class="btn btn-secondary btn-sm" data-action="edit" data-sku="${p.sku}">Edit</button>
          <button class="btn btn-danger btn-sm" data-action="delete" data-sku="${p.sku}" data-name="${p.name}">Delete</button>
        </div>
      </td>
    </tr>`).join('');
}

function nextPage() {
    currentPage++;
    render();
}

function prevPage() {
    currentPage--;
    render();
}

async function manualUpdateStock(sku, name, current) {
  const newStock = prompt(`Update stock for ${name}:\nCurrent Stock: ${current}\nEnter new quantity:`, current);
  if (newStock === null || newStock === "" || isNaN(newStock)) return;

  try {
    const res = await apiFetch(`/inventory/products/${sku}/stock`, {
      method: 'PATCH',
      body: JSON.stringify({ current_stock: parseFloat(newStock) })
    });
    if (res) {
      showToast(`Updated ${name} stock to ${newStock}`, 'success');
      setTimeout(() => {
        window.location.reload();
      }, 300);
    }
  } catch (err) {
    console.error(err);
    showToast('Failed to update stock', 'danger');
  }
}

document.getElementById('search').addEventListener('input', applyFilters);
document.getElementById('status-filter').addEventListener('change', applyFilters);
document.getElementById('sort-by').addEventListener('change', applyFilters);
document.getElementById('btn-next').addEventListener('click', nextPage);
document.getElementById('btn-prev').addEventListener('click', prevPage);

// Event delegation for table buttons — avoids inline onclick escaping issues
document.getElementById('inv-tbody').addEventListener('click', e => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  const sku    = btn.dataset.sku;
  const name   = btn.dataset.name || '';
  const stock  = parseFloat(btn.dataset.stock || 0);
  if (action === 'update-stock') manualUpdateStock(sku, name, stock);
  else if (action === 'edit')    openEdit(sku);
  else if (action === 'delete')  openDelete(sku, name);
});

function openAdd() {
  editSku = null;
  document.getElementById('modal-title').textContent = 'Add Product';
  document.getElementById('product-form').reset();
  document.getElementById('f-sku').readOnly = false;
  document.getElementById('batch-date-section').style.display = 'none';
  hideMsg(document.getElementById('modal-msg'));
  openModal('product-modal');
}

function openEdit(sku) {
  const p = allProducts.find(x => x.sku === sku);
  if (!p) return;
  editSku = sku;
  document.getElementById('modal-title').textContent = 'Edit Product';
  document.getElementById('f-sku').value = p.sku;
  document.getElementById('f-sku').readOnly = true;
  document.getElementById('f-name').value = p.name;
  document.getElementById('f-unit').value = p.unit;
  document.getElementById('f-category').value = p.category || '';
  document.getElementById('f-stock').value = p.current_stock;
  document.getElementById('f-threshold').value = p.reorder_threshold;
  document.getElementById('f-lead').value = p.lead_time_days;
  document.getElementById('f-notes').value = p.notes || '';
  document.getElementById('f-supplier').value = p.supplier_name || '';
  // Hide batch date section in edit mode (editing stock via Update Stock button)
  document.getElementById('batch-date-section').style.display = 'none';
  hideMsg(document.getElementById('modal-msg'));
  openModal('product-modal');
}

function openDelete(sku, name) {
  deleteSku = sku;
  document.getElementById('delete-name').textContent = name;
  openModal('delete-modal');
}

document.getElementById('add-btn')?.addEventListener('click', openAdd);

document.getElementById('save-btn')?.addEventListener('click', async () => {
  const btn = document.getElementById('save-btn');
  const msg = document.getElementById('modal-msg');
  const stockVal = parseFloat(document.getElementById('f-stock').value) || 0;
  const body = {
    sku: document.getElementById('f-sku').value.trim(),
    name: document.getElementById('f-name').value.trim(),
    unit: document.getElementById('f-unit').value.trim() || 'units',
    category: document.getElementById('f-category').value.trim(),
    current_stock: stockVal,
    reorder_threshold: parseFloat(document.getElementById('f-threshold').value) || 0,
    lead_time_days: parseInt(document.getElementById('f-lead').value) || 7,
    notes: document.getElementById('f-notes').value.trim(),
    supplier_name: document.getElementById('f-supplier').value,
  };
  // Only send batch dates when adding a new product with stock > 0
  if (!editSku && stockVal > 0) {
    const mfgVal = document.getElementById('f-mfg-date').value;
    const expVal = document.getElementById('f-expiry-date').value;
    if (!expVal) { showError(msg, 'Please enter expiry date for the initial batch.'); return; }
    body.mfg_date = mfgVal || null;
    body.expiry_date = expVal;
  }
  if (!body.sku || !body.name) { showError(msg, 'SKU and name are required.'); return; }
  setLoading(btn, true, 'Save');
  try {
    if (editSku) {
      await apiFetch(`/inventory/products/${editSku}`, { method: 'PUT', body });
    } else {
      await apiFetch('/inventory/products', { method: 'POST', body });
    }
    closeModal('product-modal');
    load();
  } catch (err) { showError(msg, err.message); }
  finally { setLoading(btn, false, 'Save'); }
});

// Toggle batch-date-section visibility based on stock input (only when adding)
document.getElementById('f-stock')?.addEventListener('input', () => {
  if (editSku) return; // Don't show in edit mode
  const val = parseFloat(document.getElementById('f-stock').value) || 0;
  document.getElementById('batch-date-section').style.display = val > 0 ? 'block' : 'none';
});

document.getElementById('confirm-delete-btn')?.addEventListener('click', async () => {
  const btn = document.getElementById('confirm-delete-btn');
  setLoading(btn, true, 'Delete');
  try {
    await apiFetch(`/inventory/products/${deleteSku}`, { method: 'DELETE' });
    closeModal('delete-modal');
    load();
  } catch (err) { 
    showToast(err.message, 'danger'); 
  }
  finally { setLoading(btn, false, 'Delete'); }
});

// ── Bulk stock update ─────────────────────────────────────────────────────────

function getSelectedSkus() {
  return Array.from(document.querySelectorAll('.bulk-cb:checked')).map(cb => cb.dataset.sku);
}

function updateBulkButton() {
  const count = getSelectedSkus().length;
  document.getElementById('bulk-update-btn').style.display = count ? 'inline-block' : 'none';
  document.getElementById('bulk-update-btn').textContent = count ? `Bulk Update Stock (${count})` : 'Bulk Update Stock';
}

document.getElementById('select-all')?.addEventListener('change', e => {
  const checked = e.target.checked;
  document.querySelectorAll('.bulk-cb').forEach(cb => cb.checked = checked);
  updateBulkButton();
});

document.getElementById('inv-tbody')?.addEventListener('change', e => {
  if (e.target.classList.contains('bulk-cb')) updateBulkButton();
});

function buildBulkUpdateRows(skus) {
  const tbody = document.getElementById('bulk-update-rows');
  tbody.innerHTML = skus.map(sku => {
    const p = allProducts.find(x => x.sku === sku);
    if (!p) return '';
    const cur = p.current_stock;
    return `<tr data-sku="${sku}" data-current="${cur}">
      <td style="padding:10px 12px;border-bottom:1px solid #f1f5f9;font-weight:600;color:#1e293b;">${p.name}</td>
      <td style="padding:10px 12px;border-bottom:1px solid #f1f5f9;font-family:monospace;font-size:11px;color:#64748b;">${p.sku}</td>
      <td style="padding:10px 12px;border-bottom:1px solid #f1f5f9;text-align:right;color:#64748b;">${cur} ${p.unit}</td>
      <td style="padding:10px 12px;border-bottom:1px solid #f1f5f9;text-align:right;">
        <input type="number" class="bulk-new-qty" min="0" step="0.01" placeholder="${cur}"
          style="width:90px;padding:6px 8px;border:1.5px solid #e2e8f0;border-radius:6px;font-size:13px;text-align:right;outline:none;"
          oninput="updateChangeCell(this, ${cur}, '${p.unit}')">
      </td>
      <td class="bulk-change-cell" style="padding:10px 12px;border-bottom:1px solid #f1f5f9;text-align:right;font-weight:700;color:#94a3b8;">—</td>
    </tr>`;
  }).join('');
}

function updateChangeCell(input, current, unit) {
  const cell = input.closest('tr').querySelector('.bulk-change-cell');
  const val = parseFloat(input.value);
  if (isNaN(val)) { cell.textContent = '—'; cell.style.color = '#94a3b8'; return; }
  const diff = val - current;
  const sign = diff >= 0 ? '+' : '';
  cell.textContent = `${sign}${diff.toFixed(2)} ${unit}`;
  cell.style.color = diff > 0 ? '#16a34a' : diff < 0 ? '#dc2626' : '#94a3b8';
}

document.getElementById('bulk-update-btn')?.addEventListener('click', () => {
  const selected = getSelectedSkus();
  if (!selected.length) return;
  buildBulkUpdateRows(selected);
  document.getElementById('bulk-update-reason').value = '';
  hideMsg(document.getElementById('bulk-update-msg'));
  openModal('bulk-update-modal');
});

document.getElementById('bulk-update-submit')?.addEventListener('click', async () => {
  const rows = Array.from(document.querySelectorAll('#bulk-update-rows tr'));
  const msg = document.getElementById('bulk-update-msg');
  const btn = document.getElementById('bulk-update-submit');
  const reason = document.getElementById('bulk-update-reason').value.trim();

  const items = [];
  for (const row of rows) {
    const sku = row.dataset.sku;
    const input = row.querySelector('.bulk-new-qty');
    const val = input?.value.trim();
    if (!val) continue;
    const qty = parseFloat(val);
    if (isNaN(qty) || qty < 0) { showError(msg, `Invalid quantity for SKU ${sku}.`); return; }
    items.push({ sku, current_stock: qty });
  }

  if (!items.length) { showError(msg, 'Enter at least one new stock quantity.'); return; }

  setLoading(btn, true, 'Apply Changes');
  try {
    const res = await apiFetch('/admin/bulk-update-stock', {
      method: 'POST',
      body: { items, reason }
    });
    closeModal('bulk-update-modal');
    showToast(`Updated stock for ${res.count || items.length} product(s)`, 'success');
    setTimeout(() => window.location.reload(), 400);
  } catch (err) {
    showError(msg, err.message || 'Bulk update failed.');
  } finally {
    setLoading(btn, false, 'Apply Changes');
  }
});

load();
