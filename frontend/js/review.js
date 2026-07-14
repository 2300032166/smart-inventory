requireRole('manager');
initShell();

let allData = [];

// ── Review Orders page ─────────────────────────────────────────────── v28 ───
// Data source: override_history.json (via /orders/reviewed)
// Shows all manager decisions recorded TODAY: Product, SKU, Decision,
// Suggested qty, Final qty, Timestamp.
// This page is READ-ONLY — decisions are made on the Daily Brief page.
// ─────────────────────────────────────────────────────────────────────────────

const DECISION_LABELS = {
  approved: { label: 'Approved', color: 'var(--color-success)', icon: '✓' },
  overridden: { label: 'Changed Qty', color: 'var(--color-warning)', icon: '✎' },
  skipped: { label: 'Skipped', color: 'var(--color-danger)', icon: '✕' },
};

const datePicker = document.getElementById('date-picker');
const dateText = document.getElementById('review-date');

// Use local date for todayStr (YYYY-MM-DD)
const now = new Date();
const todayStr = [
  now.getFullYear(),
  String(now.getMonth() + 1).padStart(2, '0'),
  String(now.getDate()).padStart(2, '0')
].join('-');

datePicker.value = todayStr;
datePicker.max = todayStr;

function updateDateText(dateStr) {
  if (!dateStr) return;
  const [y, m, d] = dateStr.split('-');
  dateText.textContent = `${d}-${m}-${y}`;
}

updateDateText(todayStr);

datePicker.addEventListener('change', () => {
  updateDateText(datePicker.value);
  loadReviewed();
});

async function loadReviewed() {
  const spinner = document.getElementById('review-spinner');
  const container = document.getElementById('review-list');
  const msg = document.getElementById('msg');
  const summary = document.getElementById('summary-bar');
  hideMsg(msg);
  spinner.style.display = 'flex';
  container.innerHTML = '';

  try {
    // Load decisions for the selected date
    const selectedDate = datePicker.value;
    let items = await apiFetch(`/orders/reviewed?date=${selectedDate}`);
    if (!items) return;

    allData = items;

    // Filter out cancelled/undone decisions so they don't show in the review list
    items = items.filter(i => i.status !== 'cancelled');

    // Filter only approved/overridden orders for lifecycle management
    const lifecycleItems = items.filter(i => i.decision !== 'skipped');
    const skippedItems = items.filter(i => i.decision === 'skipped');

    spinner.style.display = 'none';
    renderSummary(items, summary, selectedDate);
    renderTable(lifecycleItems, container, selectedDate);
    renderSkippedTable(skippedItems, document.getElementById('skipped-list'));
    document.getElementById('skipped-section').style.display = skippedItems.length ? 'block' : 'none';
  } catch (err) {
    spinner.style.display = 'none';
    showError(msg, 'Could not load reviewed orders: ' + err.message);
  }
}

function renderSummary(items, bar) {
  const total = items.length;
  const approved = items.filter(i => i.decision === 'approved').length;
  const overridden = items.filter(i => i.decision === 'overridden').length;
  const skipped = items.filter(i => i.decision === 'skipped').length;

  if (total === 0) {
    bar.innerHTML = '<span style="color:var(--color-text-hint);font-size:13px;">No decisions recorded yet today. Go to <a href="brief.html">Daily Brief</a> to review pending items.</span>';
    return;
  }

  bar.innerHTML = `
    <div class="review-summary-chips">
      <span class="review-chip total">${total} reviewed</span>
      ${approved ? `<span class="review-chip approved">✓ ${approved} approved</span>` : ''}
      ${overridden ? `<span class="review-chip overridden">✎ ${overridden} changed</span>` : ''}
      ${skipped ? `<span class="review-chip skipped">✕ ${skipped} skipped</span>` : ''}
    </div>`;
}

