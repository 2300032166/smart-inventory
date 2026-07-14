/* ═══════════════════════════════════════════════════════════════
   SIRA Customer Storefront — Shared JS
   ═══════════════════════════════════════════════════════════════ */

const CAPI = '/api';

// ── Auth ──────────────────────────────────────────────────────────────────────
function cGetToken()  { return localStorage.getItem('c_token'); }
function cGetName()   { return localStorage.getItem('c_name'); }
function cGetId()     { return localStorage.getItem('c_id'); }
function cGetEmail()  { return localStorage.getItem('c_email'); }

function cParseJwt(token) {
  try { return JSON.parse(atob(token.split('.')[1])); } catch { return null; }
}
function cTokenExpired(token) {
  const p = cParseJwt(token);
  return !p || !p.exp || Date.now() >= p.exp * 1000;
}
function cCheckAuth() {
  const t = cGetToken();
  if (!t || cTokenExpired(t)) {
    localStorage.removeItem('c_token');
    localStorage.removeItem('c_name');
    localStorage.removeItem('c_id');
    localStorage.removeItem('c_email');
    window.location.href = 'login.html';
    return false;
  }
  return true;
}
function cLogout() {
  localStorage.removeItem('c_token');
  localStorage.removeItem('c_name');
  localStorage.removeItem('c_id');
  localStorage.removeItem('c_email');
  window.location.href = 'login.html';
}

// ── API Fetch ─────────────────────────────────────────────────────────────────
async function cFetch(url, opts = {}) {
  const token = cGetToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(opts.headers || {}),
  };
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
    opts.body = JSON.stringify(opts.body);
  }
  if (opts.body instanceof FormData) delete headers['Content-Type'];

  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), 30000);
  try {
    const res = await fetch(CAPI + url, { ...opts, headers, signal: ctrl.signal });
    clearTimeout(tid);
    if (res.status === 401 || res.status === 403) {
      localStorage.removeItem('c_token');
      window.location.href = 'login.html';
      return null;
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { const e = await res.json(); detail = e.detail || JSON.stringify(e); } catch {}
      throw new Error(detail);
    }
    const ct = res.headers.get('content-type') || '';
    return ct.includes('application/json') ? res.json() : res.text();
  } catch (err) {
    clearTimeout(tid);
    if (err.name === 'AbortError') throw new Error('Request timed out');
    throw err;
  }
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function cToast(msg, type = 'info') {
  const t = document.createElement('div');
  t.className = `c-toast ${type}`;
  const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
  t.innerHTML = `<span>${icons[type] || 'ℹ'}</span><span>${msg}</span>`;
  document.body.appendChild(t);
  requestAnimationFrame(() => { requestAnimationFrame(() => t.classList.add('show')); });
  setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, 3500);
}

// image helpers removed — no product images used

// ── Stars ─────────────────────────────────────────────────────────────────────
function cStars(rating) {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5;
  let s = '★'.repeat(full);
  if (half) s += '½';
  s += '☆'.repeat(5 - full - (half ? 1 : 0));
  return s;
}

// ── Format ────────────────────────────────────────────────────────────────────
function cFmtPrice(n) {
  return '₹' + Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}
function cFmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }); }
  catch { return iso; }
}
function cFmtDateTime(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  catch { return iso; }
}
function cTimeAgo(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── Cart badge updater ────────────────────────────────────────────────────────
async function cUpdateCartBadge() {
  if (!cGetToken() || cTokenExpired(cGetToken())) return;
  try {
    const data = await cFetch('/customer-orders/cart');
    if (!data) return;
    document.querySelectorAll('.c-cart-count').forEach(el => {
      el.textContent = data.count;
      el.style.display = data.count > 0 ? 'flex' : 'none';
    });
  } catch {}
}

// ── Notification badge updater ────────────────────────────────────────────────
async function cUpdateNotifBadge() {
  if (!cGetToken() || cTokenExpired(cGetToken())) return;
  try {
    const data = await cFetch('/customer-orders/notifications');
    if (!data) return;
    const unread = data.filter(n => n.is_read === 'False' || n.is_read === false).length;
    document.querySelectorAll('.c-notif-count').forEach(el => {
      el.textContent = unread;
      el.style.display = unread > 0 ? 'flex' : 'none';
    });
  } catch {}
}

// ── Wishlist toggle helper ────────────────────────────────────────────────────
async function cToggleWishlist(sku, btn) {
  try {
    const data = await cFetch(`/customer-orders/wishlist/${sku}`, { method: 'POST' });
    if (!data) return;
    if (btn) {
      btn.classList.toggle('active', data.in_wishlist);
      btn.title = data.in_wishlist ? 'Remove from wishlist' : 'Add to wishlist';
    }
    cToast(data.message, data.in_wishlist ? 'success' : 'info');
  } catch (e) { cToast(e.message, 'error'); }
}

// ── Add to cart helper ────────────────────────────────────────────────────────
async function cAddToCart(sku, qty = 1, btn = null) {
  try {
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    const data = await cFetch('/customer-orders/cart', { method: 'POST', body: { sku, quantity: qty } });
    if (!data) return;
    cToast(data.message, 'success');
    cUpdateCartBadge();
  } catch (e) { cToast(e.message, 'error'); }
  finally { if (btn) { btn.disabled = false; btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg> Add'; }
  }
}

// ── Product Card HTML ────────────────────────────────────────────────────────
function cProductCard(p, extraClass = '') {
  const disc = p.discount_percent > 0
    ? `<span class="c-card-original-price">${cFmtPrice(p.original_price)}</span>
       <span class="c-card-discount">${p.discount_percent}% OFF</span>` : '';
  const stockDot = p.in_stock
    ? `<span class="c-stock-dot in"></span><span>In Stock</span>`
    : `<span class="c-stock-dot out"></span><span>Out of Stock</span>`;
  const catColor = p.category_color || '#6366f1';

  return `
  <div class="c-card ${extraClass}" style="border-top: 3px solid ${catColor};">
    <!-- Floating wishlist button -->
    <button class="c-card-wish-float" onclick="cToggleWishlist('${p.sku}',this)" title="Wishlist">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
      </svg>
    </button>

    <!-- Card body -->
    <div class="c-card-body">
      <div class="c-card-header">
        <div class="c-card-brand-col">
          ${p.discount_percent > 0 ? `<div class="c-card-disc-text">${p.discount_percent}% OFF</div>` : ''}
          <div class="c-card-brand">${p.brand || '\u00a0'}</div>
        </div>
      </div>
      
      <div class="c-card-name">${p.name}</div>
      
      <div class="c-card-rating">
        <span class="c-card-stars">${cStars(p.rating)}</span>
        <span class="c-card-rating-count">(${p.rating})</span>
      </div>
      
      <div class="c-card-price-row">
        <span class="c-card-price">${cFmtPrice(p.price)}</span>
        ${disc}
      </div>
      
      <div class="c-card-stock-row">${stockDot}</div>
      
      <div class="c-card-actions">
        <button class="c-btn-cart" onclick="cAddToCart('${p.sku}',1,this)" ${p.in_stock ? '' : 'disabled'}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>
          Add to Cart
        </button>
        <a href="customer-product-detail.html?sku=${encodeURIComponent(p.sku)}" class="c-btn-detail" title="View details">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
        </a>
      </div>
    </div>
  </div>`;
}

// ── Customer Sidebar ──────────────────────────────────────────────────────────
function cInjectSidebar(activePage = '') {
  // Create the sidebar element right after the <nav> if it doesn't exist
  let sb = document.getElementById('c-sidebar');
  if (!sb) {
    sb = document.createElement('aside');
    sb.id = 'c-sidebar';
    sb.className = 'c-sidebar';
    const nav = document.querySelector('.c-nav');
    if (nav && nav.nextSibling) {
      document.body.insertBefore(sb, nav.nextSibling);
    } else {
      document.body.appendChild(sb);
    }
  }
  document.body.classList.add('has-sidebar');

  const name     = cGetName() || 'Guest';
  const loggedIn = !!cGetToken() && !cTokenExpired(cGetToken());
  const initials = name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2) || '?';

  const mainLinks = [
    { id: 'dashboard',       icon: '🏠', label: 'Dashboard',     href: 'customer-dashboard.html' },
    { id: 'catalog',         icon: '🛍️', label: 'Shop',          href: 'customer-catalog.html' },
    { id: 'cart',            icon: '🛒', label: 'Cart',           href: 'customer-cart.html',            badge: true, badgeClass: 'c-cart-count' },
    { id: 'orders',          icon: '📦', label: 'My Orders',      href: 'customer-orders.html' },
    { id: 'wishlist',        icon: '❤️', label: 'Wishlist',       href: 'customer-wishlist.html' },
    { id: 'notifications',   icon: '🔔', label: 'Notifications',  href: 'customer-notifications.html',   badge: true, badgeClass: 'c-notif-count' },
  ];
  const acctLinks = [
    { id: 'profile', icon: '👤', label: 'My Profile', href: 'customer-profile.html' },
  ];

  function renderLink({ id, icon, label, href, badge, badgeClass }) {
    const active = activePage === id ? ' active' : '';
    return `<a href="${href}" class="c-sidebar-link${active}">
      <span class="sb-icon">${icon}</span>
      <span>${label}</span>
      ${badge ? `<span class="sb-badge ${badgeClass || ''}"></span>` : ''}
    </a>`;
  }

  sb.innerHTML = `
    ${loggedIn ? `<div class="c-sidebar-user">
      <div class="c-sidebar-avatar">${initials}</div>
      <div style="min-width:0">
        <div class="c-sidebar-uname">${name.split(' ')[0]}</div>
        <div class="c-sidebar-urole">Customer</div>
      </div>
    </div>` : ''}
    <div class="c-sidebar-section-label">Menu</div>
    ${mainLinks.map(renderLink).join('')}
    <div class="c-sidebar-divider"></div>
    <div class="c-sidebar-section-label">Account</div>
    ${acctLinks.map(renderLink).join('')}
    <div class="c-sidebar-divider"></div>
    <button class="c-sidebar-link danger" onclick="cLogout()">
      <span class="sb-icon">🚪</span><span>Sign Out</span>
    </button>
  `;
}

// ── Customer Navbar ───────────────────────────────────────────────────────────
function cInjectNav(activePage = '') {
  const nav = document.getElementById('c-nav');
  if (!nav) return;
  const name = cGetName() || '';
  const initials = name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2) || '?';
  const loggedIn = !!cGetToken() && !cTokenExpired(cGetToken());

  nav.innerHTML = `
  <div class="c-nav-inner">
    <a href="customer-dashboard.html" class="c-nav-logo">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
      </svg>
      <div><div>SIRA</div><div class="logo-sub">STORE</div></div>
    </a>
    <div class="c-nav-search" id="c-search-wrap">
      <input type="text" id="c-search-input" placeholder="Search products, brands, categories…" autocomplete="off">
      <button class="c-nav-search-btn" onclick="cDoSearch()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
      </button>
      <div class="search-suggestions" id="c-suggestions"></div>
    </div>
    <div class="c-nav-actions">
      <a href="customer-wishlist.html" class="c-nav-icon-btn" title="Wishlist">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
      </a>
      <a href="customer-cart.html" class="c-nav-icon-btn" title="Cart" style="position:relative">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>
        <span class="c-nav-badge c-cart-count" style="display:none">0</span>
      </a>
      <a href="customer-notifications.html" class="c-nav-icon-btn" title="Notifications" style="position:relative">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
        <span class="c-nav-badge c-notif-count" style="display:none">0</span>
      </a>
      ${loggedIn ? `
      <div class="c-nav-user" id="c-user-menu-btn" onclick="document.getElementById('c-user-dropdown').classList.toggle('show')">
        <div class="c-user-avatar">${initials}</div>
        <div class="c-user-name">${name.split(' ')[0]}</div>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
        <div class="c-nav-dropdown" id="c-user-dropdown">
          <a href="customer-dashboard.html" class="c-dropdown-item">🏠 Dashboard</a>
          <a href="customer-profile.html" class="c-dropdown-item">👤 My Profile</a>
          <a href="customer-orders.html" class="c-dropdown-item">📦 My Orders</a>
          <a href="customer-wishlist.html" class="c-dropdown-item">❤️ Wishlist</a>
          <div class="c-dropdown-divider"></div>
          <div class="c-dropdown-item danger" onclick="cLogout()">🚪 Sign Out</div>
        </div>
      </div>` : `
      <a href="login.html" class="c-btn c-btn-primary c-btn-sm">Sign In</a>`}
    </div>
  </div>`;

  // Close dropdown on outside click
  document.addEventListener('click', e => {
    const btn = document.getElementById('c-user-menu-btn');
    const dd  = document.getElementById('c-user-dropdown');
    if (btn && dd && !btn.contains(e.target)) dd.classList.remove('show');
  });

  // Search handlers
  const inp = document.getElementById('c-search-input');
  if (inp) {
    inp.addEventListener('input', cSearchSuggest);
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') cDoSearch(); });
    inp.addEventListener('blur', () => setTimeout(() => document.getElementById('c-suggestions')?.classList.remove('show'), 200));
  }

  if (loggedIn) {
    cUpdateCartBadge();
    cUpdateNotifBadge();
  }

  // Inject sidebar after nav is ready
  cInjectSidebar(activePage);
}

