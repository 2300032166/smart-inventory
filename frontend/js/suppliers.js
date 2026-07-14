// Allow manager and admin (not customer)
if (!checkAuth()) throw new Error('not auth');
const _role = getRole();
if (_role !== 'manager' && _role !== 'admin') {
  window.location.href = '../pages/login.html';
}
initShell();

let allSuppliers = [];
let editId  = null;
let deleteId = null;

// ── Tab switching ──────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  });
});

// ── Load Suppliers ─────────────────────────────────────────
async function load() {
  const spinner = document.getElementById('sup-spinner');
  if (spinner) spinner.style.display = 'flex';
  try {
    const data = await apiFetch('/suppliers');
    allSuppliers = Array.isArray(data) ? data : [];
    render();
    populateMappingSelects();
  } catch (e) {
    console.error('Failed to load suppliers:', e);
    const tbody = document.getElementById('suppliers-tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--color-danger);padding:32px;">Failed to load suppliers. Please refresh.</td></tr>';
  } finally {
    if (spinner) spinner.style.display = 'none';
  }
}

function render() {
  const tbody = document.getElementById('suppliers-tbody');
  if (!allSuppliers.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--color-text-hint);padding:32px;">No suppliers found</td></tr>';
    return;
  }
  tbody.innerHTML = allSuppliers.map(s => {
    const statusCls  = (s.status || 'Active') === 'Active' ? 'status-active' : 'status-inactive';
    const scoreBadge = s.total_orders > 0
      ? `<span class="badge badge-${getScoreColor(s.reliability_score)}" title="Reliability Score">${s.reliability_score}</span>`
      : '<span class="badge badge-gray">No data</span>';
    return `<tr>
      <td>
        <div style="font-weight:600;">${s.name}</div>
        <div style="font-size:11px;color:var(--color-text-hint);">${s.supplier_id}</div>
      </td>
      <td style="font-size:12px;">${s.company_name || '—'}</td>
      <td style="font-size:12px;">${s.contact_person || '—'}</td>
      <td style="font-size:12px;">${s.phone || '—'}</td>
      <td><a href="mailto:${s.email}" style="color:var(--color-primary);font-size:12px;">${s.email || '—'}</a></td>
      <td style="font-size:12px;">${s.default_lead_time_days}d</td>
      <td><span class="badge ${statusCls} badge-sm">${s.status || 'Active'}</span></td>
      <td>${scoreBadge}</td>
      <td>
        <div class="sup-actions">
          <a href="supplier-dashboard.html?sid=${s.supplier_id}" class="sup-action-btn view" title="View Dashboard">
            <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
          </a>
          <button class="sup-action-btn edit" onclick="openEdit('${s.supplier_id}')" title="Edit Supplier">
            <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
          <button class="sup-action-btn disable" onclick="openDelete('${s.supplier_id}','${s.name.replace(/'/g,`\\'`).replace(/"/g,`&quot;`)}')" title="Disable Supplier">
            <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>
          </button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

function getScoreColor(score) {
  if (score >= 85) return 'success';
  if (score >= 70) return 'warning';
  return 'urgent';
}

// ── Add / Edit Supplier ────────────────────────────────────
function openAdd() {
  editId = null;
  document.getElementById('modal-title').textContent = 'Add Supplier';
  document.getElementById('supplier-form').reset();
  document.getElementById('f-id').readOnly = false;
  document.getElementById('f-status').value = 'Active';
  hideMsg(document.getElementById('modal-msg'));
  openModal('supplier-modal');
}

function openEdit(id) {
  const s = allSuppliers.find(x => x.supplier_id === id);
  if (!s) return;
  editId = id;
  document.getElementById('modal-title').textContent = 'Edit Supplier';
  document.getElementById('f-id').value       = s.supplier_id;
  document.getElementById('f-id').readOnly    = true;
  document.getElementById('f-name').value     = s.name;
  document.getElementById('f-company').value  = s.company_name || '';
  document.getElementById('f-contact').value  = s.contact_person || '';
  document.getElementById('f-phone').value    = s.phone || '';
  document.getElementById('f-email').value    = s.email || '';
  document.getElementById('f-address').value  = s.address || '';
  document.getElementById('f-lead').value     = s.default_lead_time_days;
  document.getElementById('f-schedule').value = s.delivery_schedule || '';
  document.getElementById('f-status').value   = s.status || 'Active';
  document.getElementById('f-notes').value    = s.notes || '';
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
    supplier_id:            document.getElementById('f-id').value.trim(),
    name:                   document.getElementById('f-name').value.trim(),
    company_name:           document.getElementById('f-company').value.trim(),
    contact_person:         document.getElementById('f-contact').value.trim(),
    phone:                  document.getElementById('f-phone').value.trim(),
    email:                  document.getElementById('f-email').value.trim(),
    address:                document.getElementById('f-address').value.trim(),
    status:                 document.getElementById('f-status').value,
    default_lead_time_days: parseInt(document.getElementById('f-lead').value) || 7,
    delivery_schedule:      document.getElementById('f-schedule').value.trim(),
    notes:                  document.getElementById('f-notes').value.trim(),
  };
  if (!body.supplier_id || !body.name) { showError(msg, 'ID and name are required.'); return; }
  setLoading(btn, true, 'Save');
  try {
    if (editId) {
      await apiFetch(`/suppliers/${editId}`, { method: 'PUT', body });
    } else {
      await apiFetch('/suppliers', { method: 'POST', body });
    }
    closeModal('supplier-modal');
    load();
    showToast('Supplier saved!', 'success');
  } catch (err) { showError(msg, err.message); }
  finally { setLoading(btn, false, 'Save'); }
});

