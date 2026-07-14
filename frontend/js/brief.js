requireRole('manager');
initShell();

let allItems = [];
const decided = new Map();
let isHistoryMode = false;
let skipModalData = null;
let briefPollTimer = null;

const dateEl = document.getElementById('brief-date');
const picker = document.getElementById('date-picker');

const now = new Date();
const todayStr = [
  now.getFullYear(),
  String(now.getMonth() + 1).padStart(2, '0'),
  String(now.getDate()).padStart(2, '0')
].join('-');

picker.value = todayStr;
picker.max = todayStr;

function updateDateText(dateStr) {
  if (!dateStr) return;
  const [y, m, d] = dateStr.split('-');
  dateEl.textContent = `${d}-${m}-${y}`;
}
updateDateText(todayStr);

picker.addEventListener('change', () => {
  isHistoryMode = picker.value !== todayStr;
  updateDateText(picker.value);
  loadBrief();
});

document.getElementById('refresh-btn').addEventListener('click', () => {
  picker.value = todayStr;
  updateDateText(todayStr);
  isHistoryMode = false;
  decided.clear();
  clearTimeout(briefPollTimer);
  loadBrief(true);
});

async function loadBrief(force = false, isPolling = false) {
  const spinner = document.getElementById('brief-spinner');
  const list = document.getElementById('brief-list');
  const msg = document.getElementById('msg');
  if (!isPolling) {
    hideMsg(msg);
    spinner.style.display = 'flex';
    list.innerHTML = '';
  }
  try {
    let items;
    if (isHistoryMode) {
      items = await apiFetch(`/brief/history?date=${picker.value}`);
    } else {
      items = await apiFetch(`/brief/pending?force=${force}&_t=${Date.now()}`);
    }
    if (!items) return;

    // If polling, only update the AI reasoning text in-place to avoid
    // collapsing any open "Change Qty" / "Skip" panels
    if (isPolling) {
      const prev = allItems;
      allItems = items;
      items.forEach(item => {
        const prevItem = prev.find(p => p.sku === item.sku);
        // Update AI reasoning text only when it changes
        if (prevItem && prevItem.ai_status !== item.ai_status) {
          const card = document.getElementById(`card-${item.sku}`);
          if (!card) return;
          const aiSpan = card.querySelector('.ai-box > span:last-child');
          if (!aiSpan) return;
          let explanation = item.ai_reasoning;
          if (!explanation || explanation.toLowerCase().includes('failed')) {
            explanation = (item.drivers?.natural_explanation) ||
              `Reorder suggested: ${item.recommended_qty} ${item.unit} for ${item.product_name}.`;
          }
          if (item.ai_status === 'loading') {
            aiSpan.innerHTML = `<span>${explanation}</span> <span style="font-size:0.85em;color:var(--color-primary);padding-left:4px;">(AI generating...)</span>`;
          } else {
            aiSpan.innerHTML = `<span>${explanation}</span>`;
          }
        }
      });
      updateProgress();
      clearTimeout(briefPollTimer);
      if (!isHistoryMode && allItems.some(i => i.ai_status === 'loading')) {
        briefPollTimer = setTimeout(() => loadBrief(false, true), 3000);
      }
      return;
    }

    allItems = items;
    spinner.style.display = 'none';
    renderBrief();
    updateProgress();

    clearTimeout(briefPollTimer);
    if (!isHistoryMode && allItems.some(item => item.ai_status === 'loading')) {
      briefPollTimer = setTimeout(() => loadBrief(false, true), 3000);
    }
  } catch (err) {
    spinner.style.display = 'none';
    showError(msg, 'Could not load brief: ' + err.message);
  }
}