function renderTable(items, container) {
  if (!items.length) {
    container.innerHTML = `
      <div class="card" style="padding:32px;text-align:center;">
        <div style="font-size:36px;margin-bottom:12px;">📋</div>
        <div style="font-size:15px;font-weight:600;margin-bottom:6px;">No decisions yet today</div>
        <div style="font-size:13px;color:var(--color-text-hint);">
          Visit <a href="brief.html" style="color:var(--color-primary);">Daily Brief</a>
          to approve, change, or skip pending replenishment recommendations.
        </div>
      </div>`;
    return;
  }

  container.innerHTML = `
    <div class="card" style="padding:0;overflow:hidden;">
      <div class="table-wrap">
        <table class="review-table">
          <thead>
            <tr>
              <th>Product</th>
              <th>Status</th>
              <th>Approved Qty</th>
              <th>Exp. Arrival</th>
              <th>Rec. Date</th>
              <th>Reason</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${items.map(item => {
              const escapedName = (item.product_name || '').replace(/'/g, "\\'");
              const status = item.status || 'approved';
              const badgeClass = {
                approved: 'badge-info',
                ordered: 'badge-warning',
                received: 'badge-success',
                cancelled: 'badge-gray'
              }[status] || 'badge-low';

              const arrivalDate = item.expected_arrival_date 
                ? new Date(item.expected_arrival_date).toLocaleDateString('en-GB')
                : '—';
              const receivedDate = item.received_date
                ? new Date(item.received_date).toLocaleDateString('en-GB')
                : '—';
              
              const reasonHtml = item.reason_text
                ? `<div class="review-reason">${item.reason_text}</div>`
                : '';

              return `
                <tr>
                   <td>
                    <div class="review-product-name">${item.product_name || '—'}</div>
                    <div class="review-sku-label">${item.sku}</div>
                  </td>
                  <td><span class="badge ${badgeClass}">${status.toUpperCase()}</span></td>
                  <td style="font-weight:700;">${item.actual_qty}</td>
                  <td class="review-time">${arrivalDate}</td>
                  <td class="review-time">${receivedDate}</td>
                  <td>
                    ${item.reason_category ? `<span class="badge badge-gray">${item.reason_category}</span>` : '—'}
                    ${reasonHtml}
                  </td>
                  <td>
                    <div style="display:flex;gap:6px;flex-wrap:wrap;">
                      ${(status === 'approved' || status === 'overridden') ? `<button class="btn btn-primary btn-sm" onclick="updateStatus('${item.id}', 'ordered')">Mark Ordered</button>` : ''}
                      ${status === 'ordered' ? `<button class="btn btn-success btn-sm" onclick="updateStatus('${item.id}', 'received')">Mark Received</button>` : ''}
                      ${item.po_id && status !== 'received' && status !== 'cancelled' ? `<button class="btn btn-change-supplier btn-sm" onclick="openChangeSupplier('${item.po_id}','${item.sku}','${item.supplier_id || ''}','${(item.supplier_name || item.supplier_id || '').replace(/'/g, "\\'")}','${(item.product_name || item.sku || '').replace(/'/g, "\\'")}')">Change Supplier</button>` : ''}
                      ${status === 'cancelled' ? `<button class="btn btn-secondary btn-sm" onclick="updateStatus('${item.id}', 'approved')">Re-activate</button>` : ''}
                      ${status !== 'received' && status !== 'cancelled' ? `<button class="btn btn-ghost btn-sm" onclick="updateStatus('${item.id}', 'cancelled')">Cancel</button>` : ''}
                    </div>
                  </td>
                </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
}

