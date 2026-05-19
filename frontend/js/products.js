requireRole('admin');
initShell();

let allProducts = [];
let allSuppliers = [];
let editSku = null;
let deleteSku = null;

async function load() {
  const spinner = document.getElementById('prod-spinner');
  try {
    const [products, suppliers] = await Promise.all([
      apiFetch('/inventory/products'),
      apiFetch('/inventory/suppliers'),
    ]);
    if (!products || !suppliers) return;
    allProducts = products;
    allSuppliers = suppliers;
    spinner.style.display = 'none';
    render();
    populateSupplierDropdown();
  } catch { spinner.style.display = 'none'; }
}

function populateSupplierDropdown() {
  const sel = document.getElementById('f-supplier');
  sel.innerHTML = '<option value="">— Select supplier —</option>' +
    allSuppliers.map(s => `<option value="${s.name}">${s.name}</option>`).join('');
}

function render() {
  const search = document.getElementById('search').value.toLowerCase();
  const items = allProducts.filter(p =>
    !search || p.name?.toLowerCase().includes(search) || p.sku?.toLowerCase().includes(search)
  );
  document.getElementById('count-label').textContent = `${items.length} product${items.length !== 1 ? 's' : ''}`;
  const tbody = document.getElementById('products-tbody');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--color-text-hint);padding:32px;">No products found</td></tr>'; return;
  }
  tbody.innerHTML = items.map(p => `
    <tr>
      <td style="font-family:monospace;font-size:12px;">${p.sku}</td>
      <td style="font-weight:500;">${p.name}</td>
      <td>${p.category || '—'}</td>
      <td>${p.current_stock} ${p.unit}</td>
      <td>${p.reorder_threshold}</td>
      <td>${p.supplier_name || '—'}</td>
      <td>${p.lead_time_days}d</td>
      <td>
        <div style="display:flex;gap:6px;">
          <button class="btn btn-secondary btn-sm" onclick="openEdit('${p.sku}')">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="openDelete('${p.sku}','${p.name}')">Delete</button>
        </div>
      </td>
    </tr>`).join('');
}

function openAdd() {
  editSku = null;
  document.getElementById('modal-title').textContent = 'Add Product';
  document.getElementById('product-form').reset();
  document.getElementById('f-sku').readOnly = false;
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
  hideMsg(document.getElementById('modal-msg'));
  openModal('product-modal');
}

function openDelete(sku, name) {
  deleteSku = sku;
  document.getElementById('delete-name').textContent = name;
  openModal('delete-modal');
}

document.getElementById('add-btn').addEventListener('click', openAdd);

document.getElementById('save-btn').addEventListener('click', async () => {
  const btn = document.getElementById('save-btn');
  const msg = document.getElementById('modal-msg');
  const body = {
    sku: document.getElementById('f-sku').value.trim(),
    name: document.getElementById('f-name').value.trim(),
    unit: document.getElementById('f-unit').value.trim() || 'units',
    category: document.getElementById('f-category').value.trim(),
    current_stock: parseFloat(document.getElementById('f-stock').value) || 0,
    reorder_threshold: parseFloat(document.getElementById('f-threshold').value) || 0,
    lead_time_days: parseInt(document.getElementById('f-lead').value) || 7,
    notes: document.getElementById('f-notes').value.trim(),
    supplier_name: document.getElementById('f-supplier').value,
  };
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

document.getElementById('confirm-delete-btn').addEventListener('click', async () => {
  const btn = document.getElementById('confirm-delete-btn');
  setLoading(btn, true, 'Delete');
  try {
    await apiFetch(`/inventory/products/${deleteSku}`, { method: 'DELETE' });
    closeModal('delete-modal');
    load();
  } catch (err) { showError(document.getElementById('msg'), err.message); }
  finally { setLoading(btn, false, 'Delete'); }
});

document.getElementById('search').addEventListener('input', render);
load();
