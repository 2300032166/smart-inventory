requireRole('admin');
initShell();

let currentTab = 'expiry';

// Expiry state
let allBatches = [];
let eStatusChart = null;
let eCategoryChart = null;

// Dead stock state
let dsAnalysisData = null;
let filteredDSItems = [];
let dsCountChart = null;
let dsValueChart = null;

function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab-bar .tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    document.getElementById('section-expiry').style.display = tab === 'expiry' ? 'block' : 'none';
    document.getElementById('section-deadstock').style.display = tab === 'deadstock' ? 'block' : 'none';

    if (tab === 'expiry' && allBatches.length === 0) loadExpiryData();
    if (tab === 'deadstock' && !dsAnalysisData) loadDeadStockData();
}
window.switchTab = switchTab;

// ─── Expiry Analytics ────────────────────────────────────────────────────────

async function loadExpiryData() {
    const spinner = document.getElementById('analytics-spinner');
    const msg = document.getElementById('analytics-msg');
    spinner.style.display = 'flex';
    hideMsg(msg);

    try {
        const data = await apiFetch('/expiry/dashboard');
        if (!data) return;

        allBatches = data.batches || [];
        renderExpiryKPIs(data.summary);
        renderExpiryCharts(data.charts);
        populateCategoryFilter(allBatches);
        applyExpiryFilters();
    } catch (err) {
        showError(msg, 'Failed to load expiry analytics: ' + err.message);
    } finally {
        spinner.style.display = 'none';
    }
}

function renderExpiryKPIs(summary) {
    document.getElementById('e-stat-total').textContent = summary.total_batches || 0;
    document.getElementById('e-stat-at-risk').textContent = '₹' + (summary.at_risk_value || 0).toLocaleString();
    document.getElementById('e-stat-expired').textContent = summary.status_counts.Expired || 0;
    document.getElementById('e-stat-disposed').textContent = summary.disposed_count || 0;

    const healthPct = summary.total_batches > 0
        ? Math.round((summary.status_counts.Healthy / summary.total_batches) * 100)
        : 0;
    document.getElementById('e-stat-health').textContent = healthPct + '%';
}

function renderExpiryCharts(charts) {
    const statusCtx = document.getElementById('e-status-chart').getContext('2d');
    if (eStatusChart) eStatusChart.destroy();
    eStatusChart = new Chart(statusCtx, {
        type: 'doughnut',
        data: {
            labels: charts.status_dist.map(c => c.name),
            datasets: [{ data: charts.status_dist.map(c => c.value), backgroundColor: charts.status_dist.map(c => c.color), borderWidth: 0 }]
        },
        options: {
            maintainAspectRatio: false,
            plugins: { legend: { position: 'right' } },
            onClick: (evt, elements) => {
                if (!elements.length) return;
                const idx = elements[0].index;
                const status = charts.status_dist[idx].name;
                document.getElementById('e-filter-status').value = status;
                applyExpiryFilters();
                document.getElementById('e-batch-list').scrollIntoView({ behavior: 'smooth' });
            }
        }
    });

    const catCtx = document.getElementById('e-category-chart').getContext('2d');
    if (eCategoryChart) eCategoryChart.destroy();
    eCategoryChart = new Chart(catCtx, {
        type: 'bar',
        data: {
            labels: charts.category_dist.map(c => c.name),
            datasets: [{ label: 'Value (₹)', data: charts.category_dist.map(c => c.value), backgroundColor: 'rgba(24,95,165,0.7)', borderRadius: 4 }]
        },
        options: {
            maintainAspectRatio: false,
            indexAxis: 'y',
            plugins: { legend: { display: false } },
            scales: { x: { grid: { display: false } }, y: { grid: { display: false } } },
            onClick: (evt, elements) => {
                if (!elements.length) return;
                const idx = elements[0].index;
                const cat = charts.category_dist[idx].name;
                document.getElementById('e-filter-category').value = cat;
                applyExpiryFilters();
                document.getElementById('e-batch-list').scrollIntoView({ behavior: 'smooth' });
            }
        }
    });
}

