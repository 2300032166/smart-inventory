requireRole('manager');
initShell();

document.getElementById('today-date').textContent = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

let allItems = [];
const decided = new Set();

async function loadStats() {
  try {
    const d = await apiFetch('/sales/summary');
    if (!d) return;
    document.getElementById('stat-pending').textContent = d.pending_review ?? '—';
    document.getElementById('stat-risk').textContent = d.stockout_risk ?? '—';
    document.getElementById('stat-orders').textContent = d.orders_this_week ?? '—';
    document.getElementById('stat-accuracy').textContent = d.ai_accuracy_pct != null ? d.ai_accuracy_pct + '%' : '—';
  } catch {}
}

async function loadBrief() {
  const spinner = document.getElementById('rec-spinner');
  const list = document.getElementById('rec-list');
  try {
    const items = await apiFetch('/brief/today');
    if (!items) return;
    allItems = items.slice(0, 3);
    spinner.style.display = 'none';
    renderCards();
  } catch (err) {
    spinner.style.display = 'none';
    showError(document.getElementById('msg'), 'Could not load brief: ' + err.message);
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
    return `
    <div class="rec-card" id="card-${item.sku}">
      <div class="rec-card-header">
        <div>
          <div class="rec-card-title">${item.product_name}</div>
          <div class="rec-card-sku">${item.sku} &bull; ${item.category}</div>
        </div>
        ${urgencyBadge(item.urgency)}
      </div>
      <div class="rec-meta">
        <div class="rec-meta-item">Stock: <strong>${item.current_stock} ${item.unit}</strong></div>
        <div class="rec-meta-item">Avg daily: <strong>${item.avg_daily_sales}</strong></div>
        <div class="rec-meta-item ${item.days_remaining < item.lead_time_days ? 'critical' : ''}">
          Days left: <strong>${item.days_remaining}</strong></div>
        <div class="rec-meta-item">Suggested qty: <strong>${item.recommended_qty}</strong></div>
      </div>
      <div class="ai-box"><span class="ai-box-icon">🤖</span><span>${item.ai_reasoning}</span></div>
      ${isDone ? `<div class="rec-decided text-success">✓ Decision recorded</div>` : `
      <div class="rec-actions">
        <button class="btn btn-success btn-sm" onclick="decide('${item.sku}','${item.product_name}',${item.recommended_qty},'approved',${item.recommended_qty})">Approve</button>
        <button class="btn btn-secondary btn-sm" onclick="toggleExpand('${item.sku}')">Change qty</button>
        <button class="btn btn-danger btn-sm" onclick="decide('${item.sku}','${item.product_name}',${item.recommended_qty},'skipped',0)">Skip</button>
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
        <button class="btn btn-primary btn-sm" onclick="submitOverride('${item.sku}','${item.product_name}',${item.recommended_qty})">Confirm order</button>
      </div>`}
    </div>`;
  }).join('');
}

function toggleExpand(sku) {
  const el = document.getElementById(`expand-${sku}`);
  el?.classList.toggle('open');
}

async function decide(sku, name, aiQty, decision, actualQty, reasonCat = '', reasonText = '') {
  try {
    await apiFetch('/orders/decide', {
      method: 'POST',
      body: { sku, product_name: name, decision, ai_suggested_qty: aiQty, actual_qty: actualQty, reason_category: reasonCat, reason_text: reasonText }
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

loadStats();
loadBrief();
loadAlerts();