document.getElementById('confirm-delete-btn').addEventListener('click', async () => {
  const btn = document.getElementById('confirm-delete-btn');
  setLoading(btn, true, 'Disable');
  try {
    await apiFetch(`/suppliers/${deleteId}`, { method: 'DELETE' });
    closeModal('delete-modal');
    load();
    showToast('Supplier disabled.', 'info');
  } catch (err) { showError(document.getElementById('msg'), err.message); }
  finally { setLoading(btn, false, 'Disable'); }
});

// ── Product Mappings Tab ───────────────────────────────────
function populateMappingSelects() {
  const sels = ['map-supplier-sel', 'map-view-supplier'];
  sels.forEach(selId => {
    const sel = document.getElementById(selId);
    const cur = sel.value;
    sel.innerHTML = selId === 'map-supplier-sel'
      ? '<option value="">— Select Supplier —</option>'
      : '<option value="">— Select Supplier —</option>';
    allSuppliers.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.supplier_id;
      opt.textContent = s.name;
      sel.appendChild(opt);
    });
    if (cur) sel.value = cur;
  });
}

// View supplier's products when selected
document.getElementById('map-view-supplier').addEventListener('change', async (e) => {
  const sid = e.target.value;
  const wrap    = document.getElementById('map-table-wrap');
  const spinner = document.getElementById('map-spinner');
  const tbody   = document.getElementById('map-tbody');
  if (!sid) { wrap.style.display = 'none'; return; }
  spinner.style.display = 'flex';
  wrap.style.display = 'none';
  try {
    const products = await apiFetch(`/suppliers/${sid}/products`);
    spinner.style.display = 'none';
    if (!products || !products.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--color-text-hint);padding:24px;">No products mapped to this supplier</td></tr>';
    } else {
      tbody.innerHTML = products.map(p => `
        <tr>
          <td style="font-family:monospace;font-size:12px;">${p.sku}</td>
          <td style="font-weight:500;">${p.product_name || '—'}</td>
          <td><span class="badge badge-gray">${p.category || '—'}</span></td>
          <td>₹${Number(p.unit_price || 0).toFixed(2)}</td>
          <td>${p.current_stock ?? '—'}</td>
          <td>
            <button class="btn btn-danger btn-sm"
              onclick="removeMapping('${sid}','${p.sku}','${(p.product_name || p.sku).replace(/'/g,"\\'")}')">
              Remove
            </button>
          </td>
        </tr>`).join('');
    }
    wrap.style.display = 'block';
  } catch (e) {
    spinner.style.display = 'none';
    showError(document.getElementById('msg'), e.message);
  }
});

