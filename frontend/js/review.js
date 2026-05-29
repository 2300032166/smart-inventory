requireRole('manager');
initShell();

// ── Review Orders page ────────────────────────────────────────────────────────
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
    const items = await apiFetch(`/orders/reviewed?date=${selectedDate}`);
    if (!items) return;

    spinner.style.display = 'none';
    renderSummary(items, summary, selectedDate);
    renderTable(items, container, selectedDate);
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

  const rows = items.map(item => {
    const d = DECISION_LABELS[item.decision] || { label: item.decision, color: '#888', icon: '?' };
    const ts = item.timestamp
      ? new Date(item.timestamp).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
      : '—';
    const qtyChanged = item.decision === 'overridden'
      ? `<span style="color:var(--color-warning);">${item.actual_qty}</span>`
      : `${item.actual_qty}`;
    const reasonHtml = item.reason_text
      ? `<div class="review-reason">${item.reason_text}</div>`
      : '';

    return `
      <tr>
        <td>
          <div class="review-product-name">${item.product_name || '—'}</div>
          <div class="review-sku-label">${item.sku}</div>
        </td>
        <td>
          <span class="review-decision-badge" style="background:${d.color}20;color:${d.color};border:1px solid ${d.color}40;">
            ${d.icon} ${d.label}
          </span>
        </td>
        <td class="review-qty">${item.ai_suggested_qty ?? '—'}</td>
        <td class="review-qty">${qtyChanged}</td>
        <td>
          ${item.reason_category ? `<span class="badge badge-gray">${item.reason_category}</span>` : '—'}
          ${reasonHtml}
        </td>
        <td class="review-time">${ts}</td>
        <td class="review-manager">${item.manager_name || '—'}</td>
      </tr>`;
  }).join('');

  container.innerHTML = `
    <div class="card" style="padding:0;overflow:hidden;">
      <table class="review-table">
        <thead>
          <tr>
            <th>Product</th>
            <th>Decision</th>
            <th>Suggested Qty</th>
            <th>Final Qty</th>
            <th>Reason</th>
            <th>Time</th>
            <th>Manager</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
        </tbody>
      </table>
    </div>`;
}

document.getElementById('refresh-btn').addEventListener('click', () => {
  datePicker.value = todayStr;
  updateDateText(todayStr);
  loadReviewed();
});

loadReviewed();
