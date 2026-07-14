requireRole('manager');
initShell();

const role = getRole();

let allPos = [];          // PO list from /suppliers/purchase-orders/list
let aiDecisions = [];     // Decisions from /orders/reviewed
let allProducts = [];
let suppliers = [];
let mappedSuppliers = [];
let recommendedSupplierId = null;
let activeTab = 'all';

let currentPage = 1;
const PAGE_SIZE = 30;

let editPoId = null;
let receivePoId = null;
let receiveOrderId = null; // if marking received from AI decision status update
let ratePoId = null;
let changePoId = null;

let rcvQuality = 0;
let rateQuality = 0;

// Setup Date Picker default today
const datePicker = document.getElementById('date-picker');
const dateText = document.getElementById('review-date');
const now = new Date();
const todayStr = [
  now.getFullYear(),
  String(now.getMonth() + 1).padStart(2, '0'),
  String(now.getDate()).padStart(2, '0')
].join('-');

if (datePicker) {
  datePicker.value = todayStr;
  datePicker.max = todayStr;
  datePicker.addEventListener('change', () => {
    updateDateText(datePicker.value);
    loadAllData();
  });
}

function updateDateText(dateStr) {
  if (!dateStr || !dateText) return;
  const [y, m, d] = dateStr.split('-');
  dateText.textContent = `Date: ${d}-${m}-${y}`;
}
updateDateText(todayStr);

// Tab switching — only 'all' and 'skipped'
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeTab = btn.dataset.tab;
    currentPage = 1;
    render();
  });
});

async function loadSuppliers() {
  try {
    const data = await apiFetch('/suppliers');
    if (!data) return;
    suppliers = data;
    const sel = document.getElementById('fil-supplier');
    if (sel) {
      sel.innerHTML = '<option value="">All Suppliers</option>';
      suppliers.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.supplier_id;
        opt.textContent = s.name;
        sel.appendChild(opt);
      });
    }
  } catch (e) { console.error('Failed to load suppliers:', e); }
}

async function loadProducts() {
  try {
    const data = await apiFetch('/inventory/products');
    allProducts = data || [];
  } catch (e) { console.error('Failed to load products:', e); }
}

