requireRole('manager');
initShell();

let lineChart = null;
let barChart = null;
let dsCountChart = null;
let dsValueChart = null;

let currentDays = 7;
let currentTab = 'product';

let analysisData = null;
let filteredDSItems = [];
let dsSortCol = 'days_since_sale';
let dsSortDesc = true;

async function loadSkus() {
    const spinner = document.getElementById('trends-spinner');
    if (spinner) spinner.style.display = 'flex';
    
    try {
        const products = await apiFetch('/inventory/products');
        
        if (!products || !Array.isArray(products) || products.length === 0) {
            console.error("Products missing or empty:", products);
            document.getElementById('section-product-trends').innerHTML = `
                <div class="alert-msg alert-msg-error show" style="margin-bottom: 20px;">
                    Failed to load products. The inventory may be empty or the server is unavailable.
                </div>
            `;
            return;
        }

        const sel = document.getElementById('sku-select');
        const uniqueSkus = [];
        const seen = new Set();

        products.forEach(p => {
            if (p && p.sku && !seen.has(p.sku)) {
                uniqueSkus.push(p);
                seen.add(p.sku);
            }
        });

        uniqueSkus.sort((a, b) => (a.name || a.sku).trim().toLowerCase().localeCompare((b.name || b.sku).trim().toLowerCase()));
        const displayLimit = uniqueSkus.slice(0, 500);
        if (sel) {
            sel.innerHTML = displayLimit.map(p => `<option value="${p.sku}">${p.name || p.sku} (${p.sku})</option>`).join('');
        }

        if (uniqueSkus.length > 0) {
            await loadTrends(uniqueSkus[0].sku);
        }
    } catch (e) { 
        console.error("Error in loadSkus:", e);
        document.getElementById('section-product-trends').innerHTML = `
            <div class="alert-msg alert-msg-error show" style="margin-bottom: 20px;">
                Critical Error Loading Data: ${e.message}
            </div>
        `;
    } finally {
        if (spinner) spinner.style.display = 'none';
    }
}

async function loadTrends(sku) {
    if (!sku) return;

    const spinner = document.getElementById('trends-spinner');
    const chartsArea = document.getElementById('charts-area');
    const summaryRow = document.getElementById('summary-row');
    const patternsCard = document.getElementById('patterns-card');
    
    if (currentTab !== 'product') return;

    if (spinner) spinner.style.display = 'flex';
    if (chartsArea) chartsArea.style.display = 'none';
    if (summaryRow) summaryRow.style.display = 'none';
    if (patternsCard) patternsCard.style.display = 'none';

    // Clear any previous error messages
    let errorBox = document.getElementById('trends-error-box');
    if (!errorBox) {
        errorBox = document.createElement('div');
        errorBox.id = 'trends-error-box';
        errorBox.className = 'alert-msg alert-msg-error';
        errorBox.style.marginBottom = '20px';
        spinner.parentNode.insertBefore(errorBox, spinner);
    }
    errorBox.classList.remove('show');

    try {
        const data = await apiFetch(`/sales/trends?sku=${encodeURIComponent(sku)}&days=${currentDays}`);
        
        if (!data || !data.summary) {
            throw new Error("Invalid response format from /sales/trends");
        }

        const s = data.summary || {};
        
        const avgEl = document.getElementById('s-avg');
        if (avgEl) avgEl.textContent = s.avg_daily_sales ?? '—';
        
        const peakDayEl = document.getElementById('s-peak-day');
        if (peakDayEl) {
            if (s.peak_day && s.peak_day !== 'None') {
                peakDayEl.textContent = formatDate(s.peak_day);
            } else {
                peakDayEl.textContent = '—';
            }
        }
        
        const peakQtyEl = document.getElementById('s-peak-qty');
        if (peakQtyEl) peakQtyEl.textContent = s.peak_qty ? `${s.peak_qty} units` : '';
        
        const totalEl = document.getElementById('s-total');
        if (totalEl) totalEl.textContent = s.total ?? '—';
        
        if (summaryRow) summaryRow.style.display = 'grid';
        if (chartsArea) chartsArea.style.display = 'grid';

        const daily = data.daily_sales || [];
        const weekly = data.weekly_totals || [];

        if (typeof Chart !== 'undefined') {
            if (lineChart) lineChart.destroy();
            const canvasLine = document.getElementById('line-chart');
            if (canvasLine) {
                lineChart = new Chart(canvasLine, {
                    type: 'line',
                    data: {
                        labels: daily.map(d => d.date),
                        datasets: [{ label: 'Units sold', data: daily.map(d => d.quantity), borderColor: '#185FA5', backgroundColor: 'rgba(24,95,165,0.08)', fill: true, tension: 0.3, pointRadius: 3 }]
                    },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
                });
            }

            if (barChart) barChart.destroy();
            const canvasBar = document.getElementById('bar-chart');
            if (canvasBar) {
                barChart = new Chart(canvasBar, {
                    type: 'bar',
                    data: {
                        labels: weekly.map(w => w.week),
                        datasets: [{ label: 'Weekly total', data: weekly.map(w => w.quantity), backgroundColor: '#185FA5' }]
                    },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
                });
            }
        }

        const patterns = data.pattern_dates || [];
        if (patternsCard) patternsCard.style.display = 'block';
        
        const patternList = document.getElementById('patterns-list');
        if (patternList) {
            if (!patterns.length) {
                patternList.innerHTML = '<span class="text-muted" style="font-size:13px;">No significant patterns detected in this period.</span>';
            } else {
                patternList.innerHTML = patterns.map(p => `<span class="badge badge-warning" style="margin-right:8px;margin-bottom:8px;">${p}</span>`).join('');
            }
        }
    } catch (err) {
        console.error('Error loading trends:', err);
        errorBox.textContent = `Could not load trends configuration: ${err.message}`;
        errorBox.classList.add('show');
    } finally {
        if (spinner) spinner.style.display = 'none';
    }
}