// Add mapping
document.getElementById('btn-add-mapping').addEventListener('click', async () => {
  const sid = document.getElementById('map-supplier-sel').value;
  const sku = document.getElementById('map-sku-input').value.trim();
  const msg = document.getElementById('map-msg');
  if (!sid || !sku) { showError(msg, 'Select a supplier and enter a SKU.'); return; }
  try {
    await apiFetch('/suppliers/mappings', { method: 'POST', body: { supplier_id: sid, sku } });
    hideMsg(msg);
    showToast('Mapping added!', 'success');
    document.getElementById('map-sku-input').value = '';
    // Refresh view if same supplier selected
    const viewSid = document.getElementById('map-view-supplier').value;
    if (viewSid === sid) {
      document.getElementById('map-view-supplier').dispatchEvent(new Event('change'));
    }
  } catch (e) { showError(msg, e.message); }
});

// Remove mapping
async function removeMapping(sid, sku, name) {
  if (!confirm(`Remove mapping: ${name} from this supplier?`)) return;
  try {
    await apiFetch(`/suppliers/mappings/${sid}/${sku}`, { method: 'DELETE' });
    showToast('Mapping removed.', 'info');
    document.getElementById('map-view-supplier').dispatchEvent(new Event('change'));
  } catch (e) { showError(document.getElementById('msg'), e.message); }
}
window.removeMapping = removeMapping;

// Product search
document.getElementById('btn-prod-search').addEventListener('click', searchProductSuppliers);
document.getElementById('prod-search-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') searchProductSuppliers();
});

async function searchProductSuppliers() {
  const q = document.getElementById('prod-search-input').value.trim();
  const el = document.getElementById('prod-search-results');
  if (!q) return;
  el.innerHTML = '<div style="font-size:12px;color:var(--color-text-hint);padding:8px;">Searching…</div>';
  try {
    const products = await apiFetch('/inventory/products');
    const matches = (products || []).filter(p =>
      p.sku.toLowerCase().includes(q.toLowerCase()) ||
      p.name.toLowerCase().includes(q.toLowerCase())
    ).slice(0, 6);

    if (!matches.length) {
      el.innerHTML = '<div style="font-size:12px;color:var(--color-text-hint);padding:8px;">No products found.</div>';
      return;
    }

    if (matches.length === 1) {
      el.innerHTML = '';
      showProdSuppliers(matches[0]);
    } else {
      el.innerHTML = '<div style="font-size:12px;font-weight:500;margin-bottom:6px;color:var(--color-text-secondary);">Select a product:</div>' +
        matches.map(p => `
          <button class="btn btn-secondary btn-sm" style="margin:3px;font-size:12px;"
            onclick="showProdSuppliers({sku:'${p.sku}',name:'${p.name.replace(/'/g,"\\'")}'})"
          >${p.name} <span style="opacity:.6">(${p.sku})</span></button>`
        ).join('');
    }
  } catch (e) {
    el.innerHTML = `<div style="color:var(--color-danger);font-size:12px;">${e.message}</div>`;
  }
}

async function showProdSuppliers(prod) {
  const el = document.getElementById('prod-search-results');
  el.innerHTML = `<div style="font-weight:600;font-size:13px;margin:10px 0 6px;">${prod.name} (${prod.sku})</div>`;
  try {
    const sups = await apiFetch(`/suppliers/product/${prod.sku}/suppliers`);
    if (!sups || !sups.length) {
      el.innerHTML += '<div style="font-size:12px;color:var(--color-text-hint);">No suppliers mapped to this product.</div>';
      return;
    }
    el.innerHTML += `<div class="table-wrap"><table>
      <thead><tr><th>Rank</th><th>Supplier</th><th>Reliability</th><th>On-Time%</th><th>Lead Time</th><th>Fill Rate</th><th>Quality</th></tr></thead>
      <tbody>${sups.map((s, i) => `
        <tr ${i === 0 ? 'style="background:var(--color-success-light);"' : ''}>
          <td><b>${i + 1}</b>${i === 0 ? ' \ud83c\udfc6' : ''}</td>
          <td style="font-weight:500;">${s.name}</td>
          <td style="font-weight:700;color:${s.reliability_score >= 85 ? 'var(--color-success)' : 'var(--color-warning)'};">${s.reliability_score}</td>
          <td>${s.on_time_pct}%</td>
          <td>${s.avg_lead_time} d</td>
          <td>${s.fill_rate}%</td>
          <td>${'★'.repeat(Math.round(s.quality_rating || 0))} (${(s.quality_rating || 0).toFixed(1)})</td>
        </tr>`).join('')}
      </tbody></table></div>`;
  } catch (e) {
    el.innerHTML += `<div style="color:var(--color-danger);font-size:12px;">${e.message}</div>`;
  }
}
window.showProdSuppliers = showProdSuppliers;
window.openEdit   = openEdit;
window.openDelete = openDelete;