function populateCategoryFilter(batches) {
    const filter = document.getElementById('e-filter-category');
    const categories = [...new Set(batches.map(b => b.category))].sort();
    const current = filter.value;
    filter.innerHTML = '<option value="all">All Categories</option>' +
        categories.map(c => `<option value="${c}">${c}</option>`).join('');
    if (categories.includes(current)) filter.value = current;
}

function applyExpiryFilters() {
    const search = document.getElementById('e-filter-search').value.toLowerCase();
    const status = document.getElementById('e-filter-status').value;
    const category = document.getElementById('e-filter-category').value;

    const filtered = allBatches.filter(b => {
        const matchesSearch = b.sku.toLowerCase().includes(search) || b.product_name.toLowerCase().includes(search);
        const matchesStatus = status === 'all' || b.status === status;
        const matchesCategory = category === 'all' || b.category === category;
        return matchesSearch && matchesStatus && matchesCategory;
    });

    renderExpiryTable(filtered);
}

function renderExpiryTable(batches) {
    const container = document.getElementById('e-batch-list');
    document.getElementById('e-batch-count-tag').textContent = `${batches.length} batches`;

    if (batches.length === 0) {
        container.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:40px;color:var(--color-text-hint);">No batches found matching filters.</td></tr>';
        return;
    }

    container.innerHTML = batches.map(b => `
        <tr>
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
                ` : `<div class="text-success" style="font-size:12px;font-weight:600;">Full sell-through projected</div>`}
            </td>
        </tr>
    `).join('');
}

document.querySelectorAll('#expiry-kpis [data-drill]').forEach(card => {
    card.addEventListener('click', () => {
        const drill = card.dataset.drill;
        document.getElementById('e-filter-status').value = drill === 'all' ? 'all' : drill;
        applyExpiryFilters();
        document.getElementById('e-batch-list').scrollIntoView({ behavior: 'smooth' });
    });
});

document.getElementById('e-filter-search').addEventListener('input', applyExpiryFilters);
document.getElementById('e-filter-status').addEventListener('change', applyExpiryFilters);
document.getElementById('e-filter-category').addEventListener('change', applyExpiryFilters);

// ─── Dead Stock Analytics ────────────────────────────────────────────────────

async function loadDeadStockData() {
    const spinner = document.getElementById('analytics-spinner');
    const msg = document.getElementById('analytics-msg');
    spinner.style.display = 'flex';
    hideMsg(msg);

    try {
        const data = await apiFetch(`/dead-stock/analysis?t=${Date.now()}`);
        if (!data) return;
        dsAnalysisData = data;

        const s = data.summary || {};
        document.getElementById('ds-stat-dead').textContent = s.dead_items || 0;
        const lockedValue = s.value_locked || s.potential_loss || 0;
        document.getElementById('ds-stat-value').textContent = '₹' + lockedValue.toLocaleString('en-IN');
        document.getElementById('ds-stat-slow').textContent = s.slow_items || 0;
        document.getElementById('ds-stat-health').textContent = (s.health_score ?? 0) + '%';

        renderDeadStockCharts(data.category_breakdown || []);
        renderSupplierTable(data.supplier_performance || []);
        filterDS();
    } catch (err) {
        showError(msg, 'Failed to load dead stock analytics: ' + err.message);
    } finally {
        spinner.style.display = 'none';
    }
}

function renderDeadStockCharts(breakdown) {
    const sorted = [...breakdown].sort((a, b) => b.value - a.value).slice(0, 8);
    const labels = sorted.map(b => b.category);

    if (dsCountChart) dsCountChart.destroy();
    dsCountChart = new Chart(document.getElementById('ds-count-chart'), {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                { label: 'Dead', data: sorted.map(b => b.dead_items), backgroundColor: '#ef4444' },
                { label: 'Slow', data: sorted.map(b => b.slow_items), backgroundColor: '#f59e0b' }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: { x: { stacked: true }, y: { stacked: true } },
            onClick: (evt, elements) => {
                if (!elements.length) return;
                const idx = elements[0].index;
                const cat = sorted[idx].category;
                document.getElementById('ds-filter-search').value = cat;
                filterDS();
                document.getElementById('ds-table-body').scrollIntoView({ behavior: 'smooth' });
            }
        }
    });

    if (dsValueChart) dsValueChart.destroy();
    dsValueChart = new Chart(document.getElementById('ds-value-chart'), {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{ data: sorted.map(b => b.value), backgroundColor: ['#ef4444', '#f59e0b', '#3b82f6', '#8b5cf6', '#ec4899', '#10b981', '#f97316', '#06b6d4'] }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { position: 'right' } },
            onClick: (evt, elements) => {
                if (!elements.length) return;
                const idx = elements[0].index;
                const cat = labels[idx];
                document.getElementById('ds-filter-search').value = cat;
                filterDS();
                document.getElementById('ds-table-body').scrollIntoView({ behavior: 'smooth' });
            }
        }
    });
}

function renderSupplierTable(suppliers) {
    const body = document.getElementById('ds-supplier-body');
    if (!suppliers.length) {
        body.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--color-text-hint);padding:20px;">No supplier loss data available</td></tr>';
        return;
    }
    body.innerHTML = suppliers.slice(0, 10).map(s => `
        <tr><td>${s.supplier}</td><td class="text-danger" style="font-weight:600;">₹${s.expiry_loss.toLocaleString('en-IN')}</td></tr>
    `).join('');
}

function filterDS() {
    if (!dsAnalysisData) return;
    const search = document.getElementById('ds-filter-search').value.toLowerCase();
    const status = document.getElementById('ds-filter-status').value;

    const stockMap = {};
    (dsAnalysisData.items || []).forEach(b => {
        stockMap[b.sku] = (stockMap[b.sku] || 0) + b.current_stock;
    });

    const seen = new Set();
    filteredDSItems = [];
    (dsAnalysisData.sku_stats || []).forEach(stat => {
        if (seen.has(stat.sku)) return;
        seen.add(stat.sku);
        filteredDSItems.push({
            sku: stat.sku,
            product_name: stat.name || stat.sku,
            category: stat.category || (dsAnalysisData.items.find(i => i.sku === stat.sku) || {}).category || '—',
            current_stock: stat.current_stock ?? (stockMap[stat.sku] || 0),
            days_since_sale: stat.days_since_sale ?? 999,
            status: stat.status,
            status_code: stat.status_code || stat.status
        });
    });

    filteredDSItems = filteredDSItems.filter(item => {
        const matchesSearch = item.product_name.toLowerCase().includes(search) ||
            item.sku.toLowerCase().includes(search) ||
            (item.category || '').toLowerCase().includes(search);
        const matchesStatus = !status || item.status_code === status;
        return matchesSearch && matchesStatus;
    });

    filteredDSItems.sort((a, b) => b.days_since_sale - a.days_since_sale);
    renderDSTable();
}

function renderDSTable() {
    const body = document.getElementById('ds-table-body');
    document.getElementById('ds-count-tag').textContent = `${filteredDSItems.length} items`;
    if (!filteredDSItems.length) {
        body.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--color-text-hint);padding:32px;">No items found</td></tr>';
        return;
    }
    body.innerHTML = filteredDSItems.map(item => `
        <tr>
            <td><div style="font-weight:600;">${item.product_name}</div><div style="font-size:11px;color:var(--color-text-hint);">${item.sku}</div></td>
            <td>${item.category}</td>
            <td>${item.current_stock.toFixed(0)}</td>
            <td>${item.days_since_sale === 999 ? 'Never' : item.days_since_sale + 'd'}</td>
            <td><span class="status-${item.status_code}">${item.status}</span></td>
        </tr>
    `).join('');
}

document.querySelectorAll('#ds-kpis [data-ds-drill]').forEach(card => {
    card.addEventListener('click', () => {
        document.getElementById('ds-filter-status').value = card.dataset.dsDrill;
        filterDS();
        document.getElementById('ds-table-body').scrollIntoView({ behavior: 'smooth' });
    });
});

document.getElementById('ds-filter-search').addEventListener('input', filterDS);
document.getElementById('ds-filter-status').addEventListener('change', filterDS);

document.getElementById('refresh-btn').addEventListener('click', () => {
    if (currentTab === 'expiry') loadExpiryData();
    else loadDeadStockData();
});

// ─── Boot ─────────────────────────────────────────────────────────────────────
loadExpiryData();
