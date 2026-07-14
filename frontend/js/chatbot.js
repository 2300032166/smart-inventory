// ── SIRABot Chatbot ──────────────────────────────────────────────────────
// Self-contained module — injected globally via initShell() in app.js
// Uses the dedicated CHATBOT_GROQ_API_KEY (separate from Daily Brief key)

(function () {
  'use strict';

  // ── State ───────────────────────────────────────────────────────────────────
  const STORAGE_KEY_HISTORY = 'inventorybot_history';
  const STORAGE_KEY_OPEN = 'inventorybot_open';

  let history = [];
  try {
    const saved = localStorage.getItem(STORAGE_KEY_HISTORY);
    if (saved) history = JSON.parse(saved);
  } catch (e) {}

  let isOpen = localStorage.getItem(STORAGE_KEY_OPEN) === 'true';
  let isTyping = false;

  function saveState() {
    localStorage.setItem(STORAGE_KEY_HISTORY, JSON.stringify(history));
    localStorage.setItem(STORAGE_KEY_OPEN, isOpen.toString());
  }

  // ── Quick prompts ────────────────────────────────────────────────────────────
  const QUICK_PROMPTS = [
    '📦 What needs reordering today?',
    '⚠️ Show me active alerts',
    '💀 Any dead stock issues?',
    '📊 Inventory summary',
    '🚚 Orders in transit?',
    '🏭 List all suppliers',
    '🚚 Upcoming stock',
    '🏷️ Active discounts',
    '📉 Stockout products',
    '⏳ Expiring in 7 days',
  ];

  // ── HTML Template ────────────────────────────────────────────────────────────
  function createChatbotHTML() {
    return `
      <!-- Floating bubble -->
      <button id="cb-bubble" class="cb-bubble" aria-label="Open SIRABot" title="Ask SIRABot">
        <svg id="cb-icon-open" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <svg id="cb-icon-close" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="display:none">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
        <span class="cb-pulse"></span>
      </button>

      <!-- Chat panel -->
      <div id="cb-panel" class="cb-panel" role="dialog" aria-label="SIRABot Chat" aria-hidden="true">
        <!-- Header -->
        <div class="cb-header">
          <div class="cb-header-info">
            <div class="cb-avatar">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
              </svg>
            </div>
            <div>
              <div class="cb-title">SIRABot</div>
              <div class="cb-subtitle" id="cb-status">● Online · Powered by Groq AI</div>
            </div>
          </div>
          <div class="cb-header-actions">
            <button class="cb-clear-btn" id="cb-clear" title="Clear chat">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
              </svg>
            </button>
            <button class="cb-close-btn" id="cb-close" title="Close">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- Messages -->
        <div class="cb-messages" id="cb-messages">
          <!-- Welcome message inserted by JS -->
        </div>

        <!-- Quick prompts -->
        <div class="cb-quick-prompts" id="cb-quick-prompts"></div>

        <!-- Input area -->
        <div class="cb-input-area">
          <textarea
            id="cb-input"
            class="cb-input"
            placeholder="Ask about inventory, orders, alerts…"
            rows="1"
            maxlength="500"
            aria-label="Chat message input"
          ></textarea>
          <button id="cb-send" class="cb-send-btn" title="Send message" disabled>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>
      </div>
    `;
  }

  // ── Render helpers ───────────────────────────────────────────────────────────
  function renderMarkdown(text) {
    // Simple markdown-lite: bold, bullets, line breaks
    return text
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/^[-•] (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`)
      .replace(/\n/g, '<br>');
  }

  function createMessageEl(role, content) {
    const el = document.createElement('div');
    el.className = `cb-msg cb-msg-${role}`;

    if (role === 'assistant') {
      el.innerHTML = `
        <div class="cb-msg-avatar">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
          </svg>
        </div>
        <div class="cb-msg-bubble">${renderMarkdown(content)}</div>
      `;
    } else {
      el.innerHTML = `<div class="cb-msg-bubble">${escapeHtml(content)}</div>`;
    }
    return el;
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/\n/g, '<br>');
  }

  // ── Analyzing indicator (cycling status steps) ──────────────────────────────


  function showAnalyzing() {
    const el = document.createElement('div');
    el.className = 'cb-msg cb-msg-assistant cb-typing-row';
    el.id = 'cb-typing';
    el.innerHTML = `
      <div class="cb-msg-avatar">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
        </svg>
      </div>
      <div class="cb-msg-bubble cb-typing-bubble">
        <div class="cb-dot"></div>
        <div class="cb-dot"></div>
        <div class="cb-dot"></div>
      </div>
    `;
    document.getElementById('cb-messages').appendChild(el);
    scrollToBottom();
  }

  function removeTyping() {
    document.getElementById('cb-typing')?.remove();
  }


  function scrollToBottom() {
    const msgs = document.getElementById('cb-messages');
    if (msgs) msgs.scrollTop = msgs.scrollHeight;
  }

  function appendMessage(role, content) {
    const msgs = document.getElementById('cb-messages');
    if (!msgs) return;
    msgs.appendChild(createMessageEl(role, content));
    scrollToBottom();
  }

  // ── Quick prompts ────────────────────────────────────────────────────────────
  function renderQuickPrompts(show = true) {
    const container = document.getElementById('cb-quick-prompts');
    if (!container) return;
    if (!show || history.length > 0) {
      container.style.display = 'none';
      return;
    }
    container.style.display = 'flex';
    container.innerHTML = QUICK_PROMPTS.map(p => `
      <button class="cb-chip" data-prompt="${p}">${p}</button>
    `).join('');
    container.querySelectorAll('.cb-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        const msg = btn.dataset.prompt.replace(/^[^\s]+ /, ''); // strip emoji
        document.getElementById('cb-input').value = msg;
        sendMessage();
      });
    });
  }

  // ── API call ─────────────────────────────────────────────────────────────────
  async function sendMessage() {
    const input = document.getElementById('cb-input');
    const sendBtn = document.getElementById('cb-send');
    if (!input || isTyping) return;

    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    input.style.height = 'auto';
    sendBtn.disabled = true;
    isTyping = true;

    // Hide quick prompts once conversation starts
    renderQuickPrompts(false);

    // Show user message
    appendMessage('user', text);
    history.push({ role: 'user', content: text });
    saveState();

    // Show typing indicator after a short delay (to avoid flicker for instant direct responses)
    let typingTimeout = setTimeout(() => showAnalyzing(), 300);


    let fullReply = '';
    let assistantMsgEl = null;
    let bubbleEl = null;

    try {
      const token = localStorage.getItem('token');
      const response = await fetch('/api/chatbot/message', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message: text,
          history: history.slice(-16),
        }),
      });

      if (!response.ok) {
        clearTimeout(typingTimeout);
        removeTyping();
        let detail = `Error ${response.status}`;
        try { const err = await response.json(); detail = err.detail || detail; } catch {}
        appendMessage('assistant', `⚠️ ${detail}`);
      } else {


        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n\n');
          buffer = lines.pop(); // Keep potentially partial line in buffer

          for (const line of lines) {
            const dataLine = line.split('\n').find(l => l.startsWith('data: '));
            if (!dataLine) continue;

            const dataStr = dataLine.slice(6).trim();
            if (dataStr === '[DONE]' || !dataStr) continue;
            
            try {
              const data = JSON.parse(dataStr);
              if (data.content) {
                if (!fullReply) {
                  // First chunk! Remove typing indicator and create actual bubble
                  clearTimeout(typingTimeout);
                  removeTyping();
                  assistantMsgEl = createMessageEl('assistant', '');
                  bubbleEl = assistantMsgEl.querySelector('.cb-msg-bubble');
                  document.getElementById('cb-messages').appendChild(assistantMsgEl);
                }
                fullReply += data.content;
                bubbleEl.innerHTML = renderMarkdown(fullReply);
                scrollToBottom();
              } else if (data.error) {
                bubbleEl.innerHTML = `⚠️ ${data.error}`;
              }
            } catch (e) {
              console.error('Error parsing stream chunk:', e, dataStr);
            }
          }
        }
        
        if (fullReply) {
          history.push({ role: 'assistant', content: fullReply });
          saveState();
        } else if (bubbleEl && !bubbleEl.innerText) {
          bubbleEl.innerText = 'No response from AI.';
        }
      }
    } catch (err) {
      clearTimeout(typingTimeout);
      removeTyping();
      console.error('Chatbot error:', err);
      appendMessage('assistant', '⚠️ Network error. Please check your connection and try again.');
    }

    isTyping = false;
    sendBtn.disabled = false;
    input.focus();
    scrollToBottom();
  }

  // ── Panel open/close ─────────────────────────────────────────────────────────
  function openPanel() {
    isOpen = true;
    saveState();
    const panel = document.getElementById('cb-panel');
    const bubble = document.getElementById('cb-bubble');
    const iconOpen = document.getElementById('cb-icon-open');
    const iconClose = document.getElementById('cb-icon-close');
    if (!panel || !bubble) return;

    panel.classList.add('cb-panel-open');
    panel.setAttribute('aria-hidden', 'false');
    bubble.classList.add('cb-bubble-active');
    iconOpen.style.display = 'none';
    iconClose.style.display = 'block';

    // Focus input
    setTimeout(() => document.getElementById('cb-input')?.focus(), 200);
  }

  function closePanel() {
    isOpen = false;
    saveState();
    const panel = document.getElementById('cb-panel');
    const bubble = document.getElementById('cb-bubble');
    const iconOpen = document.getElementById('cb-icon-open');
    const iconClose = document.getElementById('cb-icon-close');
    if (!panel || !bubble) return;

    panel.classList.remove('cb-panel-open');
    panel.setAttribute('aria-hidden', 'true');
    bubble.classList.remove('cb-bubble-active');
    iconOpen.style.display = 'block';
    iconClose.style.display = 'none';
  }

  function clearChat() {
    history.length = 0;
    localStorage.removeItem(STORAGE_KEY_HISTORY);
    const msgs = document.getElementById('cb-messages');
    if (msgs) msgs.innerHTML = '';
    insertWelcome();
    renderQuickPrompts(true);
  }

  function insertWelcome() {
    const name = localStorage.getItem('name') || 'there';
    const msgs = document.getElementById('cb-messages');
    if (!msgs) return;
    const el = document.createElement('div');
    el.className = 'cb-welcome';
    el.innerHTML = `
      <div class="cb-welcome-icon">🤖</div>
      <div class="cb-welcome-text">
        <strong>Hi ${name.split(' ')[0]}! I'm SIRABot</strong><br>
        I can answer questions about your inventory, reorders, alerts, and more. Try a quick prompt below or type your question!
      </div>
    `;
    msgs.appendChild(el);
  }

  // ── Auto-resize textarea ─────────────────────────────────────────────────────
  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }

  // ── Init ─────────────────────────────────────────────────────────────────────
  function init() {
    // Guard against double-injection if initShell() is called twice
    if (document.getElementById('cb-root')) return;

    // Skip on login / forgot-password pages
    const page = location.pathname;
    if (page.includes('login') || page.includes('forgot')) return;

    // Inject HTML into body
    const wrapper = document.createElement('div');
    wrapper.id = 'cb-root';
    wrapper.innerHTML = createChatbotHTML();
    document.body.appendChild(wrapper);

    // Insert welcome + history
    insertWelcome();
    if (history.length > 0) {
      history.forEach(msg => appendMessage(msg.role, msg.content));
    }
    renderQuickPrompts(true);

    // Restore open state
    if (isOpen) {
      setTimeout(openPanel, 500); // Slight delay for smoother appearance
    }

    // Events
    document.getElementById('cb-bubble').addEventListener('click', () => {
      isOpen ? closePanel() : openPanel();
    });

    document.getElementById('cb-close').addEventListener('click', closePanel);
    document.getElementById('cb-clear').addEventListener('click', clearChat);

    const input = document.getElementById('cb-input');
    const sendBtn = document.getElementById('cb-send');

    input.addEventListener('input', () => {
      autoResize(input);
      sendBtn.disabled = input.value.trim().length === 0;
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!sendBtn.disabled) sendMessage();
      }
    });

    sendBtn.addEventListener('click', sendMessage);

    // Close on outside click
    document.addEventListener('click', (e) => {
      const panel = document.getElementById('cb-panel');
      const bubble = document.getElementById('cb-bubble');
      if (isOpen && panel && !panel.contains(e.target) && !bubble.contains(e.target)) {
        closePanel();
      }
    });
  }

  // Wait for DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