load();

// ═══════════════════════════════════════════════════════════════
//  ALL SUPPLIERS COMPARISON  (Tab 3 of suppliers page)
// ═══════════════════════════════════════════════════════════════

const CMP_DEFAULT = { reliability: 40, leadtime: 30, quality: 20, fillrate: 10 };
let cmpWeights  = { ...CMP_DEFAULT };
let cmpSortMode = 'custom';
let allSuppliersData = [];
let cmpLoaded = false;

// ── Weight sliders ─────────────────────────────────────────
['reliability', 'leadtime', 'quality', 'fillrate'].forEach(k => {
  const slider = document.getElementById(`cmp-w-${k}`);
  const label  = document.getElementById(`cmp-lbl-${k}`);
  if (!slider) return;
  slider.addEventListener('input', () => {
    cmpWeights[k] = parseInt(slider.value);
    label.textContent = cmpWeights[k] + '%';
    updateCmpWeightTotal();
    renderCmpTable();
  });
});

document.getElementById('cmp-btn-reset')?.addEventListener('click', () => {
  cmpWeights = { ...CMP_DEFAULT };
  ['reliability', 'leadtime', 'quality', 'fillrate'].forEach(k => {
    document.getElementById(`cmp-w-${k}`).value = cmpWeights[k];
    document.getElementById(`cmp-lbl-${k}`).textContent = cmpWeights[k] + '%';
  });
  updateCmpWeightTotal();
  renderCmpTable();
});

function updateCmpWeightTotal() {
  const total = Object.values(cmpWeights).reduce((a, b) => a + b, 0);
  const el = document.getElementById('cmp-weight-total');
  if (!el) return;
  el.textContent = `Total: ${total}%${total === 100 ? ' ✓' : ' \u26a0 (must equal 100%)'}`;
  el.className = 'cmp-weight-total ' + (total === 100 ? 'ok' : 'warn');
}

// ── Sort buttons ───────────────────────────────────────────
document.querySelectorAll('.cmp-sort-bar button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.cmp-sort-bar button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    cmpSortMode = btn.dataset.cmpsort;
    renderCmpTable();
  });
});

function cmpCustomScore(s) {
  const total = Object.values(cmpWeights).reduce((a, b) => a + b, 0);
  if (total === 0) return 0;
  const wR = cmpWeights.reliability / total;
  const wL = cmpWeights.leadtime    / total;
  const wQ = cmpWeights.quality     / total;
  const wF = cmpWeights.fillrate    / total;
  const rScore  = s.reliability_score ?? 0;
  const ltScore = Math.max(0, (1 - (s.avg_lead_time ?? 14) / 14)) * 100;
  const qScore  = ((s.quality_rating ?? 0) / 5) * 100;
  const fScore  = s.fill_rate ?? 0;
  return Math.round(wR * rScore + wL * ltScore + wQ * qScore + wF * fScore);
}

function cmpSorted(list) {
  const copy = [...list];
  switch (cmpSortMode) {
    case 'reliability': return copy.sort((a, b) => (b.reliability_score ?? 0) - (a.reliability_score ?? 0));
    case 'ontime':      return copy.sort((a, b) => (b.on_time_pct ?? 0) - (a.on_time_pct ?? 0));
    case 'quality':     return copy.sort((a, b) => (b.quality_rating ?? 0) - (a.quality_rating ?? 0));
    case 'leadtime':    return copy.sort((a, b) => (a.avg_lead_time ?? 99) - (b.avg_lead_time ?? 99));
    case 'fillrate':    return copy.sort((a, b) => (b.fill_rate ?? 0) - (a.fill_rate ?? 0));
    default:            return copy.sort((a, b) => cmpCustomScore(b) - cmpCustomScore(a));
  }
}

