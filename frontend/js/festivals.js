// Festival Inventory Planner — list page logic
requireRole('manager');

let allFestivals = [];

document.addEventListener('DOMContentLoaded', async () => {
  await loadFestivals();
  document.getElementById('f-search').addEventListener('input', renderFestivals);
  document.getElementById('f-status').addEventListener('change', renderFestivals);
});

async function loadFestivals() {
  const container = document.getElementById('festivals-container');
  try {
    const data = await apiFetch('/festival-planner/festivals');
    allFestivals = data.festivals || [];
    renderFestivals();
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Failed to load festivals</div></div>`;
  }
}

function statusBadgeClass(status) {
  if (status === 'Ongoing') return 'badge-success';
  if (status === 'Upcoming') return 'badge-normal';
  return 'badge-gray';
}

function cardAccentClass(status) {
  if (status === 'Upcoming') return 'card-upcoming';
  if (status === 'Ongoing') return 'card-ongoing';
  return 'card-completed';
}

function dotClass(status) {
  if (status === 'Upcoming') return 'dot-upcoming';
  if (status === 'Ongoing') return 'dot-ongoing';
  return 'dot-completed';
}

function sectionTitle(status) {
  const map = { Upcoming: 'Upcoming', Ongoing: 'Happening Now', Completed: 'Completed' };
  return map[status] || status;
}

function FestivalCard(f) {
  const daysText = f.status === 'Upcoming'
    ? `<span class="fc-days">⏳ ${f.days_remaining} day${f.days_remaining === 1 ? '' : 's'} remaining</span>`
    : (f.status === 'Ongoing'
      ? `<span class="fc-days fc-days-live">🔥 Happening now</span>`
      : `<span class="fc-days fc-days-done">✅ Completed</span>`);

  return `
    <div class="festival-card ${cardAccentClass(f.status)}" onclick="location.href='festival-detail.html?id=${f.festival_id}'">
      <div class="fc-top">
        <span class="badge ${statusBadgeClass(f.status)}">${f.status}</span>
      </div>
      <div class="fc-name">${f.festival_name}</div>
      <div class="fc-dates">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
        ${formatDate(f.start_date)} – ${formatDate(f.end_date)}
      </div>
      <div class="fc-duration">${f.duration_days} day${f.duration_days === 1 ? '' : 's'} duration</div>
      <div class="fc-meta-row">
        ${daysText}
        <span class="fc-products-count">20 products mapped</span>
      </div>
    </div>`;
}

function renderFestivals() {
  const container = document.getElementById('festivals-container');
  const search = document.getElementById('f-search').value.trim().toLowerCase();
  const statusFilter = document.getElementById('f-status').value;

  let filtered = allFestivals.filter(f => {
    if (search && !f.festival_name.toLowerCase().includes(search)) return false;
    if (statusFilter && f.status !== statusFilter) return false;
    return true;
  });

  document.getElementById('filter-count').textContent = `${filtered.length} of ${allFestivals.length} festivals`;

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">🎉</div><div class="empty-title">No festivals match your filters</div></div>`;
    return;
  }

  // Group by status in fixed order
  const order = ['Upcoming', 'Ongoing', 'Completed'];
  const groups = {};
  for (const f of filtered) {
    if (!groups[f.status]) groups[f.status] = [];
    groups[f.status].push(f);
  }

  let html = '';
  for (const status of order) {
    const items = groups[status];
    if (!items || items.length === 0) continue;
    html += `
      <div class="fest-section">
        <div class="fest-section-title"><span class="dot ${dotClass(status)}"></span>${sectionTitle(status)} <span style="color:#94a3b8;margin-left:6px">(${items.length})</span></div>
        <div class="festival-grid">
          ${items.map(FestivalCard).join('')}
        </div>
      </div>`;
  }

  container.innerHTML = html;
}