// ── Searchable product dropdown for PO creation ──
function renderProductDropdown(filter = '') {
  const dd = document.getElementById('f-po-product-dropdown');
  if (!dd) return;
  const term = filter.trim().toLowerCase();
  const filtered = term
    ? allProducts.filter(p => `${p.name} ${p.sku}`.toLowerCase().includes(term))
    : allProducts.slice(0, 50);

  const esc = (s) => String(s || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

  if (!filtered.length) {
    dd.innerHTML = '<div class="product-dropdown-empty">No products found</div>';
    return;
  }

  dd.innerHTML = filtered.map(p => `
    <div class="product-dropdown-item" data-sku="${esc(p.sku)}" data-name="${esc(p.name)}">
      <span class="p-name">${esc(p.name)}</span>
      <span class="p-sku">${esc(p.sku)}</span>
    </div>
  `).join('');
}

function showProductDropdown() {
  const dd = document.getElementById('f-po-product-dropdown');
  const searchInput = document.getElementById('f-po-product-search');
  if (dd && dd.innerHTML.trim() === '') renderProductDropdown(searchInput?.value || '');
  dd?.classList.add('show');
}

function hideProductDropdown() {
  document.getElementById('f-po-product-dropdown')?.classList.remove('show');
}

function selectProduct(sku, name) {
  const fSku = document.getElementById('f-po-sku');
  const fSearch = document.getElementById('f-po-product-search');
  const selectedDiv = document.getElementById('product-selected');
  const selectedText = document.getElementById('product-selected-text');
  const hint = document.getElementById('product-hint');
  
  if (fSku) fSku.value = sku;
  if (fSearch) fSearch.value = '';
  if (selectedText) selectedText.textContent = `${name} · ${sku}`;
  if (selectedDiv) selectedDiv.style.display = 'flex';
  if (hint) hint.textContent = '';
  hideProductDropdown();
  loadMappedSuppliers(sku);
}

function clearProductSelection() {
  const fSku = document.getElementById('f-po-sku');
  const fSearch = document.getElementById('f-po-product-search');
  const selectedDiv = document.getElementById('product-selected');
  const hint = document.getElementById('product-hint');
  const supSel = document.getElementById('f-po-supplier');

  if (fSku) fSku.value = '';
  if (fSearch) fSearch.value = '';
  if (selectedDiv) selectedDiv.style.display = 'none';
  if (hint) hint.textContent = 'Select a product to see its mapped suppliers.';
  if (supSel) {
    supSel.innerHTML = '<option value="">— Select a product first —</option>';
    supSel.disabled = true;
  }
  document.getElementById('supplier-recommendation')?.classList.remove('show');
  mappedSuppliers = [];
  recommendedSupplierId = null;
}

// Setup product search box event listeners
(function setupProductSearch() {
  const search = document.getElementById('f-po-product-search');
  const dd = document.getElementById('f-po-product-dropdown');
  if (!search || !dd) return;

  search.addEventListener('input', () => {
    renderProductDropdown(search.value);
    showProductDropdown();
  });
  search.addEventListener('focus', () => showProductDropdown());
  search.addEventListener('keydown', e => {
    if (e.key === 'Escape') { hideProductDropdown(); search.blur(); }
  });
  dd.addEventListener('click', e => {
    const item = e.target.closest('.product-dropdown-item');
    if (!item) return;
    selectProduct(item.dataset.sku, item.dataset.name);
  });
  document.addEventListener('click', e => {
    if (!search.contains(e.target) && !dd.contains(e.target)) hideProductDropdown();
  });
})();

async function loadMappedSuppliers(sku) {
  const supSel = document.getElementById('f-po-supplier');
  if (!supSel) return;
  supSel.disabled = true;
  supSel.innerHTML = '<option value="">Loading suppliers…</option>';
  try {
    const data = await apiFetch(`/suppliers/recommendation/${encodeURIComponent(sku)}`);
    mappedSuppliers = data?.all_suppliers || [];
    recommendedSupplierId = data?.recommended?.supplier_id || null;

    if (!mappedSuppliers.length) {
      supSel.innerHTML = '<option value="">No suppliers mapped to this product</option>';
      document.getElementById('supplier-recommendation')?.classList.remove('show');
      return;
    }

    supSel.innerHTML = mappedSuppliers.map(s => `
      <option value="${s.supplier_id}">${s.name} (Reliability ${s.reliability_score ?? '—'})</option>
    `).join('');
    supSel.disabled = false;

    if (recommendedSupplierId) {
      supSel.value = recommendedSupplierId;
      const rec = data.recommended;
      const recName = document.getElementById('rec-supplier-name');
      const recReasons = document.getElementById('rec-supplier-reasons');
      if (recName) recName.textContent = rec.name;
      if (recReasons) recReasons.textContent = (rec.reasons || []).join(' · ') || `Reliability score ${rec.reliability_score}`;
      document.getElementById('supplier-recommendation')?.classList.add('show');
    } else {
      document.getElementById('supplier-recommendation')?.classList.remove('show');
    }
  } catch (e) {
    supSel.innerHTML = '<option value="">Unable to load suppliers</option>';
    console.error(e);
  }
}

// ── Main Data Loading ──
async function loadAllData() {
  const spinner = document.getElementById('po-spinner');
  if (spinner) spinner.style.display = 'flex';
  
  try {
    const sid    = document.getElementById('fil-supplier').value;
    const status = document.getElementById('fil-status').value;
    const from   = document.getElementById('fil-from').value;
    const to     = document.getElementById('fil-to').value;
    const selectedDate = datePicker?.value || todayStr;

    // 1. Fetch AI decisions for selected date
    let aiItems = [];
    try {
      aiItems = await apiFetch(`/orders/reviewed?date=${selectedDate}`) || [];
    } catch (e) { console.error('Failed to load AI orders:', e); }

    // 2. Fetch purchase orders list
    let posItems = [];
    try {
      let qs = `?page=1&limit=500`;
      if (sid)    qs += `&supplier_id=${encodeURIComponent(sid)}`;
      if (status) qs += `&status=${status}`;
      if (from)   qs += `&date_from=${from}`;
      if (to)     qs += `&date_to=${to}`;
      
      const posData = await apiFetch(`/suppliers/purchase-orders/list${qs}`);
      posItems = posData?.items || [];
    } catch (e) { console.error('Failed to load POs list:', e); }

    aiDecisions = aiItems;
    allPos = posItems;

    render();
  } catch (err) {
    showError(document.getElementById('msg'), err.message);
  } finally {
    if (spinner) spinner.style.display = 'none';
  }
}

// Render tabs counts, stats, tables
function render() {
  const aiLifecycle = aiDecisions.filter(d => d.decision !== 'skipped');
  // Exclude undone skips: when a skip is undone, backend sets status='cancelled'
  // Those items are back in Daily Brief and should not show here
  const aiSkipped   = aiDecisions.filter(d => d.decision === 'skipped' && d.status !== 'cancelled');

  const aiLinkedPoIds = new Set(aiLifecycle.map(d => d.po_id).filter(Boolean));
  const manualPos     = allPos.filter(p => !aiLinkedPoIds.has(p.po_id));

  const formattedAIs = aiLifecycle.filter(d => d.status !== 'cancelled').map(d => {
    // Override AI data with fresh PO data if available (e.g. after edit/Supplier change)
    const matchingPo = allPos.find(p => p.po_id === d.po_id);
    return {
      id: d.id,
      po_id: d.po_id,
      po_number: d.po_number || (matchingPo ? matchingPo.po_number : 'AI Decision'),
      product_name: d.product_name,
      sku: d.sku,
      supplier_id: matchingPo ? matchingPo.supplier_id : d.supplier_id,
      supplier_name: matchingPo ? matchingPo.supplier_name : d.supplier_name,
      source: 'ai',
      order_date: matchingPo ? matchingPo.order_date : (d.approval_date ? d.approval_date.slice(0,10) : d.timestamp.slice(0,10)),
      expected_delivery_date: matchingPo ? matchingPo.expected_delivery_date : (d.expected_arrival_date ? d.expected_arrival_date.slice(0,10) : '—'),
      ordered_qty: matchingPo ? parseFloat(matchingPo.ordered_qty || 0) : d.actual_qty,
      received_qty: matchingPo ? parseFloat(matchingPo.received_qty || 0) : (d.status === 'received' ? d.actual_qty : 0),
      fill_rate: matchingPo 
        ? (matchingPo.status === 'received' && parseFloat(matchingPo.ordered_qty) > 0 ? Math.round((parseFloat(matchingPo.received_qty) / parseFloat(matchingPo.ordered_qty)) * 100) + '%' : '—') 
        : (d.status === 'received' ? '100%' : '—'),
      status: matchingPo ? matchingPo.status : (d.status || 'approved'),
      actual_delivery_date: matchingPo ? (matchingPo.actual_delivery_date || '—') : (d.received_date ? d.received_date.slice(0,10) : '—'),
      quality_rating: matchingPo ? (matchingPo.quality_rating || '') : (d.quality_rating || ''),
      note: matchingPo ? (matchingPo.notes || d.reason_text || '') : (d.reason_text || '')
    };
  });

  const formattedManuals = manualPos.map(p => ({
    id: null,
    po_id: p.po_id,
    po_number: p.po_number,
    product_name: p.product_name,
    sku: p.sku,
    supplier_id: p.supplier_id,
    supplier_name: p.supplier_name,
    source: 'manual',
    order_date: p.order_date,
    expected_delivery_date: p.expected_delivery_date,
    ordered_qty: parseFloat(p.ordered_qty || 0),
    received_qty: parseFloat(p.received_qty || 0),
    fill_rate: p.status === 'received' ? (parseFloat(p.ordered_qty) > 0 ? Math.round(parseFloat(p.received_qty) / parseFloat(p.ordered_qty) * 100) + '%' : '—') : '—',
    status: p.status,
    actual_delivery_date: p.actual_delivery_date || '—',
    quality_rating: p.quality_rating || '',
    note: p.notes || ''
  }));

  let allCombined = [...formattedAIs, ...formattedManuals]
    .sort((a, b) => b.order_date.localeCompare(a.order_date));

  // Filter based on UI controls
  const sid    = document.getElementById('fil-supplier').value;
  const status = document.getElementById('fil-status').value;
  const from   = document.getElementById('fil-from').value;
  const to     = document.getElementById('fil-to').value;

  if (sid) {
    allCombined = allCombined.filter(x => x.supplier_id === sid);
  }
  if (status) {
    allCombined = allCombined.filter(x => x.status === status);
  }
  if (from) {
    allCombined = allCombined.filter(x => x.order_date >= from);
  }
  if (to) {
    allCombined = allCombined.filter(x => x.order_date <= to);
  }

  // Update counts
  document.getElementById('tc-all').textContent     = allCombined.length;
  document.getElementById('tc-skipped').textContent = aiSkipped.length;

  // Stats
  const orderedCount  = allCombined.filter(x => x.status === 'ordered').length;
  const receivedCount = allCombined.filter(x => x.status === 'received').length;
  const cancelledCount= allCombined.filter(x => x.status === 'cancelled').length;
  const fillRates = allCombined
    .filter(x => x.status === 'received' && parseFloat(x.ordered_qty) > 0)
    .map(x => parseFloat(x.received_qty || 0) / parseFloat(x.ordered_qty) * 100);
  const avgFill = fillRates.length
    ? (fillRates.reduce((a, b) => a + b, 0) / fillRates.length).toFixed(1) + '%'
    : '—';

  document.getElementById('stat-total').textContent    = allCombined.length;
  document.getElementById('stat-ordered').textContent  = orderedCount;
  document.getElementById('stat-received').textContent = receivedCount;
  document.getElementById('stat-cancelled').textContent= cancelledCount;
  document.getElementById('stat-fill').textContent     = avgFill;

  const mainTableCard  = document.getElementById('main-table-card');
  const skippedSection = document.getElementById('skipped-section');

  if (activeTab === 'skipped') {
    mainTableCard.style.display  = 'none';
    skippedSection.style.display = 'block';
    renderSkippedList(aiSkipped);
  } else {
    // 'all' tab — show everything
    mainTableCard.style.display  = 'block';
    skippedSection.style.display = 'none';
    renderMainTable(allCombined);
  }
}

function renderMainTable(list) {
  const tbody = document.getElementById('main-tbody');
  const pageNav = document.getElementById('pagination');
  
  const total = list.length;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;
  if (currentPage > totalPages) currentPage = totalPages;

  if (total === 0) {
    tbody.innerHTML = '<tr><td colspan="12" style="text-align:center;padding:32px;color:var(--color-text-hint);">No orders found under this view</td></tr>';
    pageNav.innerHTML = '';
    return;
  }

  const start = (currentPage - 1) * PAGE_SIZE;
  const pageItems = list.slice(start, start + PAGE_SIZE);

  tbody.innerHTML = pageItems.map(p => {
    const statusCls = `s-${p.status}`;
    const sourceBadge = p.source === 'ai' 
      ? '<span class="source-badge source-ai">AI</span>' 
      : '<span class="source-badge source-manual">Manual</span>';

    const qrRaw = p.quality_rating;
    const qrNum = Math.min(5, Math.max(0, parseInt(qrRaw) || 0));
    const stars = qrRaw !== '' && qrRaw != null
      ? `<span class="star-filled">${'★'.repeat(qrNum)}</span><span class="star-empty">${'★'.repeat(5 - qrNum)}</span>`
      : '—';

    // Decisions actions vs PO actions
    let actionButtons = '';
    if (p.source === 'ai') {
      const status = p.status;
      if (status === 'approved' || status === 'overridden') {
        actionButtons += `<button class="btn btn-primary btn-sm" onclick="updateAiStatus('${p.id}', 'ordered')">Mark Ordered</button>`;
      }
      if (status === 'ordered') {
        actionButtons += `<button class="btn btn-success btn-sm" onclick="openReceiveForAi('${p.id}', '${p.product_name}')">Mark Received</button>`;
      }
      if (p.po_id && status !== 'received' && status !== 'cancelled') {
        actionButtons += `<button class="btn btn-secondary btn-sm" onclick="openEdit('${p.po_id}')">Edit</button>`;
      }
      if (status === 'cancelled') {
        actionButtons += `<button class="btn btn-secondary btn-sm" onclick="updateAiStatus('${p.id}', 'approved')">Re-activate</button>`;
      }
      if (status !== 'received' && status !== 'cancelled') {
        actionButtons += `<button class="btn btn-ghost btn-sm" onclick="updateAiStatus('${p.id}', 'cancelled')">Cancel</button>`;
      }
    } else {
      // Manual PO controls
      const canEdit = p.status !== 'received' && p.status !== 'cancelled';
      const canReceive = p.status === 'ordered';
      const canCancel = p.status === 'ordered';
      const canRate = p.status === 'received' && (qrRaw === '' || qrRaw == null);

      if (canEdit) actionButtons += `<button class="btn btn-secondary btn-sm" onclick="openEdit('${p.po_id}')">Edit</button>`;
      if (canReceive) actionButtons += `<button class="btn btn-primary btn-sm" onclick="openReceiveForManual('${p.po_id}', '${p.product_name}', ${p.ordered_qty})">Receive</button>`;
      if (canCancel) actionButtons += `<button class="btn btn-danger btn-sm" onclick="cancelManualPO('${p.po_id}')">Cancel</button>`;
      if (canRate) actionButtons += `<button class="btn btn-secondary btn-sm" onclick="openRate('${p.po_id}','${p.product_name}')">Rate</button>`;
    }

    return `<tr>
      <td style="font-weight:600;font-size:12px;">${p.po_number}</td>
      <td style="font-size:12px;"><strong>${p.product_name}</strong><br><span style="color:#64748b;font-family:monospace;">${p.sku}</span></td>
      <td style="font-size:12px;">${p.supplier_name || p.supplier_id}</td>
      <td>${sourceBadge}</td>
      <td style="font-size:11px;">${p.order_date}</td>
      <td style="font-size:11px;">${p.expected_delivery_date}</td>
      <td style="font-size:12px;font-weight:600;">${p.ordered_qty}</td>
      <td style="font-size:12px;">${p.status === 'received' ? `<span style="font-weight:600;color:var(--color-primary);">${p.received_qty} units</span> <br><span style="font-size:10px;color:var(--color-text-hint);">(${p.fill_rate})</span>` : '—'}</td>
      <td><span class="status-pill ${statusCls}">${p.status.toUpperCase()}</span></td>
      <td style="font-size:11px;">${p.actual_delivery_date}</td>
      <td style="font-size:12px;">${stars}</td>
      <td><div class="action-cell">${actionButtons}</div></td>
    </tr>`;
  }).join('');

  // Pagination UI
  if (totalPages <= 1) {
    pageNav.innerHTML = '';
  } else {
    pageNav.innerHTML = `
      <button ${currentPage === 1 ? 'disabled' : ''} onclick="goPage(${currentPage - 1})">‹ Prev</button>
      <span>Page ${currentPage} of ${totalPages}</span>
      <button ${currentPage === totalPages ? 'disabled' : ''} onclick="goPage(${currentPage + 1})">Next ›</button>`;
  }
}

function goPage(p) { currentPage = p; render(); }

// ── Render Skipped AI Table ──
function renderSkippedList(items) {
  const tbody = document.getElementById('skipped-tbody');
  document.getElementById('skipped-count-label').textContent = items.length;

  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--color-text-hint);">No skipped AI recommendations found for this date.</td></tr>';
    return;
  }

  tbody.innerHTML = items.map(item => {
    const escapedName = (item.product_name || '').replace(/'/g, "\\'");
    return `
      <tr>
        <td>
          <div style="font-weight:600;">${item.product_name || '—'}</div>
          <div style="font-family:monospace;font-size:11px;color:#94a3b8;">${item.sku}</div>
        </td>
        <td style="font-weight:700;">${item.ai_suggested_qty}</td>
        <td>
          ${item.reason_category ? `<span class="badge badge-urgent">${item.reason_category}</span>` : '—'}
          <div style="font-style:italic;color:#64748b;font-size:12px;">"${item.reason_text || 'No reason provided'}"</div>
        </td>
        <td style="font-size:11px;color:#94a3b8;">${new Date(item.timestamp).toLocaleDateString('en-GB', { day:'2-digit', month:'short', year:'numeric' })} ${new Date(item.timestamp).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</td>
        <td>
          <div style="display:flex;gap:6px;">
            <button class="btn btn-secondary btn-sm" onclick="toggleSkippedEdit('${item.id}')">Edit Reason</button>
            <button class="btn btn-ghost btn-sm" onclick="undoSkippedDecision('${item.id}', '${escapedName}')">Undo Skip</button>
          </div>
        </td>
      </tr>
      <tr id="edit-row-${item.id}" style="display:none;background:#fff5f5;" class="inline-edit-row">
        <td colspan="5">
          <div style="padding:10px;">
             <div class="form-row" style="margin-bottom:0;align-items:flex-end;gap:8px;">
                <div class="form-group" style="margin-bottom:0;">
                  <label style="font-size:11px;">Skip Category</label>
                  <select id="edit-cat-${item.id}" style="font-size:12px;height:30px;">
                    <option value="Inventory suffice" ${item.reason_category === 'Inventory suffice' ? 'selected' : ''}>Inventory suffice</option>
                    <option value="Budget limited" ${item.reason_category === 'Budget limited' ? 'selected' : ''}>Budget limited</option>
                    <option value="Supplier unavailable" ${item.reason_category === 'Supplier unavailable' ? 'selected' : ''}>Supplier unavailable</option>
                    <option value="Other" ${item.reason_category === 'Other' ? 'selected' : ''}>Other</option>
                  </select>
                </div>
                <div class="form-group" style="flex:2;margin-bottom:0;">
                   <label style="font-size:11px;">Skip Notes</label>
                   <input type="text" id="edit-text-${item.id}" value="${item.reason_text || ''}" style="font-size:12px;height:30px;" placeholder="Optional notes…">
                </div>
                <button class="btn btn-danger btn-sm" style="height:30px;" id="btn-save-${item.id}" onclick="saveSkippedEdit('${item.id}')">Save</button>
             </div>
          </div>
        </td>
      </tr>`;
  }).join('');
}

