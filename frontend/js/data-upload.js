requireRole('admin');
initShell();

let selectedFile = null;
const EXPECTED_COLS = ['InvoiceNo','StockCode','Description','Quantity','InvoiceDate','UnitPrice','CustomerID'];

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const previewSection = document.getElementById('preview-section');

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const f = e.dataTransfer.files[0];
  if (f) handleFile(f);
});
fileInput.addEventListener('change', () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });

function handleFile(file) {
  if (!file.name.endsWith('.csv')) {
    alert('Only .csv files are accepted.'); return;
  }
  selectedFile = file;
  const fd = new FormData();
  fd.append('file', file);
  previewFile(fd);
}

async function previewFile(fd) {
  try {
    const data = await apiFetch('/admin/upload-sales-csv', { method: 'POST', body: fd });
    if (!data) return;

    const colCheck = data.column_check || {};
    const missing = data.missing_columns || [];

    const colCheckEl = document.getElementById('col-check');
    colCheckEl.innerHTML = EXPECTED_COLS.map(c =>
      `<div class="col-check-item ${colCheck[c] ? 'ok' : 'fail'}">${colCheck[c] ? '✓' : '✗'} ${c}</div>`
    ).join('');

    if (missing.length) {
      const warn = document.getElementById('missing-warning');
      warn.textContent = `Missing columns: ${missing.join(', ')}. Please check your file.`;
      warn.className = 'alert-msg alert-msg-error show';
      document.getElementById('confirm-section').style.display = 'none';
    }

    const preview = data.preview || [];
    if (preview.length) {
      const keys = Object.keys(preview[0]);
      const table = `<table><thead><tr>${keys.map(k => `<th>${k}</th>`).join('')}</tr></thead>
        <tbody>${preview.map(row => `<tr>${keys.map(k => `<td>${row[k] ?? ''}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
      document.getElementById('preview-table-wrap').innerHTML = table;
    }

    previewSection.style.display = 'block';

    if (data.status === 'success') {
      showSuccess(document.getElementById('upload-msg'), `✓ ${data.rows} rows uploaded successfully!`);
      document.getElementById('confirm-btn').style.display = 'none';
      loadHistory();
    }
  } catch (err) {
    alert('Upload error: ' + err.message);
  }
}

document.getElementById('confirm-btn').addEventListener('click', async () => {
  if (!selectedFile) return;
  const btn = document.getElementById('confirm-btn');
  const msg = document.getElementById('upload-msg');
  const progress = document.getElementById('upload-progress');
  setLoading(btn, true, 'Confirm & Upload');
  progress.style.display = 'block';

  let pct = 0;
  const interval = setInterval(() => {
    pct = Math.min(pct + 10, 90);
    document.getElementById('progress-fill').style.width = pct + '%';
  }, 200);

  try {
    const fd = new FormData();
    fd.append('file', selectedFile);
    const data = await apiFetch('/admin/upload-sales-csv', { method: 'POST', body: fd });
    clearInterval(interval);
    document.getElementById('progress-fill').style.width = '100%';
    if (data.status === 'success') {
      showSuccess(msg, `✓ ${data.rows} rows uploaded successfully!`);
      btn.style.display = 'none';
      loadHistory();
    } else {
      showError(msg, 'Upload could not be confirmed. Check column mapping.');
    }
  } catch (err) {
    clearInterval(interval);
    showError(msg, err.message);
  } finally { setLoading(btn, false, 'Confirm & Upload'); }
});

async function loadHistory() {
  const spinner = document.getElementById('hist-spinner');
  try {
    const data = await apiFetch('/admin/upload-history');
    if (!data) return;
    spinner.style.display = 'none';
    const tbody = document.getElementById('history-tbody');
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--color-text-hint);padding:24px;">No uploads yet</td></tr>'; return; }
    tbody.innerHTML = data.map(h => `
      <tr>
        <td>${h.filename}</td>
        <td>${formatDateTime(h.date)}</td>
        <td>${h.rows}</td>
        <td><span class="badge ${h.status==='success'?'badge-success':'badge-urgent'}">${h.status}</span></td>
      </tr>`).join('');
  } catch { spinner.style.display = 'none'; }
}

loadHistory();
