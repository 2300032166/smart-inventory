requireRole('manager');
initShell();

let allBatches = [];
let disposedBatches = [];
let currentView = 'active';
let pendingDisposeBatch = null;
let statusChart = null;
let categoryChart = null;
// Safe lookup: keyed by batch_no — avoids JSON.stringify in onclick attributes
const _batchMap = {};

// ─── Data Loading ───────────────────────────────────────────────────────────

async function loadData() {
    const spinner = document.getElementById('spinner');
    const msg = document.getElementById('msg');
    spinner.style.display = 'flex';
    hideMsg(msg);

    try {
        const [data, disposed] = await Promise.all([
            apiFetch(`/expiry/dashboard?_=${Date.now()}`),
            apiFetch(`/expiry/disposed?_=${Date.now()}`)
        ]);
        if (!data) return;

        allBatches = data.batches;
        disposedBatches = disposed || [];

        renderKPIs(data.summary);
        renderCharts(data.charts);
        populateCategoryFilter(allBatches);
        applyFilters();
        renderDisposedTable();

        // Update disposed badge count
        const disposedCount = disposedBatches.length;
        document.getElementById('disposed-badge').textContent = disposedCount;

        spinner.style.display = 'none';
        showToast('Data refreshed', 'success');
    } catch (err) {
        spinner.style.display = 'none';
        showError(msg, 'Failed to load expiry data: ' + err.message);
    }
}

// ─── KPIs ────────────────────────────────────────────────────────────────────

function renderKPIs(summary) {
    document.getElementById('stat-total-batches').textContent = summary.total_batches || 0;
    document.getElementById('stat-at-risk-value').textContent = '₹' + (summary.at_risk_value || 0).toLocaleString();
    document.getElementById('stat-expired-qty').textContent = summary.status_counts.Expired || 0;
    document.getElementById('stat-disposed-count').textContent = summary.disposed_count || 0;

    const healthPct = summary.total_batches > 0
        ? Math.round((summary.status_counts.Healthy / summary.total_batches) * 100)
        : 0;
    document.getElementById('stat-health-pct').textContent = healthPct + '%';
}

// ─── Charts ──────────────────────────────────────────────────────────────────

function renderCharts(charts) {
    const statusCtx = document.getElementById('statusChart').getContext('2d');
    if (statusChart) statusChart.destroy();

    statusChart = new Chart(statusCtx, {
        type: 'doughnut',
        data: {
            labels: charts.status_dist.map(c => c.name),
            datasets: [{
                data: charts.status_dist.map(c => c.value),
                backgroundColor: charts.status_dist.map(c => c.color),
                borderWidth: 0
            }]
        },
        options: {
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right' }
            }
        }
    });

    const catCtx = document.getElementById('categoryChart').getContext('2d');
    if (categoryChart) categoryChart.destroy();

    categoryChart = new Chart(catCtx, {
        type: 'bar',
        data: {
            labels: charts.category_dist.map(c => c.name),
            datasets: [{
                label: 'Value (₹)',
                data: charts.category_dist.map(c => c.value),
                backgroundColor: 'rgba(var(--color-primary-rgb), 0.7)',
                borderRadius: 4
            }]
        },
        options: {
            maintainAspectRatio: false,
            indexAxis: 'y',
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: { grid: { display: false } },
                y: { grid: { display: false } }
            }
        }
    });
}

// ─── Filters ─────────────────────────────────────────────────────────────────

function populateCategoryFilter(batches) {
    const filter = document.getElementById('filter-category');
    const categories = [...new Set(batches.map(b => b.category))].sort();

    filter.innerHTML = '<option value="all">All Categories</option>';
    categories.forEach(cat => {
        const opt = document.createElement('option');
        opt.value = cat;
        opt.textContent = cat;
        filter.appendChild(opt);
    });
}

function applyFilters() {
    const search = document.getElementById('filter-search').value.toLowerCase();
    const status = document.getElementById('filter-status').value;
    const category = document.getElementById('filter-category').value;
    const risk = document.getElementById('filter-risk').value;

    const filtered = allBatches.filter(b => {
        const matchesSearch = b.sku.toLowerCase().includes(search) || b.product_name.toLowerCase().includes(search);
        const matchesStatus = status === 'all' || b.status === status;
        const matchesCategory = category === 'all' || b.category === category;
        const matchesRisk = risk === 'all' || (risk === 'high' ? b.risk_qty > 0 : b.risk_qty === 0);

        return matchesSearch && matchesStatus && matchesCategory && matchesRisk;
    });

    renderTable(filtered);
}

// ─── View Toggle ─────────────────────────────────────────────────────────────

function switchView(view) {
    currentView = view;
    document.getElementById('tab-active').classList.toggle('active', view === 'active');
    document.getElementById('tab-disposed').classList.toggle('active', view === 'disposed');
    document.getElementById('section-active').style.display = view === 'active' ? '' : 'none';
    document.getElementById('filter-bar-active').style.display = view === 'active' ? '' : 'none';
    document.getElementById('section-disposed').style.display = view === 'disposed' ? '' : 'none';
}