// ── SIRA confirm modal custom wrapper ──
function siraConfirm(msg) {
  return new Promise((resolve) => {
    const modal = document.getElementById('modal-confirm');
    const msgEl = document.getElementById('confirm-message');
    const okBtn = document.getElementById('confirm-ok');
    const cancelBtn = document.getElementById('confirm-cancel');
    
    if (msgEl) msgEl.textContent = msg;
    openModal('modal-confirm');
    
    const cleanup = (val) => {
      resolve(val);
      closeModal('modal-confirm');
      okBtn.replaceWith(okBtn.cloneNode(true));
      cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    };
    
    document.getElementById('confirm-ok').addEventListener('click', () => cleanup(true));
    document.getElementById('confirm-cancel').addEventListener('click', () => cleanup(false));
  });
}

// ── AI Order status update actions ──
async function updateAiStatus(orderId, status) {
  const confirmed = await siraConfirm(`Mark this decision as ${status.toUpperCase()}?`);
  if (!confirmed) return;
  
  try {
    const res = await apiFetch(`/orders/${orderId}/status`, { 
      method: 'POST',
      body: { status: status }
    });
    if (res) {
      showToast(`Status updated to ${status}.`, 'success');
      loadAllData();
    }
  } catch (err) {
    showToast('Update failed: ' + err.message, 'danger');
  }
}

