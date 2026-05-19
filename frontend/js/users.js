requireRole('admin');
initShell();

let allUsers = [];
let editId = null;

async function load() {
  const spinner = document.getElementById('users-spinner');
  try {
    const data = await apiFetch('/admin/users');
    if (!data) return;
    allUsers = data;
    spinner.style.display = 'none';
    render();
  } catch { spinner.style.display = 'none'; }
}

function render() {
  const tbody = document.getElementById('users-tbody');
  if (!allUsers.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--color-text-hint);padding:32px;">No users</td></tr>'; return;
  }
  tbody.innerHTML = allUsers.map(u => `
    <tr>
      <td style="font-weight:500;">${u.name}</td>
      <td>${u.email}</td>
      <td><span class="badge ${u.role==='admin'?'badge-warning':'badge-normal'}">${u.role}</span></td>
      <td><span class="badge ${u.is_active?'badge-success':'badge-urgent'}">${u.is_active?'Active':'Inactive'}</span></td>
      <td style="font-size:12px;">${u.last_login ? formatDateTime(u.last_login) : 'Never'}</td>
      <td>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          <button class="btn btn-secondary btn-sm" onclick="openEdit('${u.id}')">Edit</button>
          <button class="btn btn-secondary btn-sm" onclick="toggleActive('${u.id}')">${u.is_active?'Deactivate':'Activate'}</button>
          <button class="btn btn-secondary btn-sm" onclick="resetPw('${u.id}')">Reset PW</button>
        </div>
      </td>
    </tr>`).join('');
}

function openAdd() {
  editId = null;
  document.getElementById('modal-title').textContent = 'Add User';
  document.getElementById('user-form').reset();
  document.getElementById('pw-group').style.display = 'block';
  document.getElementById('f-password').required = true;
  hideMsg(document.getElementById('modal-msg'));
  openModal('user-modal');
}

function openEdit(id) {
  const u = allUsers.find(x => x.id === id);
  if (!u) return;
  editId = id;
  document.getElementById('modal-title').textContent = 'Edit User';
  document.getElementById('f-name').value = u.name;
  document.getElementById('f-email').value = u.email;
  document.getElementById('f-role').value = u.role;
  document.getElementById('pw-group').style.display = 'none';
  document.getElementById('f-password').required = false;
  hideMsg(document.getElementById('modal-msg'));
  openModal('user-modal');
}

async function toggleActive(id) {
  const msg = document.getElementById('msg');
  try {
    const res = await apiFetch(`/admin/users/${id}/deactivate`, { method: 'POST' });
    showSuccess(msg, res.message);
    load();
    setTimeout(() => hideMsg(msg), 3000);
  } catch (err) { showError(msg, err.message); }
}

async function resetPw(id) {
  try {
    const res = await apiFetch(`/admin/users/${id}/reset-password`, { method: 'POST' });
    document.getElementById('temp-password-display').textContent = res.temp_password;
    openModal('reset-modal');
  } catch (err) { showError(document.getElementById('msg'), err.message); }
}

document.getElementById('add-btn').addEventListener('click', openAdd);

document.getElementById('save-btn').addEventListener('click', async () => {
  const btn = document.getElementById('save-btn');
  const msg = document.getElementById('modal-msg');
  const body = {
    name: document.getElementById('f-name').value.trim(),
    email: document.getElementById('f-email').value.trim(),
    role: document.getElementById('f-role').value,
    password: document.getElementById('f-password').value,
  };
  if (!body.name || !body.email) { showError(msg, 'Name and email are required.'); return; }
  if (!editId && !body.password) { showError(msg, 'Password is required for new users.'); return; }
  setLoading(btn, true, 'Save');
  try {
    if (editId) {
      await apiFetch(`/admin/users/${editId}`, { method: 'PUT', body });
    } else {
      await apiFetch('/admin/users', { method: 'POST', body });
    }
    closeModal('user-modal');
    load();
  } catch (err) { showError(msg, err.message); }
  finally { setLoading(btn, false, 'Save'); }
});

load();