function updateProgress() {
  const total = allItems.length;
  const done = decided.size;
  const card = document.getElementById('progress-card');
  const text = document.getElementById('progress-text');
  const fill = document.getElementById('progress-fill');
  card.style.display = 'block';
  if (isHistoryMode) {
    text.textContent = `${total} items in brief`;
    fill.style.width = '100%';
  } else {
    text.textContent = total === 0
      ? '✓ All items reviewed for today'
      : `${total} item${total !== 1 ? 's' : ''} pending review`;
    fill.style.width = total === 0 ? '100%' : `${Math.round((done / (total + done)) * 100)}%`;
  }
}

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function getSelectedSupplierForSku(sku) {
  const sel = document.getElementById(`supplier-${sku}`);
  if (sel) {
    const opt = sel.options[sel.selectedIndex];
    return { id: sel.value, name: opt?.dataset?.name || opt?.textContent || '' };
  }
  const item = allItems.find(i => i.sku === sku);
  return { id: item?.recommended_supplier_id || '', name: item?.recommended_supplier_name || '' };
}

function updateSupplierName(sku) {
  const sel = document.getElementById(`supplier-${sku}`);
  const opt = sel?.options?.[sel.selectedIndex];
  const nameEl = document.getElementById(`supplier-name-${sku}`);
  if (nameEl && opt) nameEl.textContent = opt.dataset.name || opt.textContent;
}

function toggleSupplierExpand(sku) {
  document.getElementById(`supplier-expand-${sku}`)?.classList.toggle('open');
}