// ── AI Order Receive (with Mfg/Expiry Dates) ──
function openReceiveForAi(orderId, productName) {
  receiveOrderId = orderId;
  const item = aiDecisions.find(i => i.id === orderId);
  const infoEl = document.getElementById('batch-product-info');
  if (infoEl) infoEl.textContent = `${productName} (Qty: ${item ? item.actual_qty : '—'})`;
  
  const today = new Date().toISOString().split('T')[0];
  document.getElementById('batch-mfg-date').value = today;
  document.getElementById('batch-expiry-date').value = today;
  document.getElementById('expiry-date-error').style.display = 'none';
  
  const rcvQtyEl = document.getElementById('batch-rcv-qty');
  if (rcvQtyEl) {
    const matchingPo = allPos.find(p => p.po_id === item?.po_id);
    rcvQtyEl.value = matchingPo ? matchingPo.ordered_qty : (item ? item.actual_qty : 0);
  }

  const validateDates = () => {
    const err = document.getElementById('expiry-date-error');
    const expiryVal = document.getElementById('batch-expiry-date').value;
    const mfgVal = document.getElementById('batch-mfg-date').value;
    if (expiryVal && mfgVal && expiryVal <= mfgVal) {
      err.style.display = 'block';
    } else {
      err.style.display = 'none';
    }
  };
  document.getElementById('batch-expiry-date').oninput = validateDates;
  document.getElementById('batch-mfg-date').oninput = validateDates;

  openModal('batch-modal');
}

