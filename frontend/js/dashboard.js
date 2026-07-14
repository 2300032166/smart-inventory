requireRole('manager');
initShell();

document.getElementById('today-date').textContent = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

let allItems = [];
const decided = new Set();
let briefPollTimer = null;

function escapeHtml(str) {
  return String(str || '')
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

async function loadStats() {
  try {
    const d = await apiFetch(`/sales/summary?t=${Date.now()}`);
    if (!d) return;
    document.getElementById('stat-risk').textContent = d.stockout_risk ?? '—';
    document.getElementById('stat-orders').textContent = d.orders_this_week ?? '—';
    document.getElementById('stat-accuracy').textContent = d.ai_accuracy_pct != null ? d.ai_accuracy_pct + '%' : '—';
  } catch {}
}

async function loadDeadStock() {
  const card = document.getElementById('dead-stock-card');
  try {
    const d = await apiFetch(`/dead-stock/analysis?t=${Date.now()}`);
    if (!d || !d.summary) return;
    
    if (d.summary.dead_items > 0 || d.summary.slow_items > 0) {
      card.style.display = 'block';
      document.getElementById('ds-items').textContent = d.summary.dead_items;
      document.getElementById('ds-slow').textContent = d.summary.slow_items;
      document.getElementById('ds-value').textContent = '₹' + d.summary.value_locked.toLocaleString('en-IN');
      document.getElementById('ds-oldest').textContent = d.summary.oldest_days + ' Days';
    } else {
      card.style.display = 'none';
    }
  } catch (err) {
    console.error('Dead stock load fail', err);
    card.style.display = 'none';
  }
}

async function loadBrief(force = false) {
  const spinner = document.getElementById('rec-spinner');
  const list = document.getElementById('rec-list');
  try {
    const items = await apiFetch(`/brief/pending?force=${force}&t=${Date.now()}`);
    if (!items) return;
    document.getElementById('stat-pending').textContent = items.length;
    allItems = items.slice(0, 3);
    spinner.style.display = 'none';
    renderCards();
    
    clearTimeout(briefPollTimer);
    if (allItems.some(item => item.ai_status === 'loading')) {
      briefPollTimer = setTimeout(() => loadBrief(false), 3000);
    }
  } catch (err) {
    spinner.style.display = 'none';
    showError(document.getElementById('msg'), 'Could not load brief: ' + err.message);
  }
}

function toggleExpand(sku) {
  document.getElementById(`skip-expand-${sku}`)?.classList.remove('open');
  document.getElementById(`expand-${sku}`)?.classList.toggle('open');
}

function toggleSkipExpand(sku) {
  document.getElementById(`expand-${sku}`)?.classList.remove('open');
  document.getElementById(`skip-expand-${sku}`)?.classList.toggle('open');
}

async function decide(sku, name, aiQty, decision, actualQty, reasonCat = '', reasonText = '') {
  const supplier = getSelectedSupplierForSku(sku);
  try {
    await apiFetch('/orders/decide', {
      method: 'POST',
      body: { sku, product_name: name, decision, ai_suggested_qty: aiQty, actual_qty: actualQty, reason_category: reasonCat, reason_text: reasonText, supplier_id: supplier.id, supplier_name: supplier.name }
    });
    decided.add(sku);
    renderCards();
    loadStats();
  } catch (err) {
    showError(document.getElementById('msg'), err.message);
  }
}

async function submitOverride(sku, name, aiQty) {
  const qty = parseFloat(document.getElementById(`qty-${sku}`)?.value || 0);
  const reasonCat = document.getElementById(`reason-cat-${sku}`)?.value || '';
  const reasonText = document.getElementById(`reason-${sku}`)?.value || '';
  const decision = qty === aiQty ? 'approved' : 'overridden';
  await decide(sku, name, aiQty, decision, qty, reasonCat, reasonText);
}

async function submitSkip(sku, name, aiQty) {
  const cat = document.getElementById(`skip-cat-${sku}`)?.value || '';
  const text = document.getElementById(`skip-notes-${sku}`)?.value || '';
  const btn = document.getElementById(`btn-skip-${sku}`);

  if (!cat) { alert('Please select a reason category.'); return; }
  
  setLoading(btn, true, 'Confirm Skip');
  try {
    await decide(sku, name, aiQty, 'skipped', 0, cat, text);
    showToast(`Skipped ${name}`, 'info');
  } finally {
    setLoading(btn, false, 'Confirm Skip');
  }
}

async function loadAlerts() {
  try {
    const alerts = await apiFetch('/alerts');
    if (!alerts) return;
    const list = document.getElementById('alerts-list');
    const unread = alerts.filter(a => !a.is_read).slice(0, 3);
    if (!unread.length) { list.innerHTML = '<div style="font-size:13px;color:var(--color-text-hint);">No unread alerts.</div>'; return; }
    const iconMap = { stockout: '🔴', info: '🔵', success: '🟢', system: '⚪' };
    list.innerHTML = unread.map(a => `
      <div class="activity-item">
        <span style="font-size:16px;">${iconMap[a.type] || '⚪'}</span>
        <span class="activity-desc"><strong>${a.title}</strong> — ${a.message}</span>
        <span class="activity-time">${timeAgo(a.created_at)}</span>
      </div>`).join('');
  } catch {}
}

async function loadWeather() {
  const container = document.getElementById('weather-container');
  const section = document.getElementById('weather-section');
  try {
    const forecast = await apiFetch('/weather/forecast');
    if (!forecast || !forecast.length) {
      container.innerHTML = '<div class="weather-loading">Weather data temporarily unavailable. Please refresh.</div>';
      section.style.display = '';
      return;
    }
    section.style.display = '';

    const today = new Date().toDateString();

    function getTempClass(temp) {
      if (temp > 38) return 'hot';
      if (temp > 34) return 'warm';
      if (temp < 15) return 'cool';
      return 'moderate';
    }

    container.innerHTML = forecast.map((day, i) => {
      const dateObj = new Date(day.date);
      const isToday = dateObj.toDateString() === today;
      const dayLabel = isToday ? 'Today' : dateObj.toLocaleDateString('en-GB', { weekday: 'short' });
      const tempClass = getTempClass(day.max_temp);
      const precipText = day.precip > 0 ? `💧 ${day.precip.toFixed(1)}mm` : '☀️ Dry';
      return `
        <div class="weather-day${isToday ? ' today' : ''}" style="animation-delay:${i * 0.06}s">
          <div class="weather-day-name">${dayLabel}</div>
          <div class="weather-day-icon">${getWeatherIcon(day.code, day.max_temp)}</div>
          <div class="weather-day-desc">${getWeatherDesc(day.code, day.max_temp)}</div>
          <div class="weather-temp ${tempClass}">${Math.round(day.max_temp)}°C</div>
          <div class="weather-precip">${precipText}</div>
        </div>`;
    }).join('');
  } catch (err) {
    console.error('Weather load fail', err);
    section.style.display = '';
    container.innerHTML = '<div class="weather-error">⚠️ Error loading weather insights.</div>';
  }
}


function renderCards() {
  const list = document.getElementById('rec-list');
  if (!allItems.length) {
    list.innerHTML = '<div class="card text-muted" style="font-size:13px;padding:24px;">No recommendations pending. All products are well stocked.</div>';
    return;
  }

  list.innerHTML = allItems.map((item, i) => {
    const isDone = decided.has(item.sku);
    
    const deliveryHtml = item.delivery_date ? `<div class="rec-meta-item" style="color: #0891b2; font-weight: 600;">Arrives: <strong>${formatDate(item.delivery_date)}</strong></div>` : '';

    const drivers = item.drivers || { primary: null, supporting: [], natural_explanation: "" };
    let driverHtml = '';
    
    if (drivers.primary) {
        const d = drivers.primary;
        driverHtml += `<span class="driver-badge ${getDriverClass(d.id)}" style="margin-left:8px;">${d.name}</span>`;
    }
    
    const supportingBadges = drivers.supporting.map(id => {
        const name = id.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
        return `<span class="driver-badge ${getDriverClass(id)}" style="font-size:10px; margin-right:4px; opacity:0.8;">${name}</span>`;
    }).join('');

    let explanation = item.ai_reasoning;
    if (!explanation || explanation.toLowerCase().includes('failed')) {
        explanation = item.drivers?.natural_explanation || `Inventory check: Stock is low for ${item.product_name}. Recommend reordering to maintain shelf availability.`;
    }
    const explanationHtml = item.ai_status === 'loading'
        ? `<span>${explanation}</span> <span style="font-size: 0.85em; color: var(--color-primary); padding-left: 4px;">(AI generating...)</span>`
        : `<span>${explanation}</span>`;
    const escapedName = item.product_name.replace(/'/g, "\\'");

    let supplierHtml = '';
    const mapped = item.mapped_suppliers || [];
    if (mapped.length) {
      const canChange = mapped.length > 1;
      const options = mapped.map(s => {
        const selected = s.supplier_id === item.recommended_supplier_id ? ' selected' : '';
        return `<option value="${escapeHtml(s.supplier_id)}" data-name="${escapeHtml(s.name)}"${selected}>${escapeHtml(s.name)} — reliability ${s.reliability_score}</option>`;
      }).join('');
      supplierHtml = `
        <div class="rec-meta-item supplier-change-row">Supplier: <span class="supplier-name" id="supplier-name-${item.sku}">${escapeHtml(item.recommended_supplier_name) || '—'}</span>${canChange ? ` <button class="btn btn-ghost btn-sm" onclick="toggleSupplierExpand('${item.sku}')">Change</button>` : ''}</div>
        ${canChange ? `<div class="rec-expand supplier-expand" id="supplier-expand-${item.sku}"><div class="form-group"><label>Select supplier</label><select id="supplier-${item.sku}" class="supplier-select" onchange="updateSupplierName('${item.sku}')">${options}</select></div></div>` : ''}
      `;
    } else {
      supplierHtml = `<div class="rec-meta-item" style="color:var(--color-text-hint);">Supplier: No mapped suppliers</div>`;
    }

    return `
    <div class="rec-card" id="card-${item.sku}">
      <div class="rec-card-header">
        <div>
            <div class="rec-card-title">${item.product_name} ${driverHtml}</div>
            <div class="rec-card-sku">${item.sku} &bull; ${item.category}</div>
            <div style="margin-top:6px;">${supportingBadges}</div>
        </div>
        ${urgencyBadge(item.urgency, item.risk_level)}
      </div>
      <div class="rec-meta">
        <div class="rec-meta-item">Stock: <strong>${item.current_stock} ${item.unit}</strong></div>
        <div class="rec-meta-item">Lead Time: <strong>${item.lead_time_days}d</strong></div>
        <div class="rec-meta-item ${item.days_remaining < item.lead_time_days ? 'critical' : ''}">
          Days left: <strong>${item.days_remaining}</strong></div>
        <div class="rec-meta-item">Suggested qty: <strong>${item.recommended_qty}</strong></div>
        ${deliveryHtml}
        ${supplierHtml}
      </div>
      <div class="ai-box">
        <span class="ai-box-icon">💡</span>
        <div>
            ${explanationHtml}
        </div>
      </div>
      ${isDone ? `<div class="rec-decided text-success">✓ Decision recorded</div>` : `
      <div class="rec-actions">
        <button class="btn btn-success btn-sm" onclick="decide('${item.sku}','${escapedName}',${item.recommended_qty},'approved',${item.recommended_qty})">Approve</button>
        <button class="btn btn-secondary btn-sm" onclick="toggleExpand('${item.sku}')">Change qty</button>
        <button class="btn btn-danger btn-sm" onclick="toggleSkipExpand('${item.sku}')">Skip</button>
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
              <option value="Seasonal adjustment">Seasonal adjustment</option>
              <option value="Supplier issue">Supplier issue</option>
              <option value="Budget constraint">Budget constraint</option>
              <option value="Overstock risk">Overstock risk</option>
              <option value="Other">Other</option>
            </select>
          </div>
        </div>
        <div class="form-group">
          <label>Reason (optional)</label>
          <textarea id="reason-${item.sku}" rows="2" placeholder="Add notes…"></textarea>
        </div>
        <button class="btn btn-primary btn-sm" onclick="submitOverride('${item.sku}','${escapedName}',${item.recommended_qty})">Confirm order</button>
      </div>
      <div class="rec-expand" id="skip-expand-${item.sku}">
        <div class="form-group">
          <label>Skip Reason <span class="text-danger">*</span></label>
          <select id="skip-cat-${item.sku}">
            <option value="">Select category…</option>
            <option value="Inventory suffice">Inventory suffice</option>
            <option value="Budget limited">Budget limited</option>
            <option value="Supplier unavailable">Supplier unavailable</option>
            <option value="Other">Other</option>
          </select>
        </div>
        <div class="form-group">
          <label>Additional Notes (Optional)</label>
          <textarea id="skip-notes-${item.sku}" rows="2" placeholder="Optional details…"></textarea>
        </div>
        <button class="btn btn-danger btn-sm" id="btn-skip-${item.sku}" onclick="submitSkip('${item.sku}','${escapedName}',${item.recommended_qty})">Confirm Skip</button>
      </div>`}
    </div>`;
  }).join('');
}

function getDriverClass(id) {
    if (id.includes('risk') || id.includes('breach') || id.includes('stockout')) return 'db-danger';
    if (id.includes('weather') || id.includes('seasonal')) return 'db-warning';
    if (id.includes('payday') || id.includes('weekend')) return 'db-info';
    return 'db-primary';
}

loadStats();
loadDeadStock();
loadBrief();
loadAlerts();
loadWeather();