function renderSkippedTable(items, container) {
  if (!items.length) {
    container.innerHTML = '';
    return;
  }

  container.innerHTML = `
    <div class="card" style="padding:0;overflow:hidden;border-top:2px solid var(--color-danger);">
      <div class="table-wrap">
        <table class="review-table">
          <thead>
            <tr>
              <th>Product</th>
              <th>Recommendation</th>
              <th>Skip Reason</th>
              <th>Time</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${items.map(item => {
                const escapedName = (item.product_name || '').replace(/'/g, "\\'");
                return `
                <tr>
                  <td>
                    <div class="review-product-name">${item.product_name || '—'}</div>
                    <div class="review-sku-label">${item.sku}</div>
                  </td>
                  <td><div style="font-size:13px;font-weight:600;">Qty: ${item.ai_suggested_qty}</div></td>
                  <td>
                    ${item.reason_category ? `<span class="badge badge-urgent">${item.reason_category}</span>` : '—'}
                    <div class="review-reason" style="color:var(--color-text-hint);font-style:italic;">"${item.reason_text || 'No reason provided'}"</div>
                  </td>
                  <td class="review-time">${new Date(item.timestamp).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</td>
                  <td>
                    <div style="display:flex;gap:6px;">
                      <button class="btn btn-secondary btn-sm" onclick="toggleEdit('${item.id}')">Edit</button>
                      <button class="btn btn-ghost btn-sm" onclick="undoDecision('${item.id}', '${escapedName}')">Undo</button>
                    </div>
                  </td>
                </tr>
                <tr id="edit-row-${item.id}" style="display:none; background:#fff5f5;">
                  <td colspan="5">
                    <div style="padding:10px; border-left:3px solid var(--color-danger);">
                       <div class="form-row" style="margin-bottom:8px;">
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
                          <div style="display:flex;align-items:flex-end;">
                             <button class="btn btn-danger btn-sm" id="btn-save-${item.id}" onclick="saveEdit('${item.id}')">Save</button>
                          </div>
                       </div>
                    </div>
                  </td>
                </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
}

document.getElementById('refresh-btn').addEventListener('click', () => {
  datePicker.value = todayStr;
  updateDateText(todayStr);
  loadReviewed();
});

loadReviewed();

// ── Custom SIRA Confirmation ────────────────────────────────────────────────
function siraConfirm(msg) {
  return new Promise((resolve) => {
    const modal = document.getElementById('modal-confirm');
    const msgEl = document.getElementById('confirm-message');
    const okBtn = document.getElementById('confirm-ok');
    const cancelBtn = document.getElementById('confirm-cancel');
    
    msgEl.textContent = msg;
    openModal('modal-confirm');
    
    const cleanup = (val) => {
      resolve(val);
      closeModal('modal-confirm');
      // Clean up event listeners to prevent memory leaks or multiple clicks
      okBtn.replaceWith(okBtn.cloneNode(true));
      cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    };
    
    document.getElementById('confirm-ok').addEventListener('click', () => cleanup(true));
    document.getElementById('confirm-cancel').addEventListener('click', () => cleanup(false));
  });
}

let pendingStatusUpdate = null;

async function updateStatus(orderId, status) {
  if (status === 'received') {
    // Show Batch Modal instead of simple confirm
    pendingStatusUpdate = { orderId, status };
    const item = allData.find(i => i.id === orderId);
    document.getElementById('batch-product-info').textContent = `${item ? item.product_name : 'Product'} (Qty: ${item ? item.actual_qty : '—'})`;
    
    // Set default dates — both default to today
    const today = new Date().toISOString().split('T')[0];
    
    document.getElementById('batch-mfg-date').value = today;
    document.getElementById('batch-expiry-date').value = today;
    document.getElementById('expiry-date-error').style.display = 'none';

    // Real-time validation: show error if expiry <= mfg
    const expiryInput = document.getElementById('batch-expiry-date');
    const mfgInput = document.getElementById('batch-mfg-date');
    const validateDates = () => {
      const err = document.getElementById('expiry-date-error');
      if (expiryInput.value && mfgInput.value && expiryInput.value <= mfgInput.value) {
        err.style.display = 'block';
      } else {
        err.style.display = 'none';
      }
    };
    expiryInput.oninput = validateDates;
    mfgInput.oninput = validateDates;
    
    openModal('modal-batch-details');
    return;
  }

  const confirmed = await siraConfirm(`Mark this decision as ${status.toUpperCase()}?`);
  if (!confirmed) return;
  
  try {
    const res = await apiFetch(`/orders/${orderId}/status`, { 
      method: 'POST',
      body: { status: status }
    });
    if (res) loadReviewed();
  } catch (err) {
    showToast('Update failed: ' + err.message, 'danger');
  }
}

document.getElementById('btn-submit-batch').addEventListener('click', async () => {
    if (!pendingStatusUpdate) return;
    const { orderId, status } = pendingStatusUpdate;
    const mfgDate = document.getElementById('batch-mfg-date').value;
    const expiryDate = document.getElementById('batch-expiry-date').value;
    
    if (!mfgDate || !expiryDate) {
        showToast('Please provide both dates', 'warning');
        return;
    }

    if (expiryDate <= mfgDate) {
        document.getElementById('expiry-date-error').style.display = 'block';
        return;
    }
    document.getElementById('expiry-date-error').style.display = 'none';

    const btn = document.getElementById('btn-submit-batch');
    setLoading(btn, true, 'Confirm Receipt');

    try {
        const res = await apiFetch(`/orders/${orderId}/status`, { 
            method: 'POST',
            body: { 
                status: status, 
                mfg_date: mfgDate, 
                expiry_date: expiryDate 
            }
        });
        if (res) {
            closeModal('modal-batch-details');
            showToast('Inventory updated with new batch', 'success');
            loadReviewed();
        }
    } catch (err) {
        showToast('Update failed: ' + err.message, 'danger');
    } finally {
        setLoading(btn, false, 'Confirm Receipt');
        pendingStatusUpdate = null;
    }
});

async function undoDecision(orderId, name) {
  const confirmed = await siraConfirm(`Are you sure you want to UNDO the decision for ${name}? It will reappear in the Daily Brief.`);
  if (!confirmed) return;

  try {
    const res = await apiFetch(`/orders/${orderId}/status?status=cancelled`, { method: 'POST' });
    if (res) {
      showToast('Decision undone.', 'success');
      loadReviewed();
    }
  } catch (err) {
    showToast('Failed to undo: ' + err.message, 'danger');
  }
}

function toggleEdit(id) {
  const row = document.getElementById(`edit-row-${id}`);
  if (row) row.style.display = (row.style.display === 'none') ? 'table-row' : 'none';
}

async function saveEdit(id) {
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
    loadReviewed();
  } catch (err) {
    showToast('Update failed: ' + err.message, 'danger');
  } finally {
    setLoading(btn, false, 'Save');
  }
}

