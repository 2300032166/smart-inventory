requireRole('admin');
initShell();

const DEFAULT_PROMPT = `You are SIRA, the store inventory replenishment advisor. Analyse the following product and generate a plain-English replenishment recommendation.

Product: {product_name} (SKU: {sku})
Current stock: {current_stock} {unit}
Average daily sales (last 30 days): {avg_daily_sales} {unit}/day
Days of stock remaining: {days_remaining} days
Supplier lead time: {lead_time_days} days
Calculated recommended order quantity: {recommended_qty} {unit}
Payday spike detected: {payday_spike}
Declining trend: {declining_trend}

Override history (last 5 decisions for this product):
{override_history_summary}

Write exactly 2-3 sentences explaining WHY this order is recommended, in plain English that a store manager can understand. Mention specific patterns detected. Do not repeat the numbers — the UI already shows them. Do not use bullet points. Just write the reasoning paragraph.`;

async function loadConfig() {
  try {
    const cfg = await apiFetch('/admin/ai-config');
    if (!cfg) return;

    document.getElementById('f-groq-key').value = cfg.groq_api_key || '';
    document.getElementById('f-groq-model').value = cfg.groq_model || 'llama-3.3-70b-versatile';
    document.getElementById('f-threshold').value = cfg.confidence_threshold ?? 60;
    document.getElementById('threshold-val').textContent = cfg.confidence_threshold ?? 60;
    document.getElementById('f-max-items').value = cfg.max_brief_items ?? 10;
    document.getElementById('f-payday').value = (cfg.payday_dates || [25, 26, 27]).join(',');
    document.getElementById('f-cache-hours').value = cfg.brief_cache_hours ?? 6;
    document.getElementById('f-prompt').value = cfg.prompt_template || DEFAULT_PROMPT;
  } catch {}
}

document.getElementById('f-threshold').addEventListener('input', e => {
  document.getElementById('threshold-val').textContent = e.target.value;
});

document.getElementById('toggle-groq-key').addEventListener('click', () => {
  const f = document.getElementById('f-groq-key');
  f.type = f.type === 'password' ? 'text' : 'password';
});

document.getElementById('reset-prompt-btn').addEventListener('click', () => {
  document.getElementById('f-prompt').value = DEFAULT_PROMPT;
});

document.getElementById('test-btn').addEventListener('click', async () => {
  const btn = document.getElementById('test-btn');
  const resultEl = document.getElementById('test-result');
  setLoading(btn, true, 'Test connection');
  resultEl.textContent = '';
  try {
    const body = {
      ai_provider: 'groq',
      groq_api_key: document.getElementById('f-groq-key').value,
      ollama_url: '',
    };
    const res = await apiFetch('/admin/ai-config/test', { method: 'POST', body });
    resultEl.textContent = res.status === 'connected' ? '✓ Connected' : `✗ ${res.error}`;
    resultEl.style.color = res.status === 'connected' ? 'var(--color-success)' : 'var(--color-danger)';
  } catch (err) {
    resultEl.textContent = '✗ ' + err.message;
    resultEl.style.color = 'var(--color-danger)';
  } finally { setLoading(btn, false, 'Test connection'); }
});

document.getElementById('save-btn').addEventListener('click', async () => {
  const btn = document.getElementById('save-btn');
  const msg = document.getElementById('msg');
  const body = {
    ai_provider: 'groq',
    groq_api_key: document.getElementById('f-groq-key').value,
    groq_model: document.getElementById('f-groq-model').value,
    confidence_threshold: parseInt(document.getElementById('f-threshold').value),
    max_brief_items: parseInt(document.getElementById('f-max-items').value),
    payday_dates: document.getElementById('f-payday').value.split(',').map(v => parseInt(v.trim())).filter(Boolean),
    brief_cache_hours: parseInt(document.getElementById('f-cache-hours').value),
    prompt_template: document.getElementById('f-prompt').value,
  };
  setLoading(btn, true, 'Save settings');
  try {
    await apiFetch('/admin/ai-config', { method: 'PUT', body });
    showSuccess(msg, 'Settings saved successfully.');
    setTimeout(() => hideMsg(msg), 3000);
  } catch (err) { showError(msg, err.message); }
  finally { setLoading(btn, false, 'Save settings'); }
});

document.getElementById('test-brief-btn').addEventListener('click', async () => {
  const btn = document.getElementById('test-brief-btn');
  const resultCard = document.getElementById('test-brief-result');
  const output = document.getElementById('test-brief-output');
  setLoading(btn, true, 'Run test brief');
  resultCard.style.display = 'none';
  try {
    const items = await apiFetch('/brief/today');
    if (items && items.length) {
      const first = items[0];
      output.textContent = JSON.stringify(first, null, 2);
      resultCard.style.display = 'block';
    } else {
      output.textContent = 'No items in brief.';
      resultCard.style.display = 'block';
    }
  } catch (err) {
    output.textContent = 'Error: ' + err.message;
    resultCard.style.display = 'block';
  } finally { setLoading(btn, false, 'Run test brief'); }
});

loadConfig();
