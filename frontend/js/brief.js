requireRole('manager');
initShell();

let allItems = [];
const decided = new Map();
let isHistoryMode = false;

const dateEl = document.getElementById('brief-date');
const picker = document.getElementById('date-picker');

// Use local date for todayStr (YYYY-MM-DD)
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
  loadBrief();
});

async function loadBrief() {
  const spinner = document.getElementById('brief-spinner');
  const list = document.getElementById('brief-list');
  const msg = document.getElementById('msg');
  hideMsg(msg);
  spinner.style.display = 'flex';
  list.innerHTML = '';

  try {
    let items;
    if (isHistoryMode) {
      // History mode: show full brief for that date (read-only)
      items = await apiFetch(`/brief/history?date=${picker.value}`);
    } else {
      // Today: fetch only PENDING items (not yet decided by manager)
      // Data source: brief_log.json ∩ NOT in override_history.json for today
      items = await apiFetch('/brief/pending');
    }
    if (!items) return;
    allItems = items;
    spinner.style.display = 'none';
    renderBrief();
    updateProgress();
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
    fill.style.width = total === 0 ? '100%' : `${Math.round(((done) / (total + done)) * 100)}%`;
  }
}

function renderBrief() {
  const list = document.getElementById('brief-list');

  if (!allItems.length) {
    if (isHistoryMode) {
      list.innerHTML = '<div class="card" style="font-size:13px;color:var(--color-text-hint);padding:24px;">No recommendations found for this date.</div>';
    } else {
      list.innerHTML = '<div class="card" style="font-size:13px;color:var(--color-success);padding:24px;">✓ All items have been reviewed today. Check <a href="review.html">Review Orders</a> to see decisions.</div>';
    }
    return;
  }

  list.innerHTML = allItems.map(item => {
    const d = decided.get(item.sku);
    const isCritical = item.days_remaining < item.lead_time_days;

    return `<div class="rec-card" id="card-${item.sku}">
      <div class="rec-card-header">
        <div>
          <div class="rec-card-title">${item.product_name}</div>
          <div class="rec-card-sku">${item.sku} &bull; <span class="badge badge-gray">${item.category}</span></div>
        </div>
        ${urgencyBadge(item.urgency)}
      </div>
      <div class="rec-meta">
        <div class="rec-meta-item">Current stock: <strong>${item.current_stock} ${item.unit}</strong></div>
        <div class="rec-meta-item">Avg daily: <strong>${item.avg_daily_sales} ${item.unit}/day</strong></div>
        <div class="rec-meta-item ${isCritical ? 'critical' : ''}">Days remaining: <strong>${item.days_remaining}</strong></div>
        <div class="rec-meta-item">Lead time: <strong>${item.lead_time_days} days</strong></div>
        <div class="rec-meta-item">Suggested: <strong>${item.recommended_qty} ${item.unit}</strong></div>
      </div>
      <div class="ai-box mb-16"><span class="ai-box-icon">🤖</span><span>${item.ai_reasoning}</span></div>
      ${d
        ? `<div class="rec-decided" style="color:${d === 'approved' ? 'var(--color-success)' : d === 'skipped' ? 'var(--color-danger)' : 'var(--color-warning)'}">
             ✓ Decision recorded: ${d}
           </div>`
        : isHistoryMode
          ? '<div class="text-muted" style="font-size:13px;">Past brief — read only</div>'
          : `<div class="rec-actions">
               <button class="btn btn-success btn-sm" onclick="decide('${item.sku}','${item.product_name}',${item.recommended_qty},'approved',${item.recommended_qty})">✓ Approve</button>
               <button class="btn btn-secondary btn-sm" onclick="toggleExpand('${item.sku}')">Change quantity</button>
               <button class="btn btn-danger btn-sm" onclick="decide('${item.sku}','${item.product_name}',${item.recommended_qty},'skipped',0)">✕ Skip</button>
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
                     <option>Seasonal adjustment</option><option>Supplier issue</option>
                     <option>Budget constraint</option><option>Overstock risk</option><option>Other</option>
                   </select>
                 </div>
               </div>
               <div class="form-group">
                 <label>Additional notes</label>
                 <textarea id="reason-${item.sku}" rows="2" placeholder="Why are you changing the quantity?"></textarea>
               </div>
               <button class="btn btn-primary btn-sm" onclick="submitOverride('${item.sku}','${item.product_name}',${item.recommended_qty})">Confirm order</button>
             </div>`
      }
    </div>`;
  }).join('');
}

function toggleExpand(sku) {
  document.getElementById(`expand-${sku}`)?.classList.toggle('open');
}

async function decide(sku, name, aiQty, decision, actualQty, reasonCat = '', reasonText = '') {
  try {
    await apiFetch('/orders/decide', {
      method: 'POST',
      body: { sku, product_name: name, decision, ai_suggested_qty: aiQty, actual_qty: actualQty, reason_category: reasonCat, reason_text: reasonText }
    });
    decided.set(sku, decision);
    // Remove from allItems so the card disappears after decision
    allItems = allItems.filter(i => i.sku !== sku);
    renderBrief();
    updateProgress();
  } catch (err) {
    showError(document.getElementById('msg'), err.message);
  }
}

async function submitOverride(sku, name, aiQty) {
  const qty = parseFloat(document.getElementById(`qty-${sku}`)?.value || 0);
  const reasonCat = document.getElementById(`reason-cat-${sku}`)?.value || '';
  const reasonText = document.getElementById(`reason-${sku}`)?.value || '';
  await decide(sku, name, aiQty, qty === aiQty ? 'approved' : 'overridden', qty, reasonCat, reasonText);
}

loadBrief();
