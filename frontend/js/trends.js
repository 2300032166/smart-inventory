requireRole('manager');
initShell();

let lineChart = null;
let barChart = null;
let currentDays = 7;

async function loadSkus() {
  try {
    const products = await apiFetch('/inventory/products');
    if (!products) return;
    const sel = document.getElementById('sku-select');
    sel.innerHTML = products.map(p => `<option value="${p.sku}">${p.name} (${p.sku})</option>`).join('');
    if (products.length) loadTrends(products[0].sku);
  } catch {}
}

async function loadTrends(sku) {
  const spinner = document.getElementById('trends-spinner');
  const chartsArea = document.getElementById('charts-area');
  const summaryRow = document.getElementById('summary-row');
  const patternsCard = document.getElementById('patterns-card');
  spinner.style.display = 'flex';
  chartsArea.style.display = 'none';
  summaryRow.style.display = 'none';

  try {
    const data = await apiFetch(`/sales/trends?sku=${sku}&days=${currentDays}`);
    if (!data) return;
    spinner.style.display = 'none';

    const s = data.summary || {};
    document.getElementById('s-avg').textContent = s.avg_daily_sales ?? '—';
    document.getElementById('s-peak-day').textContent = s.peak_day ? formatDate(s.peak_day) : '—';
    document.getElementById('s-peak-qty').textContent = s.peak_qty ? `${s.peak_qty} units` : '';
    document.getElementById('s-total').textContent = s.total ?? '—';
    summaryRow.style.display = 'grid';
    chartsArea.style.display = 'grid';

    const daily = data.daily_sales || [];
    const weekly = data.weekly_totals || [];

    if (lineChart) lineChart.destroy();
    lineChart = new Chart(document.getElementById('line-chart'), {
      type: 'line',
      data: {
        labels: daily.map(d => d.date),
        datasets: [{ label: 'Units sold', data: daily.map(d => d.quantity), borderColor: '#185FA5', backgroundColor: 'rgba(24,95,165,0.08)', fill: true, tension: 0.3, pointRadius: 3 }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
    });

    if (barChart) barChart.destroy();
    barChart = new Chart(document.getElementById('bar-chart'), {
      type: 'bar',
      data: {
        labels: weekly.map(w => w.week),
        datasets: [{ label: 'Weekly total', data: weekly.map(w => w.quantity), backgroundColor: '#185FA5' }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
    });

    const patterns = data.pattern_dates || [];
    patternsCard.style.display = 'block';
    const patternList = document.getElementById('patterns-list');
    if (!patterns.length) {
      patternList.innerHTML = '<span class="text-muted" style="font-size:13px;">No significant patterns detected in this period.</span>';
    } else {
      patternList.innerHTML = patterns.map(p => `<span class="badge badge-warning" style="margin-right:8px;margin-bottom:8px;">${p}</span>`).join('');
    }
  } catch (err) {
    spinner.style.display = 'none';
  }
}

document.getElementById('sku-select').addEventListener('change', e => loadTrends(e.target.value));

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentDays = parseInt(btn.dataset.days);
    loadTrends(document.getElementById('sku-select').value);
  });
});

loadSkus();