function cmpScoreColor(score) {
  if (score >= 90) return '#059669';
  if (score >= 75) return '#2563EB';
  if (score >= 60) return '#D97706';
  return '#DC2626';
}

function cmpStarsHtml(q) {
  const r = Math.round(q);
  return '<span class="cmp-star-filled">' + '★'.repeat(r) + '</span><span style="color:#CBD5E1;">' + '★'.repeat(5 - r) + '</span>';
}

function cmpLevelClass(l) {
  return 'cmp-perf-' + (l || 'Average').replace(' ', '-');
}

function renderCmpTable() {
  const list = cmpSorted(allSuppliersData);
  if (!list.length) return;
  const best = list[0];
  document.getElementById('cmp-best-label').textContent = `\ud83c\udfc6 Best: ${best.name} (Score: ${best.reliability_score})`;

  const tbody = document.getElementById('cmp-tbody');
  tbody.innerHTML = list.map((s, i) => {
    const rank   = i + 1;
    const cs     = cmpCustomScore(s);
    const rCls   = rank === 1 ? 'cmp-rank-1' : rank === 2 ? 'cmp-rank-2' : rank === 3 ? 'cmp-rank-3' : 'cmp-rank-n';
    const rowCls = rank === 1 ? 'cmp-best-row' : '';
    const color  = cmpScoreColor(s.reliability_score ?? 0);
    return `<tr class="${rowCls}">
      <td><span class="cmp-rank-badge ${rCls}">${rank}</span></td>
      <td>
        <div style="font-weight:600;">${s.name}${rank === 1 ? ' <span style="color:#F59E0B;font-size:12px;">\ud83c\udfc6</span>' : ''}</div>
        <div style="font-size:11px;color:var(--color-text-hint);">${s.company_name || ''}</div>
      </td>
      <td>
        <div class="cmp-score-bar-wrap">
          <div class="cmp-score-bar-track"><div class="cmp-score-bar-fill" style="width:${s.reliability_score ?? 0}%;background:${color};"></div></div>
          <span style="font-weight:700;color:${color};min-width:32px;">${s.reliability_score ?? '—'}</span>
        </div>
        ${cmpSortMode === 'custom' ? `<div style="font-size:10px;color:var(--color-text-hint);">Weighted: ${cs}</div>` : ''}
      </td>
      <td style="font-weight:600;color:${(s.on_time_pct ?? 0) >= 90 ? 'var(--color-success)' : 'inherit'};">${s.on_time_pct ?? '—'}%</td>
      <td>${s.avg_lead_time ?? '—'} d</td>
      <td>${(s.avg_delay ?? 0) > 0 ? '+' + s.avg_delay + ' d' : '—'}</td>
      <td>${s.fill_rate ?? '—'}%</td>
      <td>${cmpStarsHtml(s.quality_rating ?? 0)} <span style="font-size:11px;color:var(--color-text-hint);">(${(s.quality_rating ?? 0).toFixed(1)})</span></td>
      <td><span class="${cmpLevelClass(s.performance_level)}">${s.performance_level || '—'}</span></td>
      <td><a href="supplier-dashboard.html?sid=${s.supplier_id}" class="btn btn-secondary btn-sm">View</a></td>
    </tr>`;
  }).join('');
}

async function loadCmpMetrics() {
  if (cmpLoaded) return;
  cmpLoaded = true;
  const spinner = document.getElementById('cmp-spinner');
  if (spinner) spinner.style.display = 'flex';
  try {
    const data = await apiFetch('/suppliers/metrics/all');
    if (!data) return;
    allSuppliersData = data;
    renderCmpTable();
  } catch (e) {
    const msg = document.getElementById('cmp-msg');
    if (msg) showError(msg, e.message);
  } finally {
    if (spinner) spinner.style.display = 'none';
  }
}

// ── Load comparison data lazily when tab is first opened ───
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (btn.dataset.tab === 'tab-comparison') loadCmpMetrics();
  });
});
