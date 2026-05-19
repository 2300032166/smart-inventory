requireRole('admin');
initShell();

let allSuppliers = [];
let editId = null;
let deleteId = null;

async function load() {
  const spinner = document.getElementById('sup-spinner');
  try {
    const data = await apiFetch('/inventory/suppliers');
    if (!data) return;
    allSuppliers = data;
    spinner.style.display = 'none';
    render();
  } catch { spinner.style.display = 'none'; }
}

function render() {
  const tbody = document.getElementById('suppliers-tbody');
  if (!allSuppliers.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--color-text-hint);padding:32px;">No suppliers found</td></tr>'; return;
  }
  tbody.innerHTML = allSuppliers.map(s => `
    <tr>
      <td style="font-weight:500;">${s.name}</td>
      <td>${s.contact_person || '—'}</td>
      <td>${s.phone || '—'}</td>
      <td><a href="mailto:${s.email}" style="color:var(--color-primary);">${s.email || '—'}</a></td>
      <td>${s.default_lead_time_days}d</td>
      <td style="font-size:12px;">${s.delivery_schedule || '—'}</td>
      <td>${s.products_count ?? 0}</td>
      <td>
        <div style="display:flex;gap:6px;">
          <button class="btn btn-secondary btn-sm" onclick="openEdit('${s.supplier_id}')">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="openDelete('${s.supplier_id}','${s.name}')">Delete</button>
        </div>
      </td>
    </tr>`).join('');
}

function openAdd() {
  editId = null;
  document.getElementById('modal-title').textContent = 'Add Supplier';
  document.getElementById('supplier-form').reset();
  document.getElementById('f-id').readOnly = false;
  hideMsg(document.getElementById('modal-msg'));
  openModal('supplier-modal');
}

function openEdit(id) {
  const s = allSuppliers.find(x => x.supplier_id === id);
  if (!s) return;
  editId = id;
  document.getElementById('modal-title').textContent = 'Edit Supplier';
  document.getElementById('f-id').value = s.supplier_id;
  document.getElementById('f-id').readOnly = true;
  document.getElementById('f-name').value = s.name;
  document.getElementById('f-contact').value = s.contact_person || '';
  document.getElementById('f-phone').value = s.phone || '';
  document.getElementById('f-email').value = s.email || '';
  document.getElementById('f-lead').value = s.default_lead_time_days;
  document.getElementById('f-schedule').value = s.delivery_schedule || '';
  document.getElementById('f-notes').value = s.notes || '';
  hideMsg(document.getElementById('modal-msg'));
  openModal('supplier-modal');
}

function openDelete(id, name) {
  deleteId = id;
  document.getElementById('delete-name').textContent = name;
  openModal('delete-modal');
}

document.getElementById('add-btn').addEventListener('click', openAdd);

document.getElementById('save-btn').addEventListener('click', async () => {
  const btn = document.getElementById('save-btn');
  const msg = document.getElementById('modal-msg');
  const body = {
    supplier_id: document.getElementById('f-id').value.trim(),
    name: document.getElementById('f-name').value.trim(),
    contact_person: document.getElementById('f-contact').value.trim(),
    phone: document.getElementById('f-phone').value.trim(),
    email: document.getElementById('f-email').value.trim(),
    default_lead_time_days: parseInt(document.getElementById('f-lead').value) || 7,
    delivery_schedule: document.getElementById('f-schedule').value.trim(),
    notes: document.getElementById('f-notes').value.trim(),
  };
  if (!body.supplier_id || !body.name) { showError(msg, 'ID and name are required.'); return; }
  setLoading(btn, true, 'Save');
  try {
    if (editId) {
      await apiFetch(`/inventory/suppliers/${editId}`, { method: 'PUT', body });
    } else {
      await apiFetch('/inventory/suppliers', { method: 'POST', body });
    }
    closeModal('supplier-modal');
    load();
  } catch (err) { showError(msg, err.message); }
  finally { setLoading(btn, false, 'Save'); }
});

document.getElementById('confirm-delete-btn').addEventListener('click', async () => {
  const btn = document.getElementById('confirm-delete-btn');
  setLoading(btn, true, 'Delete');
  try {
    await apiFetch(`/inventory/suppliers/${deleteId}`, { method: 'DELETE' });
    closeModal('delete-modal');
    load();
  } catch (err) { showError(document.getElementById('msg'), err.message); }
  finally { setLoading(btn, false, 'Delete'); }
});

load();