document.getElementById('btn-submit-batch')?.addEventListener('click', async () => {
  if (!receiveOrderId) return;
  const mfgDate = document.getElementById('batch-mfg-date').value;
  const expiryDate = document.getElementById('batch-expiry-date').value;
  const rcvQty = document.getElementById('batch-rcv-qty').value;
  
  if (!mfgDate || !expiryDate || rcvQty === '') {
    showToast('Please provide quantity, manufacturing and expiry dates', 'warning');
    return;
  }
  if (expiryDate <= mfgDate) {
    document.getElementById('expiry-date-error').style.display = 'block';
    return;
  }

  const btn = document.getElementById('btn-submit-batch');
  setLoading(btn, true, 'Confirm Receipt');

  try {
    const res = await apiFetch(`/orders/${receiveOrderId}/status`, { 
      method: 'POST',
      body: { 
        status: 'received', 
        mfg_date: mfgDate, 
        expiry_date: expiryDate,
        quantity_received: parseFloat(rcvQty)
      }
    });
    if (res) {
      closeModal('batch-modal');
      showToast('Inventory updated with new batch', 'success');
      loadAllData();
    }
  } catch (err) {
    showToast('Update failed: ' + err.message, 'danger');
  } finally {
    setLoading(btn, false, 'Confirm Receipt');
    receiveOrderId = null;
  }
});