function cDoSearch() {
  const q = document.getElementById('c-search-input')?.value.trim();
  if (q) window.location.href = `customer-catalog.html?search=${encodeURIComponent(q)}`;
}

let _suggestTimer;
async function cSearchSuggest() {
  clearTimeout(_suggestTimer);
  _suggestTimer = setTimeout(async () => {
    const q = document.getElementById('c-search-input')?.value.trim();
    const box = document.getElementById('c-suggestions');
    if (!box) return;
    if (!q || q.length < 2) { box.classList.remove('show'); return; }
    try {
      const data = await fetch(`${CAPI}/customer-products/search-suggestions?q=${encodeURIComponent(q)}`).then(r => r.json());
      if (!data || !data.length) { box.classList.remove('show'); return; }
      // Build items with safe DOM APIs — no innerHTML interpolation of API data
      const frag = document.createDocumentFragment();
      data.forEach(s => {
        const text = typeof s === 'string' ? s : (s && s.text) || '';
        const cat  = typeof s === 'string' ? '' : (s && s.category) || '';
        if (!text) return;

        const item = document.createElement('div');
        item.className = 'suggestion-item';
        item.addEventListener('click', () => {
          document.getElementById('c-search-input').value = text;
          cDoSearch();
        });

        const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        icon.setAttribute('width', '13'); icon.setAttribute('height', '13');
        icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('fill', 'none');
        icon.setAttribute('stroke', 'currentColor'); icon.setAttribute('stroke-width', '2');
        icon.innerHTML = '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>';

        const textWrap = document.createElement('div');
        const nameEl = document.createElement('div');
        nameEl.className = 'sg-name';
        nameEl.textContent = text;
        textWrap.appendChild(nameEl);
        if (cat) {
          const catEl = document.createElement('div');
          catEl.className = 'sg-cat';
          catEl.textContent = cat;
          textWrap.appendChild(catEl);
        }

        item.appendChild(icon);
        item.appendChild(textWrap);
        frag.appendChild(item);
      });
      box.innerHTML = '';
      box.appendChild(frag);
      box.classList.add('show');
    } catch {}
  }, 180);
}

