requireRole('manager');
initShell();

const role = getRole();

// ── Shared weight state ────────────────────────────────────
const DEFAULT_WEIGHTS = { reliability: 40, leadtime: 30, quality: 20, fillrate: 10 };
let weights = { ...DEFAULT_WEIGHTS };

let pwCurrentProduct   = null;
let pwCurrentSuppliers = [];

// ── Weight sliders (top panel — drives product comparison) ─
['reliability', 'leadtime', 'quality', 'fillrate'].forEach(k => {
  const slider = document.getElementById(`w-${k}`);
  const label  = document.getElementById(`lbl-w-${k}`);
  slider.addEventListener('input', () => {
    weights[k] = parseInt(slider.value);
    label.textContent = weights[k] + '%';
    updateWeightTotal();
    if (pwCurrentSuppliers.length) renderProductComparison();
  });
});

document.getElementById('btn-reset-weights').addEventListener('click', () => {
  weights = { ...DEFAULT_WEIGHTS };
  ['reliability', 'leadtime', 'quality', 'fillrate'].forEach(k => {
    document.getElementById(`w-${k}`).value = weights[k];
    document.getElementById(`lbl-w-${k}`).textContent = weights[k] + '%';
  });
  updateWeightTotal();
  if (pwCurrentSuppliers.length) renderProductComparison();
});

function updateWeightTotal() {
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  const el = document.getElementById('weight-total');
  el.textContent = `Total: ${total}%${total === 100 ? ' ✓' : ' ⚠ (must equal 100%)'}`;
  el.className = 'weight-total ' + (total === 100 ? 'ok' : 'warn');
}

// ── Helper: compute weighted score for a single supplier ───
function pwCustomScore(s) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  if (total === 0) return 0;
  const wR = weights.reliability / total;
  const wL = weights.leadtime    / total;
  const wQ = weights.quality     / total;
  const wF = weights.fillrate    / total;

  const rScore  = s.reliability_score ?? 0;
  const ltScore = Math.max(0, (1 - (s.avg_lead_time ?? 14) / 14)) * 100;
  const qScore  = ((s.quality_rating ?? 0) / 5) * 100;
  const fScore  = s.fill_rate ?? 0;

  return Math.round(wR * rScore + wL * ltScore + wQ * qScore + wF * fScore);
}

// ── Helper: color by reliability score ─────────────────────
function scoreColor(score) {
  if (score >= 90) return '#059669';
  if (score >= 75) return '#2563EB';
  if (score >= 60) return '#D97706';
  return '#DC2626';
}

function starsHtml(q) {
  const r = Math.round(q);
  return '<span class="star-filled">' + '★'.repeat(r) + '</span><span style="color:#CBD5E1;">' + '★'.repeat(5 - r) + '</span>';
}

function levelClass(l) {
  return 'perf-' + (l || 'Average').replace(' ', '-');
}

// ── AI Recommendation text (rule-based, instant) ───────────
function generateRecommendationText(winner, allSuppliers) {
  const strengths = [];

  const byReliability = [...allSuppliers].sort((a, b) => (b.reliability_score ?? 0) - (a.reliability_score ?? 0));
  const byLeadTime    = [...allSuppliers].sort((a, b) => (a.avg_lead_time ?? 99)  - (b.avg_lead_time ?? 99));
  const byOnTime      = [...allSuppliers].sort((a, b) => (b.on_time_pct ?? 0)     - (a.on_time_pct ?? 0));
  const byFill        = [...allSuppliers].sort((a, b) => (b.fill_rate ?? 0)        - (a.fill_rate ?? 0));
  const byQuality     = [...allSuppliers].sort((a, b) => (b.quality_rating ?? 0)   - (a.quality_rating ?? 0));

  if (byReliability[0]?.supplier_id === winner.supplier_id)
    strengths.push(`the highest reliability score (${winner.reliability_score}/100)`);
  if (byLeadTime[0]?.supplier_id === winner.supplier_id)
    strengths.push(`the shortest average lead time (${winner.avg_lead_time} days)`);
  if (byOnTime[0]?.supplier_id === winner.supplier_id)
    strengths.push(`the best on-time delivery rate (${winner.on_time_pct}%)`);
  if (byFill[0]?.supplier_id === winner.supplier_id)
    strengths.push(`the highest fill rate (${winner.fill_rate}%)`);
  if (byQuality[0]?.supplier_id === winner.supplier_id)
    strengths.push(`the top quality rating (${(winner.quality_rating ?? 0).toFixed(1)}/5 ★)`);

  const score = pwCustomScore(winner);
  const n     = allSuppliers.length;

  if (strengths.length === 0) {
    return `${winner.name} achieves the highest weighted composite score of ${score} across all ${n} mapped suppliers, balancing reliability (${winner.reliability_score}), on-time delivery (${winner.on_time_pct}%), lead time (${winner.avg_lead_time} d), fill rate (${winner.fill_rate}%), and quality rating (${(winner.quality_rating ?? 0).toFixed(1)}/5). It is the optimal choice under your current weight configuration.`;
  }

  const last = strengths.pop();
  const list = strengths.length > 0 ? `${strengths.join(', ')}, and ${last}` : last;

  return `${winner.name} is ranked #1 with a weighted score of ${score} because it has ${list} among all ${n} mapped suppliers. Adjust the weight sliders above to re-rank suppliers based on your priorities.`;
}