// ─── Active Batch Table ───────────────────────────────────────────────────────

function renderTable(batches) {
    const container = document.getElementById('batch-list');
    document.getElementById('batch-count-tag').textContent = `${batches.length} batches`;

    if (batches.length === 0) {
        container.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--color-text-hint);">No batches found matching filters.</td></tr>';
        return;
    }

    // Build safe lookup map BEFORE generating HTML
    _batchMap.__clear__ && delete _batchMap.__clear__;
    Object.keys(_batchMap).forEach(k => delete _batchMap[k]);
    batches.forEach(b => { _batchMap[b.batch_no] = b; });

    container.innerHTML = batches.map(b => {
        const isExpired = b.status === 'Expired';
        const recHtml = isExpired
            ? buildExpiredActions(b)
            : `<div class="action-cell"><div class="recommendation-pill">${b.recommendation}</div></div>`;

        return `
        <tr id="row-${b.batch_no.replace(/[^a-zA-Z0-9]/g, '_')}">
            <td><input type="checkbox" class="batch-bulk-cb" value="${b.batch_no}" onchange="updateBulkDisposeButton()"></td>
            <td>
                <div style="font-weight:600;font-size:14px;color:var(--color-text-title);">${b.product_name}</div>
                <div style="font-size:11px;color:var(--color-text-hint);">${b.sku} | ${b.category}</div>
            </td>
            <td>
                <div style="font-family:monospace;font-weight:700;">${b.batch_no}</div>
                <div style="font-size:11px;color:var(--color-text-hint);">Exp: ${b.expiry_date}</div>
            </td>
            <td>
                <span class="risk-tag" style="background:${b.status_color};">${b.status}</span>
                <div style="font-size:11px;margin-top:4px;">${b.days_left} days left</div>
            </td>
            <td>
                <div style="font-weight:700;">${b.quantity} units</div>
                <div style="font-size:11px;color:var(--color-text-hint);">Val: ₹${b.value.toLocaleString()}</div>
            </td>
            <td>
                ${b.risk_qty > 0 ? `
                    <div class="text-danger" style="font-weight:700;font-size:12px;">${b.risk_qty} units at risk</div>
                    <div style="font-size:10px;color:var(--color-text-hint);">Projected unsold before expiry</div>
                ` : `
                    <div class="text-success" style="font-size:12px;font-weight:600;">Full sell-through projected</div>
                `}
            </td>
            <td>${recHtml}</td>
        </tr>
    `}).join('');
}

function buildExpiredActions(b) {
    // Encode only the batch_no (safe alphanumeric ID) — actual batch data
    // is retrieved from _batchMap at click time to avoid HTML attribute injection
    const safeKey = encodeURIComponent(b.batch_no);
    return `
        <div class="action-cell">
            <div class="recommendation-pill" style="background:rgba(185,64,64,0.08);color:#b94040;border:1px solid rgba(185,64,64,0.2);">
                ⚠️ Dispose
            </div>
            <button class="btn-dispose"
                data-batchno="${b.batch_no.replace(/"/g, '&quot;')}"
                onclick="openDisposeByKey(this.dataset.batchno)">
                🗑 Mark as Disposed
            </button>
        </div>`;
}

// ─── Disposed Batch Table ─────────────────────────────────────────────────────

function renderDisposedTable() {
    const container = document.getElementById('disposed-list');
    document.getElementById('disposed-count-tag').textContent = `${disposedBatches.length} disposed`;

    if (disposedBatches.length === 0) {
        container.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--color-text-hint);">No disposed batches yet.</td></tr>';
        return;
    }

    container.innerHTML = disposedBatches.map(b => `
        <tr>
            <td>
                <div style="font-weight:600;font-size:14px;color:var(--color-text-title);">${b.product_name}</div>
                <div style="font-size:11px;color:var(--color-text-hint);">${b.sku}</div>
            </td>
            <td><span style="font-family:monospace;font-weight:700;">${b.batch_no}</span></td>
            <td>${b.expiry_date || '—'}</td>
            <td>${b.category || '—'}</td>
            <td><span class="disposed-tag">Disposed</span></td>
            <td style="font-size:12px;">${b.disposed_at ? b.disposed_at.split('.')[0] : '—'}</td>
            <td style="font-size:12px;color:var(--color-text-hint);">${b.disposed_by || '—'}</td>
        </tr>
    `).join('');
}

// ─── Dispose Modal ────────────────────────────────────────────────────────────

/** Called from the button — looks up batch safely from the in-memory map. */
function openDisposeByKey(batchNo) {
    const b = _batchMap[batchNo];
    if (!b) { console.error('Batch not found in map:', batchNo); return; }
    openDisposeModal(b);
}

function openDisposeModal(batch) {
    pendingDisposeBatch = batch;
    document.getElementById('modal-product-name').textContent = batch.product_name;
    document.getElementById('modal-batch-no').textContent = batch.batch_no;
    document.getElementById('modal-expiry-date').textContent = batch.expiry_date;
    document.getElementById('modal-qty').textContent = `${batch.quantity} units`;
    document.getElementById('modal-status').textContent = batch.status;
    document.getElementById('btn-confirm-dispose').disabled = false;
    document.getElementById('btn-confirm-dispose').innerHTML = '<span>🗑️</span> Confirm Disposal';
    document.getElementById('dispose-modal').classList.add('open');
}