let changePoId = null;

async function loadMappedSuppliersForReview(sku, currentSupplierId) {
  const sel = document.getElementById('f-chg-supplier');
  sel.innerHTML = '<option value="">Loading suppliers...</option>';
  try {
    const data = await apiFetch(`/suppliers/product/${encodeURIComponent(sku)}/suppliers`);
    if (!data || !data.length) {
      sel.innerHTML = '<option value="">No mapped suppliers</option>';
      return;
    }
    sel.innerHTML = '';
    data.filter(s => s.status !== 'Inactive').forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.supplier_id;
      opt.textContent = `${s.name} (reliability ${s.reliability_score})`;
      if (s.supplier_id === currentSupplierId) opt.selected = true;
      sel.appendChild(opt);
    });
  } catch (e) {
    sel.innerHTML = '<option value="">Failed to load suppliers</option>';
    console.error(e);
  }
}

function openChangeSupplier(poId, sku, currentSupplierId, currentSupplierName, productName) {
  changePoId = poId;
  document.getElementById('change-supplier-info').textContent =
    `Product: ${productName} | Current supplier: ${currentSupplierName}`;
  hideMsg(document.getElementById('change-supplier-msg'));
  loadMappedSuppliersForReview(sku, currentSupplierId);
  openModal('modal-change-supplier');
}

document.getElementById('btn-confirm-change-supplier').addEventListener('click', async () => {
  const btn = document.getElementById('btn-confirm-change-supplier');
  const msg = document.getElementById('change-supplier-msg');
  const sel = document.getElementById('f-chg-supplier');
  const supplierId = sel.value;
  if (!supplierId) { showError(msg, 'Please select a supplier.'); return; }
  const supplierName = sel.options[sel.selectedIndex].textContent.split(' (reliability')[0];
  setLoading(btn, true, 'Update Supplier');
  try {
    await apiFetch(`/suppliers/purchase-orders/${changePoId}`, {
      method: 'PUT',
      body: { supplier_id: supplierId, supplier_name: supplierName }
    });
    closeModal('modal-change-supplier');
    loadReviewed();
    showToast('Supplier updated', 'success');
  } catch (e) { showError(msg, e.message); }
  finally { setLoading(btn, false, 'Update Supplier'); }
});