function renderBrief() {
  const list = document.getElementById('brief-list');

  // ── Preserve expand states + form values before re-rendering ──
  const savedQtyOpen = new Set();
  const savedSkipOpen = new Set();
  const savedSupplierOpen = new Set();
  const savedVals = {};
  allItems.forEach(({ sku }) => {
    if (document.getElementById(`expand-${sku}`)?.classList.contains('open')) savedQtyOpen.add(sku);
    if (document.getElementById(`skip-expand-${sku}`)?.classList.contains('open')) savedSkipOpen.add(sku);
    if (document.getElementById(`supplier-expand-${sku}`)?.classList.contains('open')) savedSupplierOpen.add(sku);
    savedVals[sku] = {
      qty:       document.getElementById(`qty-${sku}`)?.value         || '',
      reasonCat: document.getElementById(`reason-cat-${sku}`)?.value  || '',
      reasonText:document.getElementById(`reason-${sku}`)?.value      || '',
      skipCat:   document.getElementById(`skip-cat-${sku}`)?.value    || '',
      skipNotes: document.getElementById(`skip-notes-${sku}`)?.value  || '',
      supplierId:document.getElementById(`supplier-${sku}`)?.value    || '',
    };
  });

  if (!allItems.length) {
    if (isHistoryMode) {
      list.innerHTML = '<div class="card" style="font-size:13px;color:var(--color-text-hint);padding:24px;">No recommendations found for this date.</div>';
    } else {
      list.innerHTML = '<div class="card" style="font-size:13px;color:var(--color-success);padding:24px;">✓ All items have been reviewed today. Check <a href="purchase-orders.html">Procurement Orders</a> to see decisions.</div>';
    }
    return;
  }

  list.innerHTML = allItems.map(item => {
    const d = decided.get(item.sku);
    const isCritical = item.days_remaining < item.lead_time_days;
    const escapedName = (item.product_name || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");

    const drivers = item.drivers || { primary: null, supporting: [], natural_explanation: '' };
    let driverHtml = '';
    if (drivers.primary) {
      const dr = drivers.primary;
      driverHtml = `<span class="driver-badge ${getDriverClass(dr.id)}" style="margin-left:8px;">${getDriverIcon(dr.id)} ${dr.name}</span>`;
    }
    const supportingBadges = (drivers.supporting || []).map(id => {
      const name = id.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
      return `<span class="driver-badge ${getDriverClass(id)}" style="font-size:10px;margin-right:4px;opacity:0.8;">${getDriverIcon(id)} ${name}</span>`;
    }).join('');

    let explanation = item.ai_reasoning;
    if (!explanation || explanation.toLowerCase().includes('failed')) {
      explanation = drivers.natural_explanation || `Reorder suggested: ${item.recommended_qty} ${item.unit} for ${item.product_name}.`;
    }
    const explanationHtml = item.ai_status === 'loading'
      ? `<span>${explanation}</span> <span style="font-size: 0.85em; color: var(--color-primary); padding-left: 4px;">(AI generating...)</span>`
      : `<span>${explanation}</span>`;

    const deliveryHtml = item.delivery_date
      ? `<div class="rec-meta-item" style="color:#0891b2;font-weight:600;">Expected Arrival: <strong>${formatDate(item.delivery_date)}</strong></div>`
      : '';

    let supplierHtml = '';
    const mapped = item.mapped_suppliers || [];
    if (mapped.length) {
      const canChange = mapped.length > 1;
      const options = mapped.map(s => {
        const selected = s.supplier_id === item.recommended_supplier_id ? ' selected' : '';
        const reasons = (s.reasons || []).join(', ');
        return `<option value="${escapeHtml(s.supplier_id)}" data-name="${escapeHtml(s.name)}"${selected}>${escapeHtml(s.name)} — reliability ${s.reliability_score}${reasons ? ` (${reasons})` : ''}</option>`;
      }).join('');
      supplierHtml = `
        <div class="rec-meta-item supplier-change-row">Recommended supplier: <span class="supplier-name" id="supplier-name-${item.sku}">${escapeHtml(item.recommended_supplier_name) || '—'}</span>${canChange ? ` <button class="btn btn-ghost btn-sm" onclick="toggleSupplierExpand('${item.sku}')">Change supplier</button>` : ''}</div>
        ${canChange ? `<div class="rec-expand supplier-expand" id="supplier-expand-${item.sku}"><div class="form-group"><label>Select supplier</label><select id="supplier-${item.sku}" class="supplier-select" onchange="updateSupplierName('${item.sku}')">${options}</select></div></div>` : ''}
      `;
    } else {
      supplierHtml = `<div class="rec-meta-item" style="color:var(--color-text-hint);">Supplier: No mapped suppliers</div>`;
    }

    const actionsHtml = d
      ? `<div class="rec-decided" style="color:${d === 'approved' ? 'var(--color-success)' : d === 'skipped' ? 'var(--color-danger)' : 'var(--color-warning)'}">✓ Decision recorded: ${d}</div>`
      : isHistoryMode
        ? '<div class="text-muted" style="font-size:13px;">Past brief — read only</div>'
        : `<div class="rec-actions">
             <button class="btn btn-success btn-sm" onclick="approveWithSupplier('${item.sku}','${escapedName}',${item.recommended_qty})">✓ Approve</button>
             <button class="btn btn-secondary btn-sm" onclick="toggleExpand('${item.sku}')">Change quantity</button>
             <button class="btn btn-danger btn-sm" onclick="toggleSkipExpand('${item.sku}')">✕ Skip</button>
           </div>
           <div class="rec-expand" id="expand-${item.sku}">
             <div class="form-row" style="margin-bottom:10px;">
               <div class="form-group" style="margin-bottom:0;">
                 <label>New quantity</label>
                 <input type="number" id="qty-${item.sku}" value="${item.recommended_qty}" min="0">
               </div>
               <div class="form-group" style="margin-bottom:0;">
                 <label>Reason category</label>
                 <select id="reason-cat-${item.sku}">
                   <option>Seasonal adjustment</option>
                   <option>Supplier issue</option>
                   <option>Budget constraint</option>
                   <option>Overstock risk</option>
                   <option>Other</option>
                 </select>
               </div>
             </div>
             <div class="form-group">
               <label>Additional notes</label>
               <textarea id="reason-${item.sku}" rows="2" placeholder="Why are you changing the quantity?"></textarea>
             </div>
             <button class="btn btn-primary btn-sm" onclick="submitOverride('${item.sku}','${escapedName}',${item.recommended_qty})">Confirm order</button>
           </div>
           <div class="rec-expand" id="skip-expand-${item.sku}">
             <div class="form-group">
               <label>Reason for skipping <span style="color:var(--color-danger)">*</span></label>
               <select id="skip-cat-${item.sku}">
                 <option value="">Select a reason...</option>
                 <option>Inventory suffice</option>
                 <option>Budget limited</option>
                 <option>Supplier unavailable</option>
                 <option>Market trend change</option>
                 <option>Other</option>
               </select>
             </div>
             <div class="form-group">
               <label>Additional notes (Optional)</label>
               <textarea id="skip-notes-${item.sku}" rows="2" placeholder="Optional notes..."></textarea>
             </div>
             <button class="btn btn-danger btn-sm" id="btn-skip-${item.sku}" onclick="submitSkip('${item.sku}','${escapedName}',${item.recommended_qty})">Confirm Skip</button>
           </div>`;

    return `<div class="rec-card" id="card-${item.sku}">
      <div class="rec-card-header">
        <div>
          <div class="rec-card-title">${item.product_name} ${driverHtml}</div>
          <div class="rec-card-sku">${item.sku} &bull; <span class="badge badge-gray">${item.category}</span></div>
          <div style="margin-top:6px;">${supportingBadges}</div>
        </div>
        ${urgencyBadge(item.urgency, item.risk_level)}
      </div>
      <div class="rec-meta">
        <div class="rec-meta-item">Current stock: <strong>${item.current_stock} ${item.unit}</strong></div>
        <div class="rec-meta-item">Avg daily: <strong>${item.avg_daily_sales} ${item.unit}/day</strong></div>
        <div class="rec-meta-item ${isCritical ? 'critical' : ''}">Days remaining: <strong>${item.days_remaining}</strong></div>
        <div class="rec-meta-item">Lead time: <strong>${item.lead_time_days} days</strong></div>
        <div class="rec-meta-item">Suggested: <strong>${item.recommended_qty} ${item.unit}</strong></div>
        ${deliveryHtml}
        ${supplierHtml}
      </div>
      <div class="ai-box mb-16"><span class="ai-box-icon">💡</span><span>${explanationHtml}</span></div>
      ${actionsHtml}
    </div>`;
  }).join('');

  // ── Restore expand states and input values ──
  savedQtyOpen.forEach(sku => {
    document.getElementById(`expand-${sku}`)?.classList.add('open');
    const v = savedVals[sku] || {};
    const qEl = document.getElementById(`qty-${sku}`);
    const rcEl = document.getElementById(`reason-cat-${sku}`);
    const rtEl = document.getElementById(`reason-${sku}`);
    if (qEl  && v.qty)        qEl.value  = v.qty;
    if (rcEl && v.reasonCat)  rcEl.value = v.reasonCat;
    if (rtEl && v.reasonText) rtEl.value = v.reasonText;
  });
  savedSkipOpen.forEach(sku => {
    document.getElementById(`skip-expand-${sku}`)?.classList.add('open');
    const v = savedVals[sku] || {};
    const scEl = document.getElementById(`skip-cat-${sku}`);
    const snEl = document.getElementById(`skip-notes-${sku}`);
    if (scEl && v.skipCat)   scEl.value = v.skipCat;
    if (snEl && v.skipNotes) snEl.value = v.skipNotes;
  });
  savedSupplierOpen.forEach(sku => {
    document.getElementById(`supplier-expand-${sku}`)?.classList.add('open');
    const v = savedVals[sku] || {};
    if (v.supplierId) {
      const supEl = document.getElementById(`supplier-${sku}`);
      if (supEl) supEl.value = v.supplierId;
    }
  });
}

function toggleExpand(sku) {
  // Close skip and supplier sections if open
  document.getElementById(`skip-expand-${sku}`)?.classList.remove('open');
  document.getElementById(`supplier-expand-${sku}`)?.classList.remove('open');
  document.getElementById(`expand-${sku}`)?.classList.toggle('open');
}

function toggleSkipExpand(sku) {
  // Close quantity and supplier sections if open
  document.getElementById(`expand-${sku}`)?.classList.remove('open');
  document.getElementById(`supplier-expand-${sku}`)?.classList.remove('open');
  document.getElementById(`skip-expand-${sku}`)?.classList.toggle('open');
}

function approveWithSupplier(sku, name, qty) {
  const sup = getSelectedSupplierForSku(sku);
  decide(sku, name, qty, 'approved', qty, '', '', sup.id, sup.name);
}

async function submitSkip(sku, name, aiQty) {
  const cat = document.getElementById(`skip-cat-${sku}`)?.value || '';
  const text = document.getElementById(`skip-notes-${sku}`)?.value || '';
  const btn = document.getElementById(`btn-skip-${sku}`);

  if (!cat) { alert('Please select a reason category.'); return; }
  
  setLoading(btn, true, 'Confirm Skip');
  try {
    await decide(sku, name, aiQty, 'skipped', 0, cat, text);
    showToast('Skipped ' + name, 'info');
  } finally {
    setLoading(btn, false, 'Confirm Skip');
  }
}

async function decide(sku, name, aiQty, decision, actualQty, reasonCat, reasonText, supplierId, supplierName) {
  reasonCat  = reasonCat  || '';
  reasonText = reasonText || '';
  try {
    const res = await apiFetch('/orders/decide', {
      method: 'POST',
      body: {
        sku,
        product_name: name,
        decision,
        ai_suggested_qty: aiQty,
        actual_qty: actualQty,
        reason_category: reasonCat,
        reason_text: reasonText,
        supplier_id: supplierId || '',
        supplier_name: supplierName || '',
      }
    });
    decided.set(sku, decision);
    allItems = allItems.filter(i => i.sku !== sku);
    renderBrief();
    updateProgress();
    if (res && res.po) {
      showToast(`${decision === 'approved' ? 'Approved' : 'Confirmed'} ${name} — PO ${res.po.po_number} created`, 'success');
    } else if (decision !== 'skipped') {
      showToast(`${decision === 'approved' ? 'Approved' : 'Confirmed'} ${name}`, 'success');
    }
  } catch (err) {
    showError(document.getElementById('msg'), err.message);
  }
}

async function submitOverride(sku, name, aiQty) {
  const qty       = parseFloat(document.getElementById(`qty-${sku}`)?.value || 0);
  const reasonCat = document.getElementById(`reason-cat-${sku}`)?.value || '';
  const reasonText= document.getElementById(`reason-${sku}`)?.value || '';
  const sup       = getSelectedSupplierForSku(sku);
  await decide(sku, name, aiQty, qty === aiQty ? 'approved' : 'overridden', qty, reasonCat, reasonText, sup.id, sup.name);
}

function getDriverIcon(id) {
  id = (id || '').toLowerCase();
  if (id.includes('risk') || id.includes('stockout')) return '⚠️';
  if (id.includes('weather')) return '🌡️';
  if (id.includes('seasonal')) return '📅';
  if (id.includes('payday')) return '💰';
  if (id.includes('weekend')) return '🏠';
  if (id.includes('trend')) return '📈';
  return '🔹';
}

function getDriverClass(id) {
  id = (id || '').toLowerCase();
  if (id.includes('risk') || id.includes('breach') || id.includes('stockout')) return 'db-danger';
  if (id.includes('weather') || id.includes('seasonal')) return 'db-warning';
  if (id.includes('payday') || id.includes('weekend') || id.includes('trend')) return 'db-info';
  return 'db-primary';
}

loadBrief();
