requireRole('manager');
initShell();

const role = getRole();

let suppliers = [];

async function loadSupplierList() {
  try {
    const data = await apiFetch('/suppliers');
    if (!data) return;
    suppliers = data;
    const sel = document.getElementById('sup-select');
    sel.innerHTML = '<option value="">— Select supplier —</option>';
    suppliers.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.supplier_id;
      opt.textContent = s.name + (s.status === 'Inactive' ? ' (Inactive)' : '');
      sel.appendChild(opt);
    });

    // If ?sid= param in URL, auto-select
    const params = new URLSearchParams(location.search);
    const sid = params.get('sid');
    if (sid) {
      sel.value = sid;
      loadDashboard(sid);
    } else {
      document.getElementById('empty-state').style.display = 'block';
    }
  } catch (e) {
    showError(document.getElementById('msg'), e.message);
  }
}

document.getElementById('sup-select').addEventListener('change', e => {
  const sid = e.target.value;
  if (sid) {
    loadDashboard(sid);
  } else {
    document.getElementById('dash-content').style.display = 'none';
    document.getElementById('empty-state').style.display = 'block';
  }
});

async function loadDashboard(sid) {
  const spinner = document.getElementById('dash-spinner');
  const content = document.getElementById('dash-content');
  const empty   = document.getElementById('empty-state');
  spinner.style.display = 'flex';
  content.style.display = 'none';
  empty.style.display   = 'none';

  try {
    const s = await apiFetch(`/suppliers/${sid}`);
    if (!s) return;
    renderDashboard(s);
    content.style.display = 'block';
  } catch (e) {
    showError(document.getElementById('msg'), e.message);
  } finally {
    spinner.style.display = 'none';
  }
}

function starsHtml(rating, max = 5) {
  let html = '';
  for (let i = 1; i <= max; i++) {
    html += i <= Math.round(rating) ? '★' : '☆';
  }
  return html;
}

function levelClass(level) {
  const map = { Excellent: 'badge-success', 'Very Good': 'badge-info',
                Good: 'badge-warning', Average: 'badge-warning', Poor: 'badge-urgent' };
  return map[level] || 'badge-gray';
}

function renderDashboard(s) {
  // Reliability box
  document.getElementById('rel-score').textContent = s.reliability_score ?? '—';
  document.getElementById('rel-stars').innerHTML =
    `<span class="star-filled">${starsHtml(s.stars ?? 0)}</span> (${s.stars ?? '—'} / 5)`;
  document.getElementById('rel-level').textContent = s.performance_level || '—';
  document.getElementById('rel-rank').textContent =
    s.rank ? `Overall Rank: #${s.rank} of all suppliers` : '';

  const onPct   = s.on_time_pct   ?? 0;
  const fillPct = s.fill_rate     ?? 0;
  const qPct    = (s.quality_rating ?? 0) / 5 * 100;

  document.getElementById('bar-ontime').style.width  = onPct + '%';
  document.getElementById('bar-fill').style.width    = fillPct + '%';
  document.getElementById('bar-quality').style.width = qPct + '%';
  document.getElementById('lbl-ontime').textContent  = onPct + '%';
  document.getElementById('lbl-fill').textContent    = fillPct + '%';
  document.getElementById('lbl-quality').textContent = (s.quality_rating ?? 0).toFixed(1);

  // Metric cards
  document.getElementById('m-total').textContent  = s.total_orders ?? 0;
  document.getElementById('m-ontime').textContent = (s.on_time_pct ?? 0) + '%';
  document.getElementById('m-lead').textContent   = (s.avg_lead_time ?? 0) + ' d';
  document.getElementById('m-delay').textContent  = s.avg_delay > 0 ? '+' + s.avg_delay + ' d' : '—';
  document.getElementById('m-fill').textContent   = (s.fill_rate ?? 0) + '%';
  document.getElementById('m-quality').textContent= (s.quality_rating ?? 0).toFixed(2) + ' ★';
  document.getElementById('m-accept').textContent = (s.acceptance_rate ?? 0) + '%';

  // Supplier info
  const infoEl = document.getElementById('sup-info');
  const fields = [
    ['Supplier ID', s.supplier_id],
    ['Company',     s.company_name || '—'],
    ['Contact',     s.contact_person || '—'],
    ['Phone',       s.phone || '—'],
    ['Email',       s.email || '—'],
    ['Address',     s.address || '—'],
    ['Lead Time',   (s.default_lead_time_days || '—') + ' days'],
    ['Schedule',    s.delivery_schedule || '—'],
    ['Status',      s.status || 'Active'],
  ];
  infoEl.innerHTML = fields.map(([k, v]) => `
    <div style="padding:8px 0;border-bottom:1px solid var(--color-border);">
      <div style="font-size:11px;color:var(--color-text-hint);font-weight:600;text-transform:uppercase;letter-spacing:.04em;">${k}</div>
      <div style="font-size:var(--text-sm);font-weight:500;margin-top:2px;">${v}</div>
    </div>`).join('');

  // Products table
  const prods = s.mapped_products || [];
  document.getElementById('prod-count').textContent = prods.length;
  const ptbody = document.getElementById('prod-tbody');
  if (!prods.length) {
    ptbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--color-text-hint);padding:24px;">No products mapped</td></tr>';
  } else {
    ptbody.innerHTML = prods.map(p => `
      <tr>
        <td style="font-family:monospace;font-size:12px;">${p.sku}</td>
        <td style="font-weight:500;">${p.name}</td>
        <td><span class="badge badge-gray">${p.category || '—'}</span></td>
        <td>${p.unit || '—'}</td>
        <td>₹${Number(p.unit_price || 0).toFixed(2)}</td>
        <td>${p.current_stock ?? '—'}</td>
      </tr>`).join('');
  }

  // PO table
  const poLink = document.getElementById('view-pos-link');
  if (poLink) poLink.href = `purchase-orders.html?supplier=${s.supplier_id}`;

  const pos = s.recent_orders || [];
  const ptbody2 = document.getElementById('po-tbody');
  if (!pos.length) {
    ptbody2.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--color-text-hint);padding:24px;">No purchase orders found</td></tr>';
  } else {
    ptbody2.innerHTML = pos.map(p => {
      const oq = parseFloat(p.ordered_qty || 0);
      const rq = parseFloat(p.received_qty || 0);
      const fillPct = oq > 0 ? Math.round(rq / oq * 100) : '—';
      const qr = p.quality_rating;
      const qrHtml = qr ? `<span class="star-filled">${'★'.repeat(Number(qr))}${'☆'.repeat(5 - Number(qr))}</span>` : '—';
      const statusCls = p.status === 'received' ? 'badge-success' : 'badge-info';
      return `<tr>
        <td style="font-weight:600;font-size:12px;">${p.po_number}</td>
        <td style="font-size:12px;">${p.product_name || p.sku}</td>
        <td style="font-size:12px;">${p.order_date || '—'}</td>
        <td style="font-size:12px;">${p.expected_delivery_date || '—'}</td>
        <td style="font-size:12px;">${p.actual_delivery_date || '—'}</td>
        <td>${oq}</td>
        <td>${fillPct}${fillPct !== '—' ? '%' : ''}</td>
        <td><span class="badge ${statusCls}">${p.status}</span></td>
        <td style="font-size:14px;">${qrHtml}</td>
      </tr>`;
    }).join('');
  }
}

loadSupplierList();