function closeDisposeModal() {
    document.getElementById('dispose-modal').classList.remove('open');
    pendingDisposeBatch = null;
}

async function confirmDispose() {
    if (!pendingDisposeBatch) return;
    const btn = document.getElementById('btn-confirm-dispose');
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span> Processing...';

    try {
        const result = await apiFetch(`/expiry/dispose/${encodeURIComponent(pendingDisposeBatch.batch_no)}`, {
            method: 'POST'
        });

        if (result && result.success) {
            closeDisposeModal();
            showSuccess(document.getElementById('msg'), `✅ Batch ${result.batch_no} (${result.product_name}) has been disposed and removed from inventory.`);
            // Reload everything to reflect updated state
            await loadData();
        } else {
            showError(document.getElementById('msg'), result?.message || 'Disposal failed.');
            btn.disabled = false;
            btn.innerHTML = '<span>🗑️</span> Confirm Disposal';
        }
    } catch (err) {
        showError(document.getElementById('msg'), 'Disposal error: ' + err.message);
        btn.disabled = false;
        btn.innerHTML = '<span>🗑️</span> Confirm Disposal';
    }
}

// ─── Bulk Dispose ────────────────────────────────────────────────────────────
function toggleBatchSelectAll(cb) {
    document.querySelectorAll('.batch-bulk-cb').forEach(el => el.checked = cb.checked);
    updateBulkDisposeButton();
}

function updateBulkDisposeButton() {
    const selected = document.querySelectorAll('.batch-bulk-cb:checked');
    const btn = document.getElementById('bulk-dispose-btn');
    btn.style.display = selected.length ? 'inline-flex' : 'none';
    btn.innerHTML = `<span class="icon">🗑️</span> Bulk Dispose (${selected.length})`;
}

function openBulkDispose() {
    const selected = Array.from(document.querySelectorAll('.batch-bulk-cb:checked'));
    document.getElementById('bulk-dispose-count').textContent = selected.length;
    document.getElementById('bulk-dispose-reason').value = '';
    document.getElementById('bulk-dispose-reason-select').value = '';
    document.getElementById('btn-confirm-bulk-dispose').disabled = false;
    document.getElementById('btn-confirm-bulk-dispose').innerHTML = '<span>🗑️</span> Confirm Disposal';

    // Populate selected batches list
    const listEl = document.getElementById('bulk-dispose-list');
    if (selected.length === 0) { listEl.innerHTML = ''; return; }
    const rows = selected.map(cb => {
        const b = _batchMap[cb.value];
        if (!b) return '';
        return `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-bottom:1px solid #fecaca;">
            <div>
                <div style="font-weight:600;color:#1e293b;">${b.product_name}</div>
                <div style="color:#64748b;font-size:11px;">${b.batch_no} · Exp: ${b.expiry_date}</div>
            </div>
            <div style="text-align:right;">
                <span style="font-weight:700;color:#b94040;">${b.quantity} units</span>
                <div style="font-size:10px;color:#94a3b8;margin-top:2px;">${b.status}</div>
            </div>
        </div>`;
    }).join('');
    listEl.innerHTML = rows || '<div style="padding:12px;color:#94a3b8;text-align:center;">No batch details available</div>';

    document.getElementById('bulk-dispose-modal').classList.add('open');
}

function closeBulkDisposeModal() {
    document.getElementById('bulk-dispose-modal').classList.remove('open');
}

async function confirmBulkDispose() {
    const selected = Array.from(document.querySelectorAll('.batch-bulk-cb:checked'));
    if (!selected.length) return;
    const reasonType = document.getElementById('bulk-dispose-reason-select').value;
    const reasonNotes = document.getElementById('bulk-dispose-reason').value.trim();
    const reason = [reasonType, reasonNotes].filter(Boolean).join(' — ') || 'Bulk disposal';
    const btn = document.getElementById('btn-confirm-bulk-dispose');
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span> Processing...';

    try {
        const result = await apiFetch('/admin/bulk-dispose-batches', {
            method: 'POST',
            body: { items: selected.map(cb => ({ batch_no: cb.value, reason })) }
        });
        closeBulkDisposeModal();
        showSuccess(document.getElementById('msg'), `✅ Disposed ${result.count || selected.length} batch(es).`);
        await loadData();
    } catch (err) {
        showError(document.getElementById('msg'), 'Bulk disposal error: ' + err.message);
        btn.disabled = false;
        btn.innerHTML = '<span>🗑️</span> Confirm Disposal';
    }
}

// Close modal on overlay click
document.getElementById('dispose-modal').addEventListener('click', function (e) {
    if (e.target === this) closeDisposeModal();
});
document.getElementById('bulk-dispose-modal').addEventListener('click', function (e) {
    if (e.target === this) closeBulkDisposeModal();
});

// ─── Boot ─────────────────────────────────────────────────────────────────────
loadData();