// ── Manual PO Receive modal flow ──
function openReceiveForManual(poId, productName, orderedQty) {
  receivePoId = poId;
  rcvQuality = 0;
  
  const infoEl = document.getElementById('receive-info');
  if (infoEl) infoEl.textContent = `Product: ${productName} | Ordered Qty: ${orderedQty}`;
  
  document.getElementById('f-rcv-qty').value = orderedQty;
  document.getElementById('f-rcv-date').value = new Date().toISOString().slice(0, 10);
  document.getElementById('f-rcv-quality').value = '';
  
  const mfg = document.getElementById('f-rcv-mfg');
  const exp = document.getElementById('f-rcv-expiry');
  const err = document.getElementById('rcv-expiry-error');
  
  const today = new Date().toISOString().split('T')[0];
  if (mfg) mfg.value = today;
  if (exp) exp.value = today;
  if (err) err.style.display = 'none';

  const validateDates = () => {
    if (mfg && exp && err) {
      if (exp.value && mfg.value && exp.value <= mfg.value) {
        err.style.display = 'block';
      } else {
        err.style.display = 'none';
      }
    }
  };
  if (mfg) mfg.oninput = validateDates;
  if (exp) exp.oninput = validateDates;

  renderQualityStars('quality-stars', 0, 'f-rcv-quality', v => { rcvQuality = v; });
  hideMsg(document.getElementById('receive-msg'));
  openModal('receive-modal');
}

