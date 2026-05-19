requireRole('manager');
initShell();

let allItems = [];
const decided = new Map();

async function load() {
  const spinner = document.getElementById('review-spinner');
  try {
    const items = await apiFetch('/brief/today');
    if (!items) return;
    allItems = items;
    spinner.style.display = 'none';
    render();
    updateProgress();
  } catch (err) {
    spinner.style.display = 'none';
    showError(document.getElementById('msg'), 'Could not load brief: ' + err.message);
  }
}

function updateProgress() {
  const total = allItems.length;
  const done = decided.size;
  document.getElementById('progress-text').textContent = `${done} of ${total} reviewed`;
  document.getElementById('progress-fill').style.width = total ? `${(done/total)*100}%` : '0%';
}

function render() {
  const list = document.getElementById('review-list');
  const undecided = allItems.filter(i => !decided.has(i.sku));
  if (!undecided.length && !allItems.length) {
    list.innerHTML = '<div class="card" style="font-size:13px;color:var(--color-text-hint);padding:24px;">No brief available yet.</div>'; return;
  }
  if (!undecided.length) {
    list.innerHTML = '<div class="card" style="font-size:13px;color:var(--color-success);padding:24px;">✓ All items reviewed for today!</div>'; return;
  }
  const item = undecided[0];
  const isCritical = item.days_remaining < item.lead_time_days;

  list.innerHTML = `
  <div class="rec-card">
    <div style="font-size:12px;color:var(--color-text-hint);margin-bottom:10px;">${allItems.indexOf(item)+1} of ${allItems.length}</div>
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
      <div class="rec-meta-item ${isCritical?'critical':''}">Days left: <strong>${item.days_remaining}</strong></div>
      <div class="rec-meta-item">Lead time: <strong>${item.lead_time_days}d</strong></div>
      <div class="rec-meta-item">Suggested qty: <strong>${item.recommended_qty}</strong></div>
    </div>
    <div class="ai-box mb-16"><span class="ai-box-icon">🤖</span><span>${item.ai_reasoning}</span></div>
    <div class="rec-actions">
      <button class="btn btn-success" onclick="decide('${item.sku}','${item.product_name}',${item.recommended_qty},'approved',${item.recommended_qty})">✓ Approve (A)</button>
      <button class="btn btn-secondary" onclick="toggleExpand('expand-main')">Change quantity</button>
      <button class="btn btn-danger" onclick="decide('${item.sku}','${item.product_name}',${item.recommended_qty},'skipped',0)">✕ Skip (S)</button>
    </div>
    <div class="rec-expand" id="expand-main">
      <div class="form-row" style="margin-bottom:10px;">
        <div class="form-group" style="margin-bottom:0;">
          <label>New quantity</label>
          <input type="number" id="qty-input" value="${item.recommended_qty}" min="0">
        </div>
        <div class="form-group" style="margin-bottom:0;">
          <label>Reason category</label>
          <select id="reason-cat">
            <option>Seasonal adjustment</option><option>Supplier issue</option>
            <option>Budget constraint</option><option>Overstock risk</option><option>Other</option>
          </select>
        </div>
      </div>
      <div class="form-group">
        <label>Notes</label><textarea id="reason-text" rows="2"></textarea>
      </div>
      <button class="btn btn-primary btn-sm" onclick="submitOverride('${item.sku}','${item.product_name}',${item.recommended_qty})">Confirm</button>
    </div>
  </div>`;

  window._currentItem = item;
}

function toggleExpand(id) { document.getElementById(id)?.classList.toggle('open'); }

async function decide(sku, name, aiQty, decision, actualQty, reasonCat = '', reasonText = '') {
  try {
    await apiFetch('/orders/decide', { method: 'POST', body: { sku, product_name: name, decision, ai_suggested_qty: aiQty, actual_qty: actualQty, reason_category: reasonCat, reason_text: reasonText } });
    decided.set(sku, decision);
    render();
    updateProgress();
  } catch (err) { showError(document.getElementById('msg'), err.message); }
}

async function submitOverride(sku, name, aiQty) {
  const qty = parseFloat(document.getElementById('qty-input')?.value || 0);
  const cat = document.getElementById('reason-cat')?.value || '';
  const text = document.getElementById('reason-text')?.value || '';
  await decide(sku, name, aiQty, qty === aiQty ? 'approved' : 'overridden', qty, cat, text);
}

document.addEventListener('keydown', e => {
  const item = window._currentItem;
  if (!item) return;
  if (e.key === 'a' || e.key === 'A') decide(item.sku, item.product_name, item.recommended_qty, 'approved', item.recommended_qty);
  if (e.key === 's' || e.key === 'S') decide(item.sku, item.product_name, item.recommended_qty, 'skipped', 0);
});

load();