// ── Render recommendation card + ranked table ──────────────
function renderProductComparison() {
  if (!pwCurrentSuppliers.length) return;

  const list   = [...pwCurrentSuppliers].sort((a, b) => pwCustomScore(b) - pwCustomScore(a));
  const winner = list[0];

  // ── Recommendation card ─────────────────────────────────
  const recEl  = document.getElementById('pw-rec-card');
  const aiText = generateRecommendationText(winner, pwCurrentSuppliers);

  recEl.className = 'pw-rec-card';
  recEl.innerHTML = `
    <div class="pw-rec-inner">
      <div style="flex:0 0 auto;">
        <div class="rec-header">🤖 AI Recommended Supplier</div>
        <div class="rec-name">${winner.name}</div>
        <div class="rec-company">${winner.company_name || ''}</div>
        <div class="pw-rec-chips">
          <span class="pw-rec-chip">Score: ${pwCustomScore(winner)}</span>
          <span class="pw-rec-chip">Reliability: ${winner.reliability_score}</span>
          <span class="pw-rec-chip">On-Time: ${winner.on_time_pct}%</span>
          <span class="pw-rec-chip">Lead: ${winner.avg_lead_time ?? '—'} d</span>
          <span class="pw-rec-chip">Fill: ${winner.fill_rate}%</span>
          <span class="pw-rec-chip">Quality: ${(winner.quality_rating ?? 0).toFixed(1)}/5 ★</span>
        </div>
      </div>
      <div class="pw-rec-why">
        <div class="pw-rec-why-label">Why this supplier?</div>
        <div class="pw-rec-why-text">${aiText}</div>
      </div>
    </div>`;
  recEl.style.display = 'block';

  // ── Ranked table ────────────────────────────────────────
  const tbody = document.getElementById('pw-ranked-tbody');
  tbody.innerHTML = list.map((s, i) => {
    const rank   = i + 1;
    const cs     = pwCustomScore(s);
    const rCls   = rank === 1 ? 'rank-1' : rank === 2 ? 'rank-2' : rank === 3 ? 'rank-3' : 'rank-n';
    const rowCls = rank === 1 ? 'best-row' : '';
    const color  = scoreColor(s.reliability_score ?? 0);
    const recommended = rank === 1
      ? '<span class="pw-badge-recommended">Recommended</span>'
      : '';
    return `<tr class="${rowCls}">
      <td><span class="rank-badge ${rCls}">${rank}</span></td>
      <td>
        <div style="font-weight:600;">${s.name}${recommended}</div>
        <div style="font-size:11px;color:var(--color-text-hint);">${s.company_name || ''}</div>
      </td>
      <td>
        <div class="score-bar-wrap">
          <div class="score-bar-track"><div class="score-bar-fill" style="width:${s.reliability_score ?? 0}%;background:${color};"></div></div>
          <span style="font-weight:700;color:${color};min-width:32px;">${s.reliability_score ?? '—'}</span>
        </div>
        <div style="font-size:10px;color:var(--color-text-hint);margin-top:2px;">Weighted: ${cs}</div>
      </td>
      <td style="font-weight:600;color:${(s.on_time_pct ?? 0) >= 90 ? 'var(--color-success)' : 'inherit'};">${s.on_time_pct ?? '—'}%</td>
      <td>${s.avg_lead_time ?? '—'} d</td>
      <td>${(s.avg_delay ?? 0) > 0 ? '+' + s.avg_delay + ' d' : '—'}</td>
      <td>${s.fill_rate ?? '—'}%</td>
      <td>${starsHtml(s.quality_rating ?? 0)} <span style="font-size:11px;color:var(--color-text-hint);">(${(s.quality_rating ?? 0).toFixed(1)})</span></td>
      <td><span class="perf-badge ${levelClass(s.performance_level)}">${s.performance_level || '—'}</span></td>
      <td><a href="supplier-dashboard.html?sid=${s.supplier_id}" class="btn btn-secondary btn-sm">View</a></td>
    </tr>`;
  }).join('');

  document.getElementById('pw-ranked-card').style.display = 'block';
}