document.getElementById('btn-confirm-receive')?.addEventListener('click', async () => {
  const btn  = document.getElementById('btn-confirm-receive');
  const msg  = document.getElementById('receive-msg');
  const qty  = parseFloat(document.getElementById('f-rcv-qty').value);
  const date = document.getElementById('f-rcv-date').value;
  const mfgVal = document.getElementById('f-rcv-mfg').value;
  const expVal = document.getElementById('f-rcv-expiry').value;

  if (!qty || !date) { showError(msg, 'Received qty and date are required.'); return; }
  if (mfgVal && expVal && expVal <= mfgVal) {
    showError(msg, 'Expiry date must be after manufacturing date.');
    return;
  }

  const body = { received_qty: qty, actual_delivery_date: date };
  if (rcvQuality > 0) body.quality_rating = rcvQuality;
  
  setLoading(btn, true, 'Confirm Receipt');
  try {
    // Call manual PO receive
    const res = await apiFetch(`/suppliers/purchase-orders/${receivePoId}/receive`, { method: 'POST', body });
    if (res) {
      // Manual PO update in backend is custom, let's verify if we need to manually update product stock.
      // Yes, suppliers.py receive_po does update inventory_batches and products.csv!
      closeModal('receive-modal');
      showToast('Purchase Order marked as received!', 'success');
      loadAllData();
    }
  } catch (e) { showError(msg, e.message); }
  finally { setLoading(btn, false, 'Confirm Receipt'); }
});

// ── Manual PO creation / edit modal triggers ──
document.getElementById('btn-add-po')?.addEventListener('click', () => {
  editPoId = null;
  document.getElementById('po-modal-title').textContent = 'New Purchase Order';
  document.getElementById('po-form').reset();
  clearProductSelection();
  hideMsg(document.getElementById('po-modal-msg'));
  document.getElementById('f-po-orderdate').value = new Date().toISOString().slice(0, 10);
  openModal('po-modal');
  setTimeout(() => document.getElementById('f-po-product-search').focus(), 50);
});

async function openEdit(poId) {
  const p = allPos.find(x => x.po_id === poId);
  if (!p) return;
  editPoId = poId;
  document.getElementById('po-modal-title').textContent = 'Edit Purchase Order';
  document.getElementById('po-form').reset();
  clearProductSelection();
  hideMsg(document.getElementById('po-modal-msg'));
  
  document.getElementById('f-po-qty').value        = p.ordered_qty;
  document.getElementById('f-po-orderdate').value  = p.order_date;
  document.getElementById('f-po-expdate').value    = p.expected_delivery_date;
  document.getElementById('f-po-notes').value      = p.notes || '';

  const product = allProducts.find(x => x.sku === p.sku) || { sku: p.sku, name: p.product_name || p.sku };
  document.getElementById('f-po-sku').value = product.sku;
  document.getElementById('product-selected-text').textContent = `${product.name} · ${product.sku}`;
  document.getElementById('product-selected').style.display = 'flex';
  document.getElementById('product-hint').textContent = '';

  await loadMappedSuppliers(product.sku);
  if (p.supplier_id) {
    const supSel = document.getElementById('f-po-supplier');
    if (Array.from(supSel.options).some(o => o.value === p.supplier_id)) {
      supSel.value = p.supplier_id;
    }
  }
  openModal('po-modal');
}

document.getElementById('btn-save-po')?.addEventListener('click', async () => {
  const btn = document.getElementById('btn-save-po');
  const msg = document.getElementById('po-modal-msg');
  const sku = document.getElementById('f-po-sku').value.trim();
  const selSupplier = document.getElementById('f-po-supplier');
  const supplier_id = selSupplier.value;
  const supplier_name = supplier_id ? selSupplier.options[selSupplier.selectedIndex].textContent.split(' (Reliability')[0] : '';
  const prodText = document.getElementById('product-selected-text').textContent;
  const product_name = prodText ? prodText.split(' · ')[0] : '';

  const body = {
    supplier_id,
    supplier_name,
    sku,
    product_name,
    ordered_qty:             parseFloat(document.getElementById('f-po-qty').value),
    order_date:              document.getElementById('f-po-orderdate').value,
    expected_delivery_date:  document.getElementById('f-po-expdate').value,
    notes:                   document.getElementById('f-po-notes').value.trim(),
  };

  if (!sku) { showError(msg, 'Please select a product.'); return; }
  if (!supplier_id) { showError(msg, 'Please select a supplier.'); return; }
  if (!body.ordered_qty || !body.order_date || !body.expected_delivery_date) {
    showError(msg, 'Please fill all required fields.'); return;
  }
  if (!mappedSuppliers.some(s => s.supplier_id === supplier_id)) {
    showError(msg, 'Selected supplier is not mapped to this product.'); return;
  }

  setLoading(btn, true, 'Save');
  try {
    if (editPoId) {
      await apiFetch(`/suppliers/purchase-orders/${editPoId}`, { method: 'PUT', body });
    } else {
      await apiFetch('/suppliers/purchase-orders', { method: 'POST', body });
    }
    closeModal('po-modal');
    loadAllData();
  } catch (e) { showError(msg, e.message); }
  finally { setLoading(btn, false, 'Save'); }
});