async function loadFullAnalysis() {
    try {
        const data = await apiFetch(`/dead-stock/analysis?t=${Date.now()}`);
        if (!data) return;
        analysisData = data;
        
        // --- 1. Dead Stock & Health Score ---
        const s = data.summary || {};
        const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val ?? 0; };
        
        setVal('ds-total-items', s.dead_items);
        const lockedValue = s.value_locked || s.potential_loss || 0;
        const totalValueEl = document.getElementById('ds-total-value');
        if (totalValueEl) totalValueEl.textContent = '₹' + lockedValue.toLocaleString('en-IN');
        setVal('ds-total-slow', s.slow_items);
        
        const hScore = s.health_score ?? 0;
        const hEl = document.getElementById('health-score');
        const hProg = document.getElementById('health-progress');
        if (hEl) hEl.textContent = hScore + '%';
        if (hProg) {
            hProg.style.width = hScore + '%';
            hProg.style.backgroundColor = hScore > 80 ? '#22c55e' : (hScore > 50 ? '#f59e0b' : '#ef4444');
        }

        renderDeadStockCharts(data.category_breakdown || []);
        filterDS();

    } catch (err) {
        console.error('Full analysis load fail', err);
    }
}

function renderDeadStockCharts(breakdown) {
    const sorted = [...breakdown].sort((a,b) => b.value - a.value).slice(0, 8);
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
        options: { responsive: true, maintainAspectRatio: false, scales: { x: { stacked: true }, y: { stacked: true } } }
    });

    if (dsValueChart) dsValueChart.destroy();
    dsValueChart = new Chart(document.getElementById('ds-value-chart'), {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{ data: sorted.map(b => b.value), backgroundColor: ['#ef4444','#f59e0b','#3b82f6','#8b5cf6','#ec4899','#10b981','#f97316','#06b6d4'] }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right' } } }
    });
}

function filterDS() {
    if (!analysisData) return;
    const search = document.getElementById('ds-search').value.toLowerCase();
    const status = document.getElementById('ds-filter-status').value;

    // Build a rich map from sku_stats (has name + status)
    const skuMap = {};
    (analysisData.sku_stats || []).forEach(s => { skuMap[s.sku] = s; });

    // Derive per-SKU total stock from items_with_expiry
    const stockMap = {};
    (analysisData.items || []).forEach(b => {
        stockMap[b.sku] = (stockMap[b.sku] || 0) + b.current_stock;
    });

    // Build deduplicated SKU rows for the table
    const seen = new Set();
    filteredDSItems = [];
    (analysisData.sku_stats || []).forEach(stat => {
        if (seen.has(stat.sku)) return;
        seen.add(stat.sku);
        filteredDSItems.push({
            sku: stat.sku,
            product_name: stat.name || stat.sku,
            category: stat.category || (analysisData.items.find(i => i.sku === stat.sku) || {}).category || '—',
            current_stock: stat.current_stock ?? (stockMap[stat.sku] || 0),
            days_since_sale: stat.days_since_sale ?? 999,  // now provided by backend
            status: stat.status,
            status_code: stat.status_code || stat.status
        });
    });

    filteredDSItems = filteredDSItems.filter(item => {
        const matchesSearch = item.product_name.toLowerCase().includes(search) || item.sku.toLowerCase().includes(search);
        const matchesStatus = !status || item.status_code === status;
        return matchesSearch && matchesStatus;
    });

    sortDS();
}

function sortDS(col) {
    if (col) {
        if (dsSortCol === col) dsSortDesc = !dsSortDesc;
        else { dsSortCol = col; dsSortDesc = true; }
    }
    filteredDSItems.sort((a, b) => {
        let valA = a[dsSortCol], valB = b[dsSortCol];
        if (typeof valA === 'string') { valA = valA.toLowerCase(); valB = valB.toLowerCase(); }
        return dsSortDesc ? (valA < valB ? 1 : -1) : (valA > valB ? -1 : 1);
    });
    renderDSTable();
}

function renderDSTable() {
    const body = document.getElementById('ds-table-body');
    if (!body) return;
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

window.switchTrendsTab = function(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab-bar .tab-btn').forEach(btn => {
        const btnTab = btn.getAttribute('onclick')?.match(/'([^']+)'/)?.[1];
        if (btnTab) {
            btn.classList.toggle('active', btnTab === tab);
        }
    });

    document.getElementById('section-product-trends').style.display = tab === 'product' ? 'block' : 'none';
    document.getElementById('section-dead-stock').style.display = tab === 'deadstock' ? 'block' : 'none';

    if (tab === 'deadstock') {
        loadFullAnalysis();
    } else {
        loadTrends(document.getElementById('sku-select').value);
    }
};

window.sortDS = sortDS;

document.getElementById('sku-select').addEventListener('change', e => loadTrends(e.target.value));
document.querySelectorAll('#section-product-trends .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('#section-product-trends .tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentDays = parseInt(btn.dataset.days);
        loadTrends(document.getElementById('sku-select').value);
    });
});

document.getElementById('ds-search').addEventListener('input', filterDS);
document.getElementById('ds-filter-status').addEventListener('change', filterDS);

// Check for URL param
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('tab') === 'dead-stock') {
    setTimeout(() => switchTrendsTab('deadstock'), 100);
}

loadSkus();