// ── Export CSV ────────────────────────────────────────────────────────────────
function cExportCsv(headers, rows, filename) {
  const lines = [headers.join(',')];
  rows.forEach(r => lines.push(r.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')));
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
}

// ── Invoice print ─────────────────────────────────────────────────────────────
function cPrintInvoice(order) {
  const items = (order.items || []).map(i =>
    `<tr><td>${i.name}</td><td style="text-align:center">${i.quantity}</td><td style="text-align:right">${cFmtPrice(i.unit_price)}</td><td style="text-align:right">${cFmtPrice(i.total)}</td></tr>`
  ).join('');
  const w = window.open('', '_blank');
  w.document.write(`<!DOCTYPE html><html><head><title>Invoice ${order.order_id}</title>
  <style>body{font-family:Inter,sans-serif;padding:40px;color:#0f172a}h2{color:#2563eb}table{width:100%;border-collapse:collapse;margin:20px 0}th,td{padding:10px;border:1px solid #e2e8f0;font-size:13px}th{background:#f1f5f9;font-weight:600}.total{font-weight:700;font-size:15px}</style>
  </head><body>
  <h2>🛒 SIRA Store — Invoice</h2>
  <p><strong>Order ID:</strong> ${order.order_id}</p>
  <p><strong>Date:</strong> ${cFmtDateTime(order.order_date)}</p>
  <p><strong>Customer:</strong> ${order.customer_name || cGetName()} | ${order.customer_email || cGetEmail()}</p>
  <p><strong>Delivery Address:</strong> ${order.delivery_address}</p>
  <p><strong>Payment:</strong> ${order.payment_method?.toUpperCase()}</p>
  <table><thead><tr><th>Product</th><th>Qty</th><th>Unit Price</th><th>Total</th></tr></thead><tbody>${items}</tbody></table>
  <p class="total">Total Amount: ${cFmtPrice(order.total_amount)}</p>
  <p style="color:#94a3b8;font-size:12px;margin-top:20px">Thank you for shopping with SIRA Store!</p>
  <script>window.print();</script></body></html>`);
  w.document.close();
}