async function cancelManualPO(poId) {
  const confirmed = await siraConfirm('Cancel this manual purchase order?');
  if (!confirmed) return;
  
  try {
    await apiFetch(`/suppliers/purchase-orders/${poId}/cancel`, { method: 'POST' });
    loadAllData();
    showToast('PO cancelled.', 'success');
  } catch (e) { showToast(e.message, 'error'); }
}

// ── Manual PO Quality Rating modal flow ──
function openRate(poId, productName) {
  ratePoId   = poId;
  rateQuality = 0;
  const infoEl = document.getElementById('rate-info');
  if (infoEl) infoEl.textContent = `Rate quality for: ${productName}`;
  renderQualityStars('rate-stars', 0, 'f-rate-quality', v => { rateQuality = v; });
  openModal('rate-modal');
}

document.getElementById('btn-confirm-rate')?.addEventListener('click', async () => {
  const btn = document.getElementById('btn-confirm-rate');
  if (!rateQuality) { showToast('Please select a rating.', 'info'); return; }
  setLoading(btn, true, 'Save Rating');
  try {
    await apiFetch(`/suppliers/purchase-orders/${ratePoId}/rate`, {
      method: 'POST', body: { quality_rating: rateQuality }
    });
    closeModal('rate-modal');
    loadAllData();
    showToast('Quality rating saved!', 'success');
  } catch (e) { showToast(e.message, 'error'); }
  finally { setLoading(btn, false, 'Save Rating'); }
});

// ── Quality star rating widget helper ──
function renderQualityStars(containerId, selected, hiddenId, onChange) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const spans = container.querySelectorAll('span');
  function update(v) {
    spans.forEach((s, i) => {
      s.textContent = i < v ? '★' : '☆';
      s.style.color = i < v ? '#F59E0B' : '#CBD5E1';
    });
    if (hiddenId) document.getElementById(hiddenId).value = v;
    if (onChange) onChange(v);
  }
  update(selected);
  spans.forEach(s => {
    s.addEventListener('click', () => update(parseInt(s.dataset.v)));
    s.addEventListener('mouseenter', () => {
      spans.forEach((x, i) => {
        x.style.color = i < parseInt(s.dataset.v) ? '#F59E0B' : '#CBD5E1';
      });
    });
    s.addEventListener('mouseleave', () => update(parseInt(document.getElementById(hiddenId)?.value || 0)));
  });
}

// ── Skipped AI decisions edits / undo decisions ──
function toggleSkippedEdit(id) {
  const row = document.getElementById(`edit-row-${id}`);
  if (row) row.style.display = (row.style.display === 'none') ? 'table-row' : 'none';
}

async function saveSkippedEdit(id) {
  const cat = document.getElementById(`edit-cat-${id}`).value;
  const text = document.getElementById(`edit-text-${id}`).value;
  const btn = document.getElementById(`btn-save-${id}`);
  
  setLoading(btn, true, 'Save');
  try {
    await apiFetch(`/orders/${id}/reason`, {
      method: 'POST',
      body: { reason_category: cat, reason_text: text }
    });
    showToast('Reason updated', 'success');
    loadAllData();
  } catch (err) {
    showToast('Update failed: ' + err.message, 'danger');
  } finally {
    setLoading(btn, false, 'Save');
  }
}

async function undoSkippedDecision(orderId, name) {
  const confirmed = await siraConfirm(`Are you sure you want to UNDO the skip decision for ${name}? It will reappear in the Daily Brief.`);
  if (!confirmed) return;

  try {
    // Send status in request BODY (not query string) — backend expects it there
    const res = await apiFetch(`/orders/${orderId}/status`, {
      method: 'POST',
      body: { status: 'cancelled' }
    });
    if (res) {
      showToast('Decision undone — will reappear in Daily Brief.', 'success');
      loadAllData();
    }
  } catch (err) {
    showToast('Failed to undo: ' + err.message, 'danger');
  }
}

// ── Filters & Clean setup ──
document.getElementById('btn-filter')?.addEventListener('click', loadAllData);
document.getElementById('btn-reset')?.addEventListener('click', () => {
  document.getElementById('fil-supplier').value = '';
  document.getElementById('fil-status').value   = '';
  document.getElementById('fil-from').value     = '';
  document.getElementById('fil-to').value       = '';
  loadAllData();
});

document.getElementById('refresh-btn')?.addEventListener('click', () => {
  if (datePicker) {
    datePicker.value = todayStr;
    updateDateText(todayStr);
  }
  loadAllData();
});

// ── Init ──
async function init() {
  await Promise.all([loadSuppliers(), loadProducts()]);
  loadAllData();
}
init();
