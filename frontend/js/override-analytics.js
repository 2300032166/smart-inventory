requireRole('admin');
initShell();

let lineChart = null, doughnutChart = null, barChart = null;

async function load() {
  const spinner = document.getElementById('ana-spinner');
  const dateFrom = document.getElementById('date-from').value;
  const dateTo = document.getElementById('date-to').value;
  let url = '/analytics/overrides';
  const params = [];
  if (dateFrom) params.push(`date_from=${dateFrom}`);
  if (dateTo) params.push(`date_to=${dateTo}`);
  if (params.length) url += '?' + params.join('&');

  try {
    const data = await apiFetch(url);
    if (!data) return;
    spinner.style.display = 'none';

    document.getElementById('s-total').textContent = data.total_suggestions;
    document.getElementById('s-approved').textContent = data.approved_pct + '%';
    document.getElementById('s-overridden').textContent = data.overridden_pct + '%';
    document.getElementById('s-skipped').textContent = data.skipped_pct + '%';

    const timeline = data.approval_rate_over_time || [];
    if (lineChart) lineChart.destroy();
    lineChart = new Chart(document.getElementById('line-chart'), {
      type: 'line',
      data: {
        labels: timeline.map(t => t.date),
        datasets: [{ label: 'Approval rate (%)', data: timeline.map(t => t.approval_rate), borderColor: '#0F6E56', backgroundColor: 'rgba(15,110,86,0.08)', fill: true, tension: 0.3, spanGaps: true }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { min: 0, max: 100 } } }
    });

    const reasons = data.reason_breakdown || {};
    const reasonKeys = Object.keys(reasons);
    if (doughnutChart) doughnutChart.destroy();
    doughnutChart = new Chart(document.getElementById('doughnut-chart'), {
      type: 'doughnut',
      data: {
        labels: reasonKeys,
        datasets: [{ data: reasonKeys.map(k => reasons[k]), backgroundColor: ['#185FA5','#0F6E56','#854F0B','#A32D2D','#9C9A92'] }]
      },
      options: { responsive: true, maintainAspectRatio: false }
    });

    const topProducts = data.top_overridden_products || [];
    if (barChart) barChart.destroy();
    barChart = new Chart(document.getElementById('bar-chart'), {
      type: 'bar',
      data: {
        labels: topProducts.map(p => p.product_name || p.sku),
        datasets: [{ label: 'Override count', data: topProducts.map(p => p.count), backgroundColor: '#854F0B' }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } } }
    });

    const delta = data.quantity_delta_products || [];
    const tbody = document.getElementById('delta-tbody');
    if (!delta.length) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--color-text-hint);padding:24px;">No override data yet</td></tr>';
    } else {
      tbody.innerHTML = delta.map(d => `
        <tr>
          <td>${d.product_name}</td>
          <td style="font-family:monospace;font-size:12px;">${d.sku}</td>
          <td>${d.override_count}</td>
          <td>${d.avg_qty_delta}</td>
        </tr>`).join('');
    }
  } catch { spinner.style.display = 'none'; }
}

document.getElementById('filter-btn').addEventListener('click', load);
load();
