requireRole('admin');
initShell();

function fmtPrice(n) { return '₹' + Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function fmtInt(n) { return Number(n || 0).toLocaleString('en-IN'); }

async function loadInsights() {
  try {
    const data = await apiFetch('/admin/insights');
    if (!data) return;

    const inv = data.inventory || {};
    const disc = data.discounts || {};
    const exp = data.expiry || {};
    const up = data.upcoming_stock || {};
    const sup = data.suppliers || {};

    document.getElementById('kpi-products').textContent = fmtInt(inv.total_products);
    document.getElementById('kpi-value').textContent = fmtPrice(inv.total_value);
    document.getElementById('kpi-low').textContent = fmtInt(inv.low_stock_count);
    document.getElementById('kpi-stockout').textContent = fmtInt(inv.stockout_count);
    document.getElementById('kpi-active-disc').textContent = fmtInt(disc.active_count);
    document.getElementById('kpi-pending-disc').textContent = fmtInt(disc.pending_count);
    document.getElementById('kpi-expiry').textContent = fmtInt(exp.expiring_30_count);
    document.getElementById('kpi-incoming').textContent = fmtInt(up.total_units);
    document.getElementById('kpi-suppliers').textContent = fmtInt(sup.total_suppliers);
    document.getElementById('kpi-best-supplier').textContent = (sup.best_overall && sup.best_overall.name) ? sup.best_overall.name : '—';

    renderActiveDiscounts(disc.active_sample || []);
    renderExpiring(exp.expiring_30_sample || []);
    renderStockIssues((inv.low_stock_sample || []).concat(inv.stockout_sample || []));
    renderUpcoming(up.sample || []);
    renderSuppliers(sup.top_suppliers || []);
  } catch (e) {
    console.error(e);
    showToast('Failed to load insights: ' + e.message, 'danger');
  }
}

function renderActiveDiscounts(items) {
  const el = document.getElementById('active-discounts-body');
  if (!items.length) { el.innerHTML = '<div class="text-muted" style="font-size:13px;">No active discounts.</div>'; return; }
  el.innerHTML = `
    <table class="insight-table">
      <thead><tr><th>Product</th><th>SKU</th><th>Discount</th><th>Final Price</th><th>Stock</th></tr></thead>
      <tbody>
        ${items.map(d => `
          <tr>
            <td>${d.product_name || '—'}</td>
            <td>${d.sku || '—'}</td>
            <td><span class="pill pill-success">${d.discount_percent || 0}% off</span></td>
            <td>${fmtPrice(d.discounted_price)}</td>
            <td>${fmtInt(d.current_stock)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>`;
}

function renderExpiring(items) {
  const el = document.getElementById('expiring-body');
  if (!items.length) { el.innerHTML = '<div class="text-muted" style="font-size:13px;">No batches expiring within 30 days.</div>'; return; }
  el.innerHTML = `
    <table class="insight-table">
      <thead><tr><th>Product</th><th>Batch</th><th>Days Left</th><th>Qty</th><th>Status</th></tr></thead>
      <tbody>
        ${items.map(b => `
          <tr>
            <td>${b.product_name || '—'}</td>
            <td>${b.batch_no || '—'}</td>
            <td class="${b.days_left <= 7 ? 'text-danger' : 'text-warning'}">${b.days_left}d</td>
            <td>${fmtInt(b.quantity)}</td>
            <td>${b.status || '—'}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>`;
}

function renderStockIssues(items) {
  const el = document.getElementById('stockout-body');
  if (!items.length) { el.innerHTML = '<div class="text-muted" style="font-size:13px;">No low-stock or stockout products.</div>'; return; }
  el.innerHTML = `
    <table class="insight-table">
      <thead><tr><th>Product</th><th>SKU</th><th>Category</th><th>Price</th></tr></thead>
      <tbody>
        ${items.map(p => `
          <tr>
            <td>${p.name || p.product_name || '—'}</td>
            <td>${p.sku || '—'}</td>
            <td>${p.category || '—'}</td>
            <td>${p.unit_price ? fmtPrice(p.unit_price) : '—'}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>`;
}

function renderUpcoming(items) {
  const el = document.getElementById('upcoming-body');
  if (!items.length) { el.innerHTML = '<div class="text-muted" style="font-size:13px;">No incoming stock.</div>'; return; }
  el.innerHTML = `
    <table class="insight-table">
      <thead><tr><th>Product</th><th>PO</th><th>Supplier</th><th>Qty</th><th>Expected</th></tr></thead>
      <tbody>
        ${items.map(u => `
          <tr>
            <td>${u.product_name || '—'}</td>
            <td>${u.po_number || '—'}</td>
            <td>${u.supplier_name || '—'}</td>
            <td>${fmtInt(u.qty)}</td>
            <td>${u.expected_delivery_date || '—'}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>`;
}

function renderSuppliers(items) {
  const el = document.getElementById('suppliers-body');
  if (!items.length) { el.innerHTML = '<div class="text-muted" style="font-size:13px;">No supplier data.</div>'; return; }
  el.innerHTML = `
    <table class="insight-table">
      <thead><tr><th>Supplier</th><th>Reliability</th><th>On-time</th><th>Lead Time</th><th>Products</th></tr></thead>
      <tbody>
        ${items.map(s => `
          <tr>
            <td>${s.name || '—'}</td>
            <td>${s.reliability_score || 0}</td>
            <td>${s.on_time_pct || 0}%</td>
            <td>${s.avg_lead_time || 0}d</td>
            <td>${s.product_count || 0}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>`;
}

loadInsights();