// ── Product search ─────────────────────────────────────────
document.getElementById('pw-btn-search').addEventListener('click', pwSearchProduct);
document.getElementById('pw-prod-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') pwSearchProduct();
});

async function pwSearchProduct() {
  const q         = document.getElementById('pw-prod-input').value.trim();
  const resultsEl = document.getElementById('pw-prod-results');
  if (!q) { resultsEl.innerHTML = '<div style="color:var(--color-warning);font-size:13px;">Please enter a product name or SKU.</div>'; return; }

  resultsEl.innerHTML = '<div style="color:var(--color-text-hint);font-size:13px;padding:6px 0;">Searching…</div>';
  document.getElementById('pw-rec-card').style.display    = 'none';
  document.getElementById('pw-ranked-card').style.display = 'none';

  try {
    const products = await apiFetch('/inventory/products');
    const matches  = (products || []).filter(p =>
      p.sku.toLowerCase().includes(q.toLowerCase()) ||
      p.name.toLowerCase().includes(q.toLowerCase())
    ).slice(0, 8);

    if (!matches.length) {
      resultsEl.innerHTML = '<div style="color:var(--color-text-hint);font-size:13px;padding:6px 0;">No products found. Try a different name or SKU.</div>';
      return;
    }

    if (matches.length === 1) {
      resultsEl.innerHTML = '';
      await pwSelectProduct(matches[0]);
    } else {
      resultsEl.innerHTML =
        '<div style="font-size:12px;font-weight:500;margin-bottom:8px;color:var(--color-text-secondary);">Multiple matches — select a product:</div>' +
        matches.map(p => `
          <button class="btn btn-secondary btn-sm" style="margin:3px;font-size:12px;"
            onclick="pwSelectProduct({sku:'${p.sku}',name:'${p.name.replace(/'/g,"\\'")}',category:'${(p.category||'').replace(/'/g,"\\'")}'})"
          >${p.name} <span style="opacity:.6">(${p.sku})</span></button>`).join('');
    }
  } catch (e) {
    resultsEl.innerHTML = `<div style="color:var(--color-danger);font-size:13px;">${e.message}</div>`;
  }
}

async function pwSelectProduct(prod) {
  const resultsEl = document.getElementById('pw-prod-results');
  const spinner   = document.getElementById('pw-spinner');

  resultsEl.innerHTML = `<div style="font-size:12px;color:var(--color-text-secondary);padding:4px 0;">Loading suppliers for <strong>${prod.name}</strong>…</div>`;
  spinner.style.display = 'flex';

  try {
    const sups = await apiFetch(`/suppliers/product/${prod.sku}/suppliers`);
    spinner.style.display = 'none';

    if (!sups || !sups.length) {
      resultsEl.innerHTML = `
        <div style="color:var(--color-warning);font-size:13px;padding:6px 0;">
          No suppliers are mapped to <strong>${prod.name}</strong>.
          <a href="suppliers.html" style="color:var(--color-primary);margin-left:4px;">Add a mapping →</a>
        </div>`;
      document.getElementById('pw-selected-badge').style.display = 'none';
      return;
    }

    pwCurrentProduct   = prod;
    pwCurrentSuppliers = sups;

    resultsEl.innerHTML = `<div style="font-size:12px;color:var(--color-success);padding:4px 0;">✓ Found <strong>${sups.length}</strong> supplier${sups.length > 1 ? 's' : ''} for <strong>${prod.name}</strong> (${prod.sku})</div>`;

    const badge = document.getElementById('pw-selected-badge');
    badge.textContent   = prod.name;
    badge.style.display = 'inline-block';

    document.getElementById('pw-ranked-title').textContent   = prod.name;
    document.getElementById('pw-supplier-count').textContent = `${sups.length} supplier${sups.length > 1 ? 's' : ''}`;

    renderProductComparison();

  } catch (e) {
    spinner.style.display = 'none';
    resultsEl.innerHTML = `<div style="color:var(--color-danger);font-size:13px;">${e.message}</div>`;
  }
}

window.pwSelectProduct = pwSelectProduct;

// Boot
updateWeightTotal();
