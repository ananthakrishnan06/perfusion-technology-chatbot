// Perfusion AI - Client Application Controller
// Cardiovascular Decision Support & Knowledge Workspace

const state = {
  activeView: 'home',
  selectedDepth: 'detailed',
  chatDepth: 'detailed',
  chatHistory: [],
  isChatSending: false,
  currentCitations: [],
  currentAnswer: null,
  documents: [],
  isQuerying: false,
  activeDocId: null,
  activeDocName: null,
  currentConversationId: localStorage.getItem('perfusion_current_conv_id') || null,
  user: JSON.parse(localStorage.getItem('perfusion_user') || 'null'),
  authConfig: { google_client_id: '', enabled: false, mode: 'setup_required' },
};

// Dynamic API Endpoint Resolver (supports Vercel proxy rewrite & direct Azure App Service routing)
function apiEndpoint(path) {
  const base = (window.PERFUSION_CONFIG && window.PERFUSION_CONFIG.API_BASE_URL)
    || localStorage.getItem('perfusion_api_base_url')
    || '';
  if (!path.startsWith('/')) path = '/' + path;
  if (!base) return path;
  return `${base.replace(/\/+$/, '')}${path}`;
}

// ==========================================
// 1. INITIALIZATION & HEALTH CHECK
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) {
    lucide.createIcons();
  }

  // Handle Google OAuth 2.0 redirect parameters (?auth_token=... or ?auth_error=...)
  const urlParams = new URLSearchParams(window.location.search);
  const authToken = urlParams.get('auth_token');
  const authError = urlParams.get('auth_error');

  if (authToken) {
    fetch(apiEndpoint('/api/v1/auth/me'), {
      headers: { 'Authorization': `Bearer ${authToken}` }
    })
    .then(r => r.json())
    .then(user => {
      if (user && user.authenticated) {
        state.user = user;
        localStorage.setItem('perfusion_user', JSON.stringify(user));
        renderAuthUI();
        bypassLoginToGuest();
        showAuthNotification(`Signed in with Google as ${user.name}`);
      }
    })
    .catch(console.error);

    window.history.replaceState({}, document.title, window.location.pathname);
  } else if (authError) {
    showToastNotification(`Google sign-in error: ${authError}`, 'error');
    window.history.replaceState({}, document.title, window.location.pathname);
  }

  initAuth();
  checkHealth();
  setupKeyboardShortcuts();
  calculateBSA();
  calculateFlowRate();

  // Auto-resize chat textarea for multi-line and large prompts
  const chatInputEl = document.getElementById('chat-input');
  if (chatInputEl) {
    chatInputEl.addEventListener('input', () => {
      chatInputEl.style.height = 'auto';
      chatInputEl.style.height = Math.min(chatInputEl.scrollHeight, 220) + 'px';
    });
  }

  // Control initial view based on auth session
  if (state.user && state.user.authenticated) {
    bypassLoginToGuest();
  } else {
    openLoginScreen();
  }

  // Restore active conversation session if saved
  if (state.currentConversationId) {
    loadConversationSession(state.currentConversationId, false, false);
  }
});

async function checkHealth() {
  const dot = document.getElementById('health-dot');
  const status = document.getElementById('health-status');

  try {
    const res = await fetch(apiEndpoint('/health'));
    if (res.ok) {
      const data = await res.json();
      if (status) status.textContent = 'System Online';
      if (dot) dot.className = 'w-2 h-2 rounded-full bg-emerald-500 animate-pulse';
    } else {
      throw new Error('Health check failed');
    }
  } catch (err) {
    if (status) status.textContent = 'Connecting...';
    if (dot) dot.className = 'w-2 h-2 rounded-full bg-amber-500';
  }

  // Also query document counts
  try {
    const docRes = await fetch(apiEndpoint('/api/v1/documents'));
    if (docRes.ok) {
      const docData = await docRes.json();
      state.documents = docData.documents || [];
    }
  } catch (e) {
    console.debug('Failed to load initial document count', e);
  }
}

function setupKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // Command/Ctrl + K to focus search
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      const topSearch = document.getElementById('top-quick-search');
      if (topSearch) {
        topSearch.focus();
        topSearch.select();
      }
    }
  });
}

// ==========================================
// ==========================================
// 2. NAVIGATION & VIEW SWITCHING (DESKTOP + MOBILE)
// ==========================================
function toggleMobileSidebar() {
  const sidebar = document.getElementById('app-sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (!sidebar) return;
  const isClosed = sidebar.classList.contains('-translate-x-full');
  if (isClosed) {
    sidebar.classList.remove('-translate-x-full');
    if (backdrop) backdrop.classList.remove('hidden');
    closeConversationsDrawer();
    closeCitationDrawer();
  } else {
    sidebar.classList.add('-translate-x-full');
    if (backdrop) backdrop.classList.add('hidden');
  }
}

function closeMobileSidebar() {
  const sidebar = document.getElementById('app-sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (sidebar) sidebar.classList.add('-translate-x-full');
  if (backdrop) backdrop.classList.add('hidden');
}

function switchView(viewName) {
  state.activeView = viewName;
  closeMobileSidebar();

  const contentScrollArea = document.getElementById('content-scroll-area');
  const viewChat = document.getElementById('view-chat');

  if (viewName === 'chat') {
    if (contentScrollArea) contentScrollArea.classList.add('hidden');
    if (viewChat) viewChat.classList.remove('hidden');
  } else {
    if (viewChat) viewChat.classList.add('hidden');
    if (contentScrollArea) contentScrollArea.classList.remove('hidden');

    const views = ['home', 'cases', 'library', 'calculators'];
    views.forEach(v => {
      const el = document.getElementById(`view-${v}`);
      if (el) {
        if (v === viewName) {
          el.classList.remove('hidden');
        } else {
          el.classList.add('hidden');
        }
      }
    });
  }

  // Desktop Sidebar Nav buttons
  const navBtns = {
    home: document.getElementById('nav-home'),
    chat: document.getElementById('nav-chat'),
    library: document.getElementById('nav-library'),
    calculators: document.getElementById('nav-calculators'),
    cases: document.getElementById('nav-cases'),
  };

  const activeClasses = ['bg-white', 'shadow-sm', 'border', 'border-subtleborder', 'text-darktext'];
  const inactiveClasses = ['text-neutral-600', 'hover:text-darktext', 'hover:bg-neutral-100/60'];

  Object.entries(navBtns).forEach(([key, btn]) => {
    if (!btn) return;
    if (key === viewName) {
      btn.classList.add(...activeClasses);
      btn.classList.remove(...inactiveClasses);
    } else {
      btn.classList.remove(...activeClasses);
      btn.classList.add(...inactiveClasses);
    }
  });

  // Mobile Header Title Sync
  const mobileTitles = {
    home: 'Perfusion AI',
    chat: 'Ask Perfusion AI',
    library: 'Knowledge Library',
    calculators: 'Calculators',
    cases: 'Exam MCQs'
  };
  const mobileTitleEl = document.getElementById('mobile-header-title');
  if (mobileTitleEl && mobileTitles[viewName]) {
    mobileTitleEl.textContent = mobileTitles[viewName];
  }

  // Mobile Bottom Navigation Dock Sync
  const bnavBtns = {
    home: document.getElementById('bnav-home'),
    chat: document.getElementById('bnav-chat'),
    library: document.getElementById('bnav-library'),
    calculators: document.getElementById('bnav-calculators'),
    cases: document.getElementById('bnav-cases')
  };
  Object.entries(bnavBtns).forEach(([key, btn]) => {
    if (!btn) return;
    if (key === viewName) {
      btn.className = 'flex flex-col items-center justify-center py-1 px-2 rounded-xl transition text-neutral-900 font-semibold cursor-pointer active:scale-95';
    } else {
      btn.className = 'flex flex-col items-center justify-center py-1 px-2 rounded-xl transition text-neutral-400 hover:text-neutral-700 font-normal cursor-pointer active:scale-95';
    }
  });

  if (viewName === 'chat') {
    const chatInput = document.getElementById('chat-input');
    if (chatInput) setTimeout(() => chatInput.focus(), 150);
    scrollChatToBottom();
  } else if (viewName === 'library') {
    loadDocuments();
    if (contentScrollArea) contentScrollArea.scrollTo({ top: 0, behavior: 'smooth' });
  } else if (viewName === 'calculators') {
    calculateBSA();
    calculateFlowRate();
    if (contentScrollArea) contentScrollArea.scrollTo({ top: 0, behavior: 'smooth' });
  } else {
    if (contentScrollArea) contentScrollArea.scrollTo({ top: 0, behavior: 'smooth' });
  }

  if (window.lucide) lucide.createIcons();
}

// ==========================================
// 3. DEPTH TOGGLE
// ==========================================
function setDepth(depth) {
  state.selectedDepth = depth;
  const depths = ['overview', 'detailed', 'student'];
  depths.forEach(d => {
    const btn = document.getElementById(`depth-${d}`);
    if (btn) {
      if (d === depth) {
        btn.className = 'px-2.5 py-1 rounded-md bg-sand font-semibold text-neutral-900 shadow-sm transition';
      } else {
        btn.className = 'px-2.5 py-1 rounded-md text-neutral-600 hover:text-darktext transition';
      }
    }
  });
}

// ==========================================
// 4. MAIN QUERY EXECUTION (PERFUSION AI)
// ==========================================
function setQueryAndExecute(text, docId = null, docName = null) {
  if (docId) {
    state.activeDocId = docId;
    state.activeDocName = docName;
  }
  switchView('chat');
  setTimeout(() => {
    sendSuggestedMessage(text);
  }, 50);
}

function setQueryAndFocus(text) {
  switchView('chat');
  setTimeout(() => {
    const input = document.getElementById('chat-input');
    if (input) {
      input.value = text;
      input.focus();
    }
  }, 50);
}

function handleTopSearch(event) {
  if (event.key === 'Enter') {
    event.preventDefault();
    const query = event.target.value.trim();
    if (!query) return;
    setQueryAndExecute(query);
  }
}

async function executeQuery() {
  const input = document.getElementById('main-query-input') || document.getElementById('chat-input');
  const query = input ? input.value.trim() : '';
  if (!query) return;
  setQueryAndExecute(query);
}


// ==========================================
// 4B. CONVERSATIONAL CHATROOM ENGINE (MULTI-TURN)
// ==========================================
function setChatDepth(depth) {
  state.chatDepth = depth;
  const depths = ['overview', 'detailed', 'student'];
  depths.forEach(d => {
    const btn = document.getElementById(`chat-depth-${d}`);
    if (btn) {
      if (d === depth) {
        btn.className = 'px-2 py-0.5 rounded-md bg-sand font-semibold text-neutral-900 shadow-sm transition text-[11px]';
      } else {
        btn.className = 'px-2 py-0.5 rounded-md text-neutral-600 hover:text-darktext transition text-[11px]';
      }
    }
  });
}

function scrollChatToBottom() {
  const container = document.getElementById('chat-messages');
  if (container) {
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
  }
}

function handleChatKeyDown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendChatMessage();
  }
}

function sendSuggestedMessage(text) {
  const input = document.getElementById('chat-input');
  if (input) input.value = text;
  sendChatMessage();
}

function escapeHtml(text) {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}

async function sendChatMessage() {
  if (state.isChatSending) return;

  const input = document.getElementById('chat-input');
  const query = input ? input.value.trim() : '';
  if (!query) return;

  const chatMessages = document.getElementById('chat-messages');
  if (!chatMessages) return;

  state.isChatSending = true;
  input.value = '';
  input.style.height = 'auto';

  // 1. Append User Message Bubble
  const userMsgEl = document.createElement('div');
  userMsgEl.className = 'flex justify-end';
  userMsgEl.innerHTML = `
    <div class="bg-[#18181B] text-white rounded-2xl rounded-tr-sm px-4 py-3 text-xs max-w-xl leading-relaxed shadow-xs space-y-1">
      <div class="flex items-center justify-between text-[10px] text-neutral-400 font-mono-code mb-1">
        <span>You</span>
        <span>${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      </div>
      <p class="whitespace-pre-wrap">${escapeHtml(query)}</p>
    </div>
  `;
  chatMessages.appendChild(userMsgEl);

  // 2. Append Typing Indicator Bubble
  const typingIndicator = document.createElement('div');
  typingIndicator.id = 'chat-typing-indicator';
  typingIndicator.className = 'flex items-start space-x-3 max-w-2xl';
  typingIndicator.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-[#18181B] text-amber-300 flex items-center justify-center flex-shrink-0 mt-0.5 shadow-xs">
      <i data-lucide="activity" class="w-4 h-4"></i>
    </div>
    <div class="bg-white border border-subtleborder rounded-2xl rounded-tl-sm px-4 py-3 shadow-xs flex items-center space-x-2 text-xs text-neutral-600">
      <span class="inline-block w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
      <span class="font-mono-code text-[11px]">Consulting clinical literature & formulating evidence-based reply...</span>
    </div>
  `;
  chatMessages.appendChild(typingIndicator);
  scrollChatToBottom();
  if (window.lucide) lucide.createIcons();

  // 3. Format prompt with depth context
  let formattedQuery = query;
  const isSimplificationRequest = /\b(easier|simpler|simplify|simple|beginner|plain english)\b/i.test(query);
  const hasExamMarks = /(?:\b|\()(\d{1,2})\s*(?:marks?|mark|[Mm])\b(?:\))?/i.test(query);
  const isLongOrMultiPart = query.length > 180 || query.split(/\s+/).length >= 25 || query.includes('\n');

  if (isSimplificationRequest) {
    formattedQuery += "\n\n[Instruction: Explain the established concepts from the previous turn in very simple, easy-to-understand terms with clear bullet points. Avoid complex jargon and keep it intuitive for a beginner student.]";
  } else if (hasExamMarks) {
    formattedQuery += "\n\n[Instruction: Format as an authentic university examination answer calibrated for the specified marks (200 handwritten words/page standard). Adhere to the required structure and word count.]";
  } else if (isLongOrMultiPart) {
    formattedQuery += "\n\n[Instruction: Provide a comprehensive, in-depth, and well-structured answer addressing all components and sub-questions of the prompt in full detail based strictly on the clinical text.]";
  } else if (state.chatDepth === 'student') {
    formattedQuery += "\n\n[Instruction: Provide a structured educational breakdown with key definitions, formulas, and clinical pearls strictly derived from the text.]";
  } else if (state.chatDepth === 'overview') {
    formattedQuery += "\n\n[Instruction: Provide a high-yield bullet-point summary strictly derived from the text without any filler.]";
  } else {
    formattedQuery += "\n\n[Instruction: Provide an authentic, evidence-grounded answer covering all relevant clinical and technical details strictly derived from the text.]";
  }

  try {
    const payloadHistory = state.chatHistory.map(m => ({
      role: m.role,
      content: m.content
    }));

    const payload = {
      question: formattedQuery,
      top_k: isLongOrMultiPart ? 8 : 5,
      conversation_history: payloadHistory
    };
    if (state.activeDocId) {
      payload.document_ids = [state.activeDocId];
    }
    if (state.currentConversationId) {
      payload.conversation_id = state.currentConversationId;
    }

    let streamedAnswer = "";
    let streamSucceeded = false;

    // Create assistant message bubble
    const assistantMsgEl = document.createElement('div');
    assistantMsgEl.className = 'flex items-start space-x-3 max-w-3xl';
    assistantMsgEl.innerHTML = `
      <div class="w-8 h-8 rounded-lg bg-[#18181B] text-amber-300 flex items-center justify-center flex-shrink-0 mt-0.5 shadow-xs">
        <i data-lucide="activity" class="w-4 h-4"></i>
      </div>
      <div class="bg-white border border-subtleborder rounded-2xl rounded-tl-sm p-4 shadow-xs space-y-2 flex-1 text-xs text-neutral-800">
        <div class="flex items-center justify-between border-b border-subtleborder/60 pb-1.5">
          <div class="flex items-center space-x-2">
            <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
            <span class="font-mono-code font-bold text-neutral-900 text-[11px]">Perfusion AI</span>
            <span class="exam-marks-badge"></span>
          </div>
        </div>
        <div class="prose-clinical text-xs leading-relaxed text-neutral-800">
          <span class="inline-block w-2 h-3.5 bg-amber-500 animate-pulse"></span>
        </div>
      </div>
    `;

    const authHeaders = { 'Content-Type': 'application/json' };
    if (state.user && state.user.token) {
      authHeaders['Authorization'] = `Bearer ${state.user.token}`;
    }

    // Try streaming endpoint first for instant response
    try {
      const streamRes = await fetch(apiEndpoint('/api/v1/chat/stream'), {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify(payload)
      });

      if (streamRes.ok && streamRes.body) {
        typingIndicator.remove();
        chatMessages.appendChild(assistantMsgEl);
        if (window.lucide) lucide.createIcons();
        scrollChatToBottom();

        const proseDiv = assistantMsgEl.querySelector('.prose-clinical');
        const badgeEl = assistantMsgEl.querySelector('.exam-marks-badge');

        const reader = streamRes.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n\n');
          buffer = lines.pop(); // Keep unfinished tail

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith('data:')) continue;
            try {
              const eventData = JSON.parse(trimmed.slice(5).trim());
              if (eventData.type === 'meta') {
                if (eventData.conversation_id) {
                  state.currentConversationId = eventData.conversation_id;
                  localStorage.setItem('perfusion_current_conv_id', eventData.conversation_id);
                }
                if (eventData.exam_marks && badgeEl) {
                  badgeEl.className = 'text-[9px] font-mono-code bg-amber-100 text-amber-900 font-semibold px-2 py-0.5 rounded-full border border-amber-300 shadow-xs';
                  badgeEl.textContent = `${eventData.exam_marks} MARKS`;
                }
              } else if (eventData.type === 'token') {
                streamedAnswer += eventData.content;
                proseDiv.innerHTML = window.marked ? marked.parse(streamedAnswer) : streamedAnswer;
                scrollChatToBottom();
              } else if (eventData.type === 'done') {
                streamedAnswer = eventData.answer || streamedAnswer;
                proseDiv.innerHTML = window.marked ? marked.parse(streamedAnswer) : streamedAnswer;
                scrollChatToBottom();
              }
            } catch (e) {
              // Ignore single malformed chunk
            }
          }
        }

        if (streamedAnswer) {
          state.chatHistory.push({ role: 'user', content: query });
          state.chatHistory.push({ role: 'assistant', content: streamedAnswer });
          streamSucceeded = true;
        }
      }
    } catch (streamErr) {
      console.warn('Streaming encountered issue, falling back to /ask:', streamErr);
    }

    if (!streamSucceeded) {
      // Fallback to standard non-streaming /ask endpoint
      const response = await fetch(apiEndpoint('/api/v1/chat/ask'), {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || err.message || 'Request could not be completed');
      }

      const data = await response.json();
      if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
        localStorage.setItem('perfusion_current_conv_id', data.conversation_id);
      }
      typingIndicator.remove();
      assistantMsgEl.innerHTML = `
        <div class="w-8 h-8 rounded-lg bg-[#18181B] text-amber-300 flex items-center justify-center flex-shrink-0 mt-0.5 shadow-xs">
          <i data-lucide="activity" class="w-4 h-4"></i>
        </div>
        <div class="bg-white border border-subtleborder rounded-2xl rounded-tl-sm p-4 shadow-xs space-y-2 flex-1 text-xs text-neutral-800">
          <div class="flex items-center justify-between border-b border-subtleborder/60 pb-1.5">
            <div class="flex items-center space-x-2">
              <span class="w-2 h-2 rounded-full ${data.grounded ? 'bg-emerald-500' : 'bg-amber-500'}"></span>
              <span class="font-mono-code font-bold text-neutral-900 text-[11px]">Perfusion AI</span>
              ${data.exam_marks ? `<span class="text-[9px] font-mono-code bg-amber-100 text-amber-900 font-semibold px-2 py-0.5 rounded-full border border-amber-300 shadow-xs">${data.exam_marks} MARKS</span>` : ''}
            </div>
          </div>
          <div class="prose-clinical text-xs leading-relaxed text-neutral-800">
            ${window.marked ? marked.parse(data.answer) : data.answer}
          </div>
        </div>
      `;
      chatMessages.appendChild(assistantMsgEl);
      if (window.lucide) lucide.createIcons();
      scrollChatToBottom();

      state.chatHistory.push({ role: 'user', content: query });
      state.chatHistory.push({ role: 'assistant', content: data.answer });
    }

  } catch (err) {
    typingIndicator.remove();
    const errorBubble = document.createElement('div');
    errorBubble.className = 'flex items-start space-x-3 max-w-2xl';
    errorBubble.innerHTML = `
      <div class="w-8 h-8 rounded-lg bg-rose-600 text-white flex items-center justify-center flex-shrink-0 mt-0.5 shadow-xs">
        <i data-lucide="alert-circle" class="w-4 h-4"></i>
      </div>
      <div class="bg-rose-50 border border-rose-200 text-rose-900 rounded-2xl rounded-tl-sm p-3.5 shadow-xs text-xs space-y-1">
        <p class="font-semibold">Unable to generate reply</p>
        <p class="font-mono-code text-[11px]">${err.message}</p>
      </div>
    `;
    chatMessages.appendChild(errorBubble);
  } finally {
    state.isChatSending = false;
    scrollChatToBottom();
    if (window.lucide) lucide.createIcons();
  }
}

async function clearChat(confirmFirst = true) {
  if (confirmFirst && state.chatHistory.length > 0) {
    const confirmed = await showConfirmDialog({
      title: 'Start New Conversation',
      message: 'Start a fresh conversation? Your past messages remain saved in Past Chats.',
      confirmText: 'Start New',
      danger: false
    });
    if (!confirmed) return;
  }
  state.chatHistory = [];
  state.activeDocId = null;
  state.activeDocName = null;
  state.currentConversationId = null;
  localStorage.removeItem('perfusion_current_conv_id');

  const sub = document.getElementById('chat-session-subtitle');
  if (sub) {
    sub.textContent = 'Evidence Grounded • 799-Page Textbook Active';
    sub.className = 'text-[11px] text-neutral-500 font-mono-code mt-0.5 truncate max-w-md';
  }

  const chatMessages = document.getElementById('chat-messages');
  if (chatMessages) {
    chatMessages.innerHTML = `
      <div class="flex items-start space-x-3 max-w-3xl">
        <div class="w-8 h-8 rounded-lg bg-[#18181B] text-amber-300 flex items-center justify-center flex-shrink-0 mt-0.5 shadow-xs">
          <i data-lucide="activity" class="w-4 h-4"></i>
        </div>
        <div class="bg-white border border-subtleborder rounded-2xl rounded-tl-sm p-5 shadow-xs space-y-3 flex-1 text-xs text-neutral-800">
          <div class="flex items-center justify-between border-b border-subtleborder/60 pb-2">
            <span class="font-mono-code font-bold text-neutral-900 text-[11px]">Perfusion AI Assistant</span>
          </div>
          <p class="leading-relaxed">
            Welcome to the clinical decision support chatroom. I am grounded directly in your uploaded Perfusion Technology curriculum and textbooks. You can ask detailed clinical questions, request procedure walk-throughs, or explore complex hemodynamics with full multi-turn follow-ups.
          </p>
          <div class="space-y-1.5 pt-1">
            <p class="text-[10px] font-mono-code uppercase tracking-wider text-neutral-400 font-semibold">Suggested Starters:</p>
            <div class="flex flex-wrap gap-1.5">
              <button onclick="sendSuggestedMessage('Walk me through the CPB circuit de-airing procedure and pre-bypass safety checks.')" class="bg-[#FAF8F5] hover:bg-[#F4E8D6] text-neutral-700 border border-subtleborder rounded-lg px-2.5 py-1 text-[11px] transition text-left">
                • Pre-bypass safety checks & de-airing
              </button>
              <button onclick="sendSuggestedMessage('What are the physiological causes and management of acute high arterial line pressure during CPB?')" class="bg-[#FAF8F5] hover:bg-[#F4E8D6] text-neutral-700 border border-subtleborder rounded-lg px-2.5 py-1 text-[11px] transition text-left">
                • Acute high arterial line pressure causes
              </button>
              <button onclick="sendSuggestedMessage('Compare alpha-stat vs pH-stat arterial blood gas management during deep hypothermic circulatory arrest.')" class="bg-[#FAF8F5] hover:bg-[#F4E8D6] text-neutral-700 border border-subtleborder rounded-lg px-2.5 py-1 text-[11px] transition text-left">
                • Alpha-stat vs pH-stat blood gas strategy
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
    if (window.lucide) lucide.createIcons();
  }
  loadConversationsList();
}

// ==========================================
// 5. CITATION INSPECTOR DRAWER
// ==========================================
function openCitationDrawer(index) {
  const citation = state.currentCitations[index];
  if (!citation) return;

  const drawer = document.getElementById('citation-drawer');
  const sourceEl = document.getElementById('drawer-source');
  const pageEl = document.getElementById('drawer-page');
  const excerptEl = document.getElementById('drawer-excerpt');

  if (sourceEl) sourceEl.textContent = citation.source;
  if (pageEl) pageEl.textContent = `Original PDF Page ${citation.page}`;
  if (excerptEl) excerptEl.textContent = `"${citation.excerpt}"`;

  closeMobileSidebar();
  closeConversationsDrawer();

  const backdrop = document.getElementById('conversations-backdrop');
  if (backdrop) backdrop.classList.remove('hidden');

  if (drawer) {
    drawer.classList.remove('translate-x-full');
  }
  if (window.lucide) lucide.createIcons();
}

function closeCitationDrawer() {
  const drawer = document.getElementById('citation-drawer');
  if (drawer) {
    drawer.classList.add('translate-x-full');
  }
  const convDrawer = document.getElementById('conversations-drawer');
  const isConvClosed = !convDrawer || convDrawer.classList.contains('translate-x-full');
  if (isConvClosed) {
    const backdrop = document.getElementById('conversations-backdrop');
    if (backdrop) backdrop.classList.add('hidden');
  }
}

// ==========================================
// 6. MULTIPLE-CHOICE QUESTIONS (EXAM ENGINE)
// ==========================================
async function generateMCQs() {
  const topicInput = document.getElementById('mcq-topic');
  const countSelect = document.getElementById('mcq-count');
  const container = document.getElementById('mcq-container');

  const topic = topicInput ? topicInput.value.trim() : 'Cardiopulmonary bypass physiology';
  const num_questions = countSelect ? parseInt(countSelect.value, 10) : 3;

  if (!topic) return;

  container.innerHTML = `
    <div class="bg-white border border-subtleborder rounded-xl p-8 text-center space-y-3 shadow-sm">
      <div class="inline-block animate-spin w-7 h-7 border-2 border-darktext border-t-transparent rounded-full"></div>
      <p class="text-sm font-medium text-neutral-800">Synthesizing ${num_questions} evidence-based MCQs on "${topic}"...</p>
      <p class="text-xs text-neutral-400 font-mono-code">Grounding questions in indexed textbook chapters</p>
    </div>
  `;

  try {
    const res = await fetch(apiEndpoint('/api/v1/study/mcq'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, num_questions })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error: ${res.status}`);
    }

    const data = await res.json();
    if (!data.questions || data.questions.length === 0) {
      container.innerHTML = `
        <div class="bg-amber-50 border border-amber-200 text-amber-900 p-5 rounded-xl text-xs">
          <p class="font-semibold">Insufficient Evidence Found</p>
          <p class="mt-1">The knowledge base did not contain enough specific material on "${topic}" to construct reliable questions.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = '';

    data.questions.forEach((q, qIndex) => {
      const card = document.createElement('div');
      card.className = 'bg-white border border-subtleborder rounded-xl p-6 shadow-sm space-y-4';
      
      let optionsHtml = '';
      q.options.forEach(opt => {
        optionsHtml += `
          <button 
            onclick="checkAnswer(this, '${opt.key}', '${q.correct_answer}', 'explanation-${qIndex}')"
            class="mcq-option w-full text-left p-3.5 rounded-lg border border-subtleborder hover:border-neutral-400 bg-neutral-50/50 hover:bg-neutral-100/50 transition flex items-start space-x-3 text-xs"
            data-key="${opt.key}"
          >
            <span class="font-mono-code font-bold w-5 h-5 rounded flex items-center justify-center bg-white border border-neutral-300 text-neutral-700 text-[11px] flex-shrink-0">${opt.key}</span>
            <span class="text-neutral-800 leading-snug pt-0.5">${opt.text}</span>
          </button>
        `;
      });

      card.innerHTML = `
        <div class="flex items-center justify-between border-b border-subtleborder pb-3">
          <span class="text-xs font-mono-code uppercase text-neutral-500 font-semibold">Question ${qIndex + 1} of ${data.questions.length}</span>
          <span class="text-[10px] font-mono-code bg-sandbadge text-neutral-800 px-2 py-0.5 rounded font-semibold">BOARD PREP</span>
        </div>
        
        <p class="text-sm font-semibold text-neutral-900 leading-relaxed">${q.question}</p>
        
        <div class="space-y-2">
          ${optionsHtml}
        </div>

        <div id="explanation-${qIndex}" class="hidden pt-3 border-t border-subtleborder text-xs space-y-2">
          <div class="flex items-center space-x-1.5 font-semibold text-emerald-800">
            <i data-lucide="check-circle" class="w-4 h-4 text-emerald-600"></i>
            <span>Correct Answer: Option ${q.correct_answer}</span>
          </div>
          <p class="text-neutral-700 leading-relaxed bg-[#FBF9F5] p-3 rounded-lg border border-subtleborder">${q.explanation}</p>
        </div>
      `;

      container.appendChild(card);
    });

    if (window.lucide) lucide.createIcons();

  } catch (err) {
    container.innerHTML = `
      <div class="bg-rose-50 border border-rose-200 text-rose-800 p-4 rounded-xl text-xs">
        <p class="font-semibold">Failed to generate MCQs</p>
        <p class="font-mono-code mt-1">${err.message}</p>
      </div>
    `;
  }
}

function checkAnswer(btn, selectedKey, correctKey, explanationId) {
  const parent = btn.parentElement;
  const allButtons = parent.querySelectorAll('.mcq-option');
  
  // Disable further clicks
  allButtons.forEach(b => {
    b.disabled = true;
    b.classList.remove('hover:border-neutral-400', 'hover:bg-neutral-100/50');
    if (b.dataset.key === correctKey) {
      b.classList.add('bg-emerald-50', 'border-emerald-500', 'text-emerald-950');
      b.querySelector('span:first-child').classList.add('bg-emerald-600', 'text-white', 'border-emerald-600');
    }
  });

  if (selectedKey !== correctKey) {
    btn.classList.add('bg-rose-50', 'border-rose-400', 'text-rose-950');
    btn.querySelector('span:first-child').classList.add('bg-rose-600', 'text-white', 'border-rose-600');
  }

  const expEl = document.getElementById(explanationId);
  if (expEl) {
    expEl.classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  }
}

// ==========================================
// 7. KNOWLEDGE LIBRARY TABLE & REBUILD
// ==========================================
async function loadDocuments() {
  const tbody = document.getElementById('documents-table-body');
  if (!tbody) return;

  tbody.innerHTML = `
    <tr>
      <td colspan="5" class="py-6 text-center text-neutral-400">
        <div class="inline-block animate-spin w-5 h-5 border-2 border-darktext border-t-transparent rounded-full mb-2"></div>
        <p>Loading indexed textbooks and documents...</p>
      </td>
    </tr>
  `;

  try {
    const res = await fetch(apiEndpoint('/api/v1/documents'));
    if (!res.ok) throw new Error('Failed to fetch documents');
    const data = await res.json();
    state.documents = data.documents || [];

    if (state.documents.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" class="py-6 text-center text-neutral-400">
            No curriculum reference documents loaded yet.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = '';
    state.documents.forEach(doc => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-neutral-50/70 transition';
      tr.innerHTML = `
        <td class="py-3 px-4 font-medium text-neutral-900 flex items-center space-x-2">
          <i data-lucide="file-text" class="w-4 h-4 text-amber-700 flex-shrink-0"></i>
          <span class="truncate max-w-sm" title="${doc.filename}">${doc.filename}</span>
        </td>
        <td class="py-3 px-4 font-mono-code text-neutral-600">${doc.total_pages || '—'} pages</td>
        <td class="py-3 px-4">
          <span class="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
            <span>Active</span>
          </span>
        </td>
        <td class="py-3 px-4 text-right">
          <button onclick="setQueryAndExecute('Summarize key principles in ' + escapeHtml('${doc.filename}'), '${doc.document_id}', escapeHtml('${doc.filename}'))" class="text-xs font-mono-code text-amber-800 hover:text-amber-900 font-semibold underline underline-offset-2">
            Explore
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    if (window.lucide) lucide.createIcons();

  } catch (err) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" class="py-6 text-center text-rose-600">
          Failed to load documents: ${err.message}
        </td>
      </tr>
    `;
  }
}

async function refreshLibrary() {
  await loadDocuments();
  showToastNotification('Clinical library refreshed', 'success');
}
window.rebuildIndex = refreshLibrary;

// ==========================================
// 9. CLINICAL CALCULATORS (PERFUSION SUITE)
// ==========================================
function calculateBSA() {
  const height = parseFloat(document.getElementById('calc-height')?.value || '175');
  const weight = parseFloat(document.getElementById('calc-weight')?.value || '75');

  if (height > 0 && weight > 0) {
    // Mosteller formula: sqrt((H * W) / 3600)
    const bsa = Math.sqrt((height * weight) / 3600);
    const bsaEl = document.getElementById('calc-bsa-result');
    if (bsaEl) bsaEl.textContent = bsa.toFixed(2) + ' m²';

    // Auto-sync into flow rate BSA input
    const flowBsaInput = document.getElementById('calc-flow-bsa');
    if (flowBsaInput) {
      flowBsaInput.value = bsa.toFixed(2);
      calculateFlowRate();
    }
  }
}

function calculateFlowRate() {
  const bsa = parseFloat(document.getElementById('calc-flow-bsa')?.value || '1.91');
  const ci = parseFloat(document.getElementById('calc-flow-ci')?.value || '2.4');

  if (bsa > 0 && ci > 0) {
    // Flow Rate = BSA * Cardiac Index
    const flowRate = bsa * ci;
    const flowRateMl = flowRate * 1000;

    const flowEl = document.getElementById('calc-flow-rate-result');
    const flowMlEl = document.getElementById('calc-flow-rate-ml');
    if (flowEl) flowEl.textContent = flowRate.toFixed(2) + ' L/min';
    if (flowMlEl) flowMlEl.textContent = Math.round(flowRateMl).toLocaleString() + ' mL/min';
  }
}

// Backward compatibility alias
function calculateBSAAndFlow() {
  calculateBSA();
  calculateFlowRate();
}

// ==========================================
// 10. GOOGLE AUTHENTICATION & USER PROFILE
// ==========================================

async function initAuth() {
  if (!document.getElementById('auth-container')) return;
  renderAuthUI();
  await fetchAuthConfig();

  // Validate or refresh session from backend if token exists
  if (state.user && state.user.token) {
    try {
      const meRes = await fetch(apiEndpoint('/api/v1/auth/me'), {
        headers: { 'Authorization': `Bearer ${state.user.token}` }
      });
      if (meRes.ok) {
        state.user = await meRes.json();
        localStorage.setItem('perfusion_user', JSON.stringify(state.user));
        renderAuthUI();
      } else if (meRes.status === 401) {
        // Token expired or invalid
        localStorage.removeItem('perfusion_user');
        state.user = null;
        renderAuthUI();
      }
    } catch (e) {
      console.debug('Session check note', e);
    }
  }

  // Close user dropdown when clicking outside
  document.addEventListener('click', (e) => {
    const authContainer = document.getElementById('auth-container');
    const dropdown = document.getElementById('user-dropdown-menu');
    if (dropdown && !dropdown.classList.contains('hidden')) {
      if (authContainer && !authContainer.contains(e.target)) {
        dropdown.classList.add('hidden');
      }
    }
  });
}

async function fetchAuthConfig() {
  try {
    const res = await fetch(apiEndpoint('/api/v1/auth/config'));
    if (res.ok) {
      state.authConfig = await res.json();
      updateAuthModalConfigUI(false);
      initializeGoogleGSI();
      initSupabaseClient();
    }
  } catch (err) {
    console.debug('Failed to fetch auth configuration', err);
  }
}

function initializeGoogleGSI() {
  if (!state.authConfig.enabled || !state.authConfig.google_client_id) {
    console.log('Institutional authentication not configured. Guest clinician access active.');
    return;
  }

  // Poll for Google Identity Services script availability
  const checkGsi = setInterval(() => {
    if (window.google && google.accounts && google.accounts.id) {
      clearInterval(checkGsi);
      try {
        google.accounts.id.initialize({
          client_id: state.authConfig.google_client_id,
          callback: handleGoogleCredentialResponse,
          auto_select: false,
          cancel_on_tap_outside: true,
        });

        // Render official Google button inside modal target if element exists
        const modalTarget = document.getElementById('g_id_signin_modal_target');
        if (modalTarget) {
          google.accounts.id.renderButton(modalTarget, {
            theme: 'outline',
            size: 'large',
            type: 'standard',
            text: 'signin_with',
            shape: 'pill',
            logo_alignment: 'left',
            width: 280
          });
        }
        console.log('Google Identity Services initialized successfully.');
      } catch (e) {
        console.warn('Google GSI initialization error:', e);
      }
    }
  }, 300);

  // Stop polling after 10 seconds
  setTimeout(() => clearInterval(checkGsi), 10000);
}

function initSupabaseClient() {
  if (!state.authConfig || !state.authConfig.supabase_url || !state.authConfig.supabase_anon_key) {
    return;
  }
  if (window.supabase && typeof window.supabase.createClient === 'function') {
    try {
      window.supabaseClient = window.supabase.createClient(
        state.authConfig.supabase_url,
        state.authConfig.supabase_anon_key
      );
      console.log('Supabase client initialized successfully.');

      // Check for active session
      window.supabaseClient.auth.getSession().then(({ data }) => {
        const session = data?.session;
        if (session && session.access_token && (!state.user || !state.user.authenticated)) {
          syncSupabaseSession(session.access_token);
        }
      }).catch(err => console.debug('Supabase getSession error:', err));

      // Listen to auth state changes
      window.supabaseClient.auth.onAuthStateChange(async (event, session) => {
        if (event === 'SIGNED_IN' && session && session.access_token) {
          await syncSupabaseSession(session.access_token);
        } else if (event === 'SIGNED_OUT') {
          if (state.user) {
            state.user = null;
            localStorage.removeItem('perfusion_user');
            renderAuthUI();
          }
        }
      });
    } catch (e) {
      console.warn('Supabase client initialization note:', e);
    }
  }
}

async function syncSupabaseSession(accessToken) {
  try {
    const res = await fetch(apiEndpoint('/api/v1/auth/session'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ access_token: accessToken })
    });
    if (res.ok) {
      const user = await res.json();
      state.user = user;
      localStorage.setItem('perfusion_user', JSON.stringify(user));
      renderAuthUI();
      bypassLoginToGuest();
      showAuthNotification(`Signed in as ${user.name}`);
      // Clean up URL hash if returned from OAuth redirect
      if (window.location.hash && (window.location.hash.includes('access_token') || window.location.hash.includes('type='))) {
        window.history.replaceState(null, '', window.location.pathname);
      }
      return user;
    }
  } catch (err) {
    console.error('Supabase session sync error:', err);
  }
  return null;
}

function updateAuthModalConfigUI(populateInputs = false) {
  const badge = document.getElementById('oauth-status-badge');
  const desc = document.getElementById('oauth-status-desc');
  const supaUrlInput = document.getElementById('input-supabase-url');
  const supaKeyInput = document.getElementById('input-supabase-key');

  if (populateInputs) {
    if (supaUrlInput && state.authConfig.supabase_url) {
      supaUrlInput.value = state.authConfig.supabase_url;
    }
    if (supaKeyInput && state.authConfig.supabase_anon_key) {
      supaKeyInput.value = state.authConfig.supabase_anon_key;
    }
  }

  if (state.authConfig.supabase_enabled) {
    if (badge) {
      badge.textContent = 'Supabase Active';
      badge.className = 'font-mono-code text-[10px] px-2 py-0.5 rounded-full font-semibold bg-emerald-100 text-emerald-800';
    }
    if (desc) {
      const shortUrl = state.authConfig.supabase_url.replace(/^https?:\/\//, '');
      desc.innerHTML = `Supabase authentication active (<code class="bg-white px-1 py-0.5 rounded text-neutral-800 font-mono-code border border-subtleborder">${escapeHtml(shortUrl)}</code>). Institutional accounts, session tokens, and password recovery are verified via Supabase.`;
    }
  } else {
    if (badge) {
      badge.textContent = 'Setup Required';
      badge.className = 'font-mono-code text-[10px] px-2 py-0.5 rounded-full font-semibold bg-amber-100 text-amber-800';
    }
    if (desc) {
      desc.innerHTML = `Enter your Supabase Project URL and Anon Key below or in <code class="bg-white px-1 py-0.5 rounded border border-subtleborder">.env</code> to activate institutional cloud authentication.`;
    }
  }
}

function toggleSetupGuide() {
  const guide = document.getElementById('google-setup-guide');
  if (guide) {
    guide.classList.toggle('hidden');
  }
}

async function saveSupabaseCredentials() {
  const urlInput = document.getElementById('input-supabase-url');
  const keyInput = document.getElementById('input-supabase-key');
  const saveBtn = document.getElementById('btn-save-google-creds');

  const supabaseUrl = urlInput ? urlInput.value.trim() : '';
  const supabaseKey = keyInput ? keyInput.value.trim() : '';

  if (!supabaseUrl || !supabaseKey) {
    showToastNotification('Please enter both Supabase Project URL and Anon Key.', 'error');
    return;
  }

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i><span>Connecting...</span>';
    if (window.lucide) lucide.createIcons();
  }

  try {
    const res = await fetch(apiEndpoint('/api/v1/auth/configure'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        supabase_url: supabaseUrl,
        supabase_anon_key: supabaseKey
      })
    });

    if (res.ok) {
      state.authConfig = await res.json();
      updateAuthModalConfigUI();
      initSupabaseClient();
      showAuthNotification('Supabase Authentication configured and activated!');
      closeGoogleAuthModal();
    } else {
      const err = await res.json().catch(() => ({}));
      showToastNotification(`Activation failed: ${err.detail || 'Could not save credentials'}`, 'error');
    }
  } catch (err) {
    showToastNotification('Network error saving Supabase credentials', 'error');
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.innerHTML = '<i data-lucide="check" class="w-3.5 h-3.5"></i><span>Save & Activate Supabase</span>';
      if (window.lucide) lucide.createIcons();
    }
  }
}

async function initiateGoogleSignIn() {
  const btn = document.getElementById('btn-google-signin') || document.querySelector('button[onclick="initiateGoogleSignIn()"]');
  const originalHtml = btn ? btn.innerHTML : '';

  // 1. If Supabase is active, initiate Supabase Google OAuth
  if (window.supabaseClient && state.authConfig?.supabase_enabled) {
    try {
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="inline-block animate-spin w-3.5 h-3.5 border-2 border-stone-800 border-t-transparent rounded-full mr-2"></span><span>Redirecting to Google...</span>';
      }

      const { data, error } = await window.supabaseClient.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: window.location.origin
        }
      });

      if (error) {
        console.warn('Supabase Google OAuth error, falling back to direct OAuth:', error);
        // If Supabase Google provider is not yet enabled in Supabase dashboard, fall back seamlessly to backend Google OAuth
        if (state.authConfig?.google_client_id) {
          window.location.href = apiEndpoint('/api/v1/auth/google/login');
          return;
        }
        showToastNotification(error.message || 'Google sign-in error with Supabase.', 'error');
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = originalHtml;
        }
        return;
      }
      return;
    } catch (e) {
      console.warn('Supabase OAuth exception, falling back to direct OAuth:', e);
      if (state.authConfig?.google_client_id) {
        window.location.href = apiEndpoint('/api/v1/auth/google/login');
        return;
      }
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
      }
    }
  }

  // 2. Direct Google OAuth (if client ID is configured)
  if (state.authConfig?.google_client_id) {
    window.location.href = apiEndpoint('/api/v1/auth/google/login');
    return;
  }

  showToastNotification('Please configure Google OAuth credentials in Supabase or .env', 'info');
}

async function handleGoogleCredentialResponse(response) {
  if (!response || !response.credential) {
    console.error('Invalid credential received from Google');
    return;
  }

  try {
    const res = await fetch(apiEndpoint('/api/v1/auth/google'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential: response.credential })
    });

    if (res.ok) {
      const user = await res.json();
      state.user = user;
      localStorage.setItem('perfusion_user', JSON.stringify(user));
      renderAuthUI();
      closeGoogleAuthModal();
      bypassLoginToGuest();
      showAuthNotification(`Signed in as ${user.name}`);
    } else {
      const err = await res.json().catch(() => ({}));
      showToastNotification(`Sign-in failed: ${err.detail || err.message || 'Invalid Token'}`, 'error');
    }
  } catch (err) {
    console.error('Authentication network error:', err);
    showToastNotification('Failed to connect to authentication backend.', 'error');
  }
}

// ==========================================
// DEDICATED FULL-VIEWPORT LOGIN SCREEN LOGIC
// ==========================================
function openLoginScreen() {
  const loginView = document.getElementById('view-login');
  const appShell = document.getElementById('app-shell');
  if (loginView) loginView.classList.remove('hidden');
  if (appShell) appShell.classList.add('hidden');
  if (window.lucide) lucide.createIcons();
}

function bypassLoginToGuest() {
  const loginView = document.getElementById('view-login');
  const appShell = document.getElementById('app-shell');
  if (loginView) loginView.classList.add('hidden');
  if (appShell) appShell.classList.remove('hidden');
  if (window.lucide) lucide.createIcons();
}

function toggleAuthBox(mode, event) {
  if (event) event.preventDefault();
  const boxLogin = document.getElementById('auth-box-login');
  const boxRegister = document.getElementById('auth-box-register');
  if (mode === 'register') {
    if (boxLogin) boxLogin.classList.add('hidden');
    if (boxRegister) boxRegister.classList.remove('hidden');
  } else {
    if (boxRegister) boxRegister.classList.add('hidden');
    if (boxLogin) boxLogin.classList.remove('hidden');
  }
  if (window.lucide) lucide.createIcons();
}

function togglePasswordVisibility(inputId, iconId) {
  const input = document.getElementById(inputId);
  const icon = document.getElementById(iconId);
  if (!input || !icon) return;

  if (input.type === 'password') {
    input.type = 'text';
    icon.setAttribute('data-lucide', 'eye-off');
  } else {
    input.type = 'password';
    icon.setAttribute('data-lucide', 'eye');
  }
  if (window.lucide) lucide.createIcons();
}

async function handleForgotPassword(event) {
  if (event) event.preventDefault();
  const emailInput = document.getElementById('login-email');
  let email = emailInput ? emailInput.value.trim() : '';

  if (!email) {
    email = prompt('Enter your institutional email address for password recovery:');
    if (!email || !email.trim()) {
      return;
    }
    email = email.trim();
  }

  try {
    const res = await fetch(apiEndpoint('/api/v1/auth/recover-password'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email })
    });

    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      showToastNotification(data.message || `Password recovery instructions sent to ${email}`, 'info');
    } else {
      showToastNotification(data.detail || 'Could not initiate password recovery.', 'error');
    }
  } catch (err) {
    showToastNotification('Network error contacting password recovery service.', 'error');
  }
}

async function handleEmailPasswordLogin(event) {
  if (event) event.preventDefault();
  const emailInput = document.getElementById('login-email');
  const passwordInput = document.getElementById('login-password');
  const rememberInput = document.getElementById('login-remember');
  const submitBtn = document.getElementById('btn-login-submit');

  const email = emailInput ? emailInput.value.trim() : '';
  const password = passwordInput ? passwordInput.value.trim() : '';
  const remember = rememberInput ? rememberInput.checked : true;

  if (!email || !password) {
    showToastNotification('Please enter both your institutional email and password.', 'error');
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="inline-block animate-spin w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full mr-2"></span><span>Signing in...</span>';
  }

  try {
    // 1. If Supabase client is initialized on frontend, authenticate directly
    if (window.supabaseClient && state.authConfig?.supabase_enabled) {
      try {
        const { data, error } = await window.supabaseClient.auth.signInWithPassword({
          email: email,
          password: password
        });

        if (!error && data?.session?.access_token) {
          const user = await syncSupabaseSession(data.session.access_token);
          if (user) return;
        } else if (error) {
          // If Supabase returned an explicit authentication error, show message
          showToastNotification(error.message || 'Supabase authentication failed.', 'error');
          return;
        }
      } catch (clientErr) {
        console.warn('Frontend Supabase sign-in exception, falling back to backend:', clientErr);
      }
    }

    // 2. Authenticate through backend endpoint (proxy to Supabase or DB)
    const res = await fetch(apiEndpoint('/api/v1/auth/login'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, remember_me: remember })
    });

    if (res.ok) {
      const user = await res.json();
      state.user = user;
      localStorage.setItem('perfusion_user', JSON.stringify(user));
      renderAuthUI();
      bypassLoginToGuest();
      showAuthNotification(`Welcome back, ${user.name}`);
    } else {
      const err = await res.json().catch(() => ({}));
      showToastNotification(err.detail || 'Incorrect institutional email or password.', 'error');
    }
  } catch (err) {
    console.error('Email sign-in network error:', err);
    showToastNotification('Network error connecting to login server.', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = '<span>Sign in</span><i data-lucide="arrow-right" class="w-4 h-4"></i>';
      if (window.lucide) lucide.createIcons();
    }
  }
}

async function handleRegister(event) {
  if (event) event.preventDefault();
  const nameInput = document.getElementById('reg-name');
  const emailInput = document.getElementById('reg-email');
  const roleSelect = document.getElementById('reg-role');
  const passwordInput = document.getElementById('reg-password');
  const submitBtn = document.getElementById('btn-reg-submit');

  const name = nameInput ? nameInput.value.trim() : '';
  const email = emailInput ? emailInput.value.trim() : '';
  const role = roleSelect ? roleSelect.value : 'Clinical Perfusionist';
  const password = passwordInput ? passwordInput.value.trim() : '';

  if (!name || !email || !password) {
    showToastNotification('Please fill in all registration fields.', 'error');
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="inline-block animate-spin w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full mr-2"></span><span>Creating account...</span>';
  }

  try {
    // 1. If Supabase client is initialized on frontend, register directly
    if (window.supabaseClient && state.authConfig?.supabase_enabled) {
      try {
        const { data, error } = await window.supabaseClient.auth.signUp({
          email: email,
          password: password,
          options: {
            data: { name: name, role: role }
          }
        });

        if (error) {
          showToastNotification(error.message || 'Supabase registration failed.', 'error');
          return;
        }

        if (data?.session?.access_token) {
          const user = await syncSupabaseSession(data.session.access_token);
          if (user) {
            showAuthNotification(`Account created! Welcome, ${user.name}`);
            return;
          }
        } else if (data?.user) {
          showToastNotification('Account created! Please check your institutional email to confirm.', 'info');
          toggleAuthBox('login', event);
          return;
        }
      } catch (clientErr) {
        console.warn('Frontend Supabase sign-up exception, falling back to backend:', clientErr);
      }
    }

    // 2. Register through backend endpoint
    const res = await fetch(apiEndpoint('/api/v1/auth/register'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, role, password })
    });

    if (res.ok) {
      const user = await res.json();
      state.user = user;
      localStorage.setItem('perfusion_user', JSON.stringify(user));
      renderAuthUI();
      bypassLoginToGuest();
      showAuthNotification(`Account created! Welcome, ${user.name}`);
    } else {
      const err = await res.json().catch(() => ({}));
      showToastNotification(err.detail || 'Registration could not be completed.', 'error');
    }
  } catch (err) {
    console.error('Registration network error:', err);
    showToastNotification('Network error connecting to registration server.', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = '<span>Create account</span><i data-lucide="arrow-right" class="w-4 h-4"></i>';
      if (window.lucide) lucide.createIcons();
    }
  }
}

function renderAuthUI() {
  const loggedOutDiv = document.getElementById('auth-logged-out');
  const loggedInDiv = document.getElementById('auth-logged-in');

  if (state.user && state.user.authenticated) {
    // Show logged-in profile
    if (loggedOutDiv) loggedOutDiv.classList.add('hidden');
    if (loggedInDiv) loggedInDiv.classList.remove('hidden');

    const nameEl = document.getElementById('user-display-name');
    const roleEl = document.getElementById('user-display-role');
    const dropdownName = document.getElementById('dropdown-user-name');
    const dropdownEmail = document.getElementById('dropdown-user-email');
    const avatarImg = document.getElementById('user-avatar-img');
    const avatarInitials = document.getElementById('user-avatar-initials');

    if (nameEl) nameEl.textContent = state.user.name || 'Clinician';
    if (roleEl) roleEl.textContent = state.user.role || 'Perfusionist';
    if (dropdownName) dropdownName.textContent = state.user.name || 'Clinician';
    if (dropdownEmail) dropdownEmail.textContent = state.user.email || '';

    if (state.user.picture && avatarImg) {
      avatarImg.src = state.user.picture;
      avatarImg.classList.remove('hidden');
      if (avatarInitials) avatarInitials.classList.add('hidden');
    } else if (avatarInitials) {
      const initial = (state.user.name || 'U').charAt(0).toUpperCase();
      avatarInitials.textContent = initial;
      avatarInitials.classList.remove('hidden');
      if (avatarImg) avatarImg.classList.add('hidden');
    }
  } else {
    // Show Sign-In button
    if (loggedOutDiv) loggedOutDiv.classList.remove('hidden');
    if (loggedInDiv) loggedInDiv.classList.add('hidden');
    const dropdown = document.getElementById('user-dropdown-menu');
    if (dropdown) dropdown.classList.add('hidden');
  }

  if (window.lucide) lucide.createIcons();
}

function toggleUserDropdown() {
  const dropdown = document.getElementById('user-dropdown-menu');
  if (dropdown) {
    dropdown.classList.toggle('hidden');
    if (window.lucide) lucide.createIcons();
  }
}

function openGoogleAuthModal() {
  const modal = document.getElementById('google-auth-modal');
  if (modal) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    updateAuthModalConfigUI(true);
    if (window.lucide) lucide.createIcons();
  }
}

function closeGoogleAuthModal() {
  const modal = document.getElementById('google-auth-modal');
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
}

async function handleSignOut() {
  try {
    const token = state.user?.token;
    if (token) {
      await fetch(apiEndpoint('/api/v1/auth/logout'), {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
    }
    if (window.supabaseClient) {
      try {
        await window.supabaseClient.auth.signOut();
      } catch (e) {
        console.debug('Supabase client signOut note:', e);
      }
    }
  } catch (e) {
    console.debug('Logout request completed', e);
  }

  localStorage.removeItem('perfusion_user');
  state.user = null;
  renderAuthUI();

  if (window.google && google.accounts && google.accounts.id) {
    google.accounts.id.disableAutoSelect();
  }

  showAuthNotification('Signed out of session');
  openLoginScreen();
}

function showToastNotification(text, type = 'info') {
  const note = document.createElement('div');
  const dotColor = type === 'error' ? 'bg-rose-500' : (type === 'success' ? 'bg-emerald-400' : 'bg-amber-400');
  const borderColor = type === 'error' ? 'border-rose-800/80' : 'border-neutral-700';

  note.className = `fixed bottom-5 right-5 bg-darktext text-white text-xs font-medium px-4 py-2.5 rounded-xl shadow-2xl z-[70] flex items-center space-x-2.5 border ${borderColor} animate-in fade-in slide-in-from-bottom-2 duration-200`;
  note.innerHTML = `<span class="w-2 h-2 rounded-full ${dotColor} flex-shrink-0"></span><span class="leading-tight">${escapeHtml(text)}</span>`;
  document.body.appendChild(note);

  setTimeout(() => {
    note.classList.add('opacity-0', 'transition-opacity', 'duration-300');
    setTimeout(() => note.remove(), 350);
  }, 3200);
}

function showAuthNotification(text) {
  showToastNotification(text, 'success');
}

function showConfirmDialog({
  title = 'Delete Conversation',
  message = 'Are you sure you want to delete this chat session? This action cannot be undone.',
  confirmText = 'Delete',
  danger = true,
  loadingText = 'Deleting...',
  onConfirm = null
} = {}) {
  return new Promise((resolve, reject) => {
    let modal = document.getElementById('app-confirm-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'app-confirm-modal';
      modal.className = 'fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/45 backdrop-blur-[2px] transition-opacity duration-200';
      modal.innerHTML = `
        <div class="bg-white rounded-2xl max-w-sm w-full p-6 shadow-2xl border border-subtleborder space-y-4 transform transition-all duration-200">
          <div class="w-11 h-11 rounded-full ${danger ? 'bg-rose-50 text-rose-600' : 'bg-amber-50 text-amber-700'} flex items-center justify-center mx-auto">
            <i data-lucide="${danger ? 'trash-2' : 'help-circle'}" class="w-5 h-5"></i>
          </div>
          <div class="text-center space-y-1.5">
            <h3 class="text-base font-editorial font-bold text-neutral-900" id="confirm-dialog-title">${escapeHtml(title)}</h3>
            <p class="text-xs text-neutral-500 leading-relaxed" id="confirm-dialog-message">${escapeHtml(message)}</p>
          </div>
          <div class="flex items-center space-x-2.5 pt-2">
            <button id="confirm-dialog-cancel" class="flex-1 py-2 px-3 border border-subtleborder hover:bg-neutral-100 rounded-xl text-xs font-semibold text-neutral-700 transition cursor-pointer">
              Cancel
            </button>
            <button id="confirm-dialog-btn" class="flex-1 py-2 px-3 ${danger ? 'bg-rose-600 hover:bg-rose-700' : 'bg-darktext hover:bg-neutral-800'} text-white rounded-xl text-xs font-semibold shadow-xs transition cursor-pointer flex items-center justify-center">
              ${escapeHtml(confirmText)}
            </button>
          </div>
        </div>
      `;
      document.body.appendChild(modal);
    } else {
      const titleEl = document.getElementById('confirm-dialog-title');
      const msgEl = document.getElementById('confirm-dialog-message');
      const btn = document.getElementById('confirm-dialog-btn');
      const btnCancel = document.getElementById('confirm-dialog-cancel');
      if (titleEl) titleEl.textContent = title;
      if (msgEl) msgEl.textContent = message;
      if (btn) {
        btn.disabled = false;
        btn.textContent = confirmText;
        btn.className = `flex-1 py-2 px-3 ${danger ? 'bg-rose-600 hover:bg-rose-700' : 'bg-darktext hover:bg-neutral-800'} text-white rounded-xl text-xs font-semibold shadow-xs transition cursor-pointer flex items-center justify-center`;
      }
      if (btnCancel) {
        btnCancel.disabled = false;
      }
      modal.classList.remove('hidden');
    }

    if (window.lucide) lucide.createIcons();

    const btnCancel = document.getElementById('confirm-dialog-cancel');
    const btnConfirm = document.getElementById('confirm-dialog-btn');

    function onCancelClick() {
      modal.classList.add('hidden');
      cleanup();
      resolve(false);
    }

    async function onConfirmClick() {
      if (typeof onConfirm === 'function') {
        btnConfirm.disabled = true;
        btnCancel.disabled = true;
        btnConfirm.innerHTML = `
          <span class="inline-flex items-center space-x-1.5">
            <span class="inline-block animate-spin w-3 h-3 border-2 border-white border-t-transparent rounded-full"></span>
            <span>${escapeHtml(loadingText)}</span>
          </span>
        `;
        try {
          await onConfirm();
          modal.classList.add('hidden');
          cleanup();
          resolve(true);
        } catch (err) {
          btnConfirm.disabled = false;
          btnCancel.disabled = false;
          btnConfirm.textContent = confirmText;
          modal.classList.add('hidden');
          cleanup();
          reject(err);
        }
      } else {
        modal.classList.add('hidden');
        cleanup();
        resolve(true);
      }
    }

    function cleanup() {
      btnCancel.removeEventListener('click', onCancelClick);
      btnConfirm.removeEventListener('click', onConfirmClick);
    }

    btnCancel.addEventListener('click', onCancelClick);
    btnConfirm.addEventListener('click', onConfirmClick);
  });
}

// ==========================================
// 12. PAST CONVERSATIONS DRAWER
// ==========================================
function toggleConversationsDrawer() {
  closeMobileSidebar();
  closeCitationDrawer();
  const drawer = document.getElementById('conversations-drawer');
  const backdrop = document.getElementById('conversations-backdrop');
  if (!drawer) return;
  const isClosed = drawer.classList.contains('translate-x-full');
  if (isClosed) {
    drawer.classList.remove('translate-x-full');
    if (backdrop) backdrop.classList.remove('hidden');
    loadConversationsList();
  } else {
    drawer.classList.add('translate-x-full');
    if (backdrop) backdrop.classList.add('hidden');
  }
}

function closeConversationsDrawer() {
  const drawer = document.getElementById('conversations-drawer');
  const backdrop = document.getElementById('conversations-backdrop');
  if (drawer) drawer.classList.add('translate-x-full');
  if (backdrop) backdrop.classList.add('hidden');
}

async function loadConversationsList() {
  const container = document.getElementById('conversations-list-container');
  if (!container) return;

  container.innerHTML = `
    <div class="py-6 text-center text-xs text-neutral-400 font-mono-code flex items-center justify-center space-x-2">
      <span class="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
      <span>Loading past conversations...</span>
    </div>
  `;

  try {
    const res = await fetch(apiEndpoint('/api/v1/conversations'));
    const data = await res.json();

    if (data.status === 'database_not_configured') {
      container.innerHTML = `
        <div class="bg-amber-50 border border-amber-200/80 rounded-xl p-4 text-xs text-neutral-700 space-y-2">
          <div class="flex items-center space-x-2 font-semibold text-amber-900 font-mono-code text-[11px]">
            <i data-lucide="cloud-off" class="w-4 h-4 text-amber-700"></i>
            <span>Chat Cloud Sync</span>
          </div>
          <p class="leading-relaxed">
            Cloud session sync is currently offline. Your past conversations will appear here once connected.
          </p>
        </div>
      `;
      if (window.lucide) lucide.createIcons();
      return;
    }

    const convs = data.conversations || [];
    if (convs.length === 0) {
      container.innerHTML = `
        <div class="py-8 text-center text-xs text-neutral-400 font-mono-code space-y-1">
          <i data-lucide="message-square" class="w-6 h-6 mx-auto text-neutral-300"></i>
          <p>No past conversations yet.</p>
          <p class="text-[10px] text-neutral-400">Ask a question to start your first session.</p>
        </div>
      `;
      if (window.lucide) lucide.createIcons();
      return;
    }

    container.innerHTML = '';
    convs.forEach(c => {
      const el = document.createElement('div');
      el.id = `conv-card-${c.id}`;
      const isActive = state.currentConversationId === c.id;
      el.className = `p-3 rounded-xl border text-xs cursor-pointer transition flex items-start justify-between space-x-2 ${
        isActive
          ? 'bg-amber-50/90 border-amber-400 ring-1 ring-amber-300 shadow-xs'
          : 'bg-[#FAF8F5] border-subtleborder hover:bg-neutral-100/80'
      }`;
      // Make entire card clickable
      el.onclick = (e) => {
        if (e.target.closest('button')) return;
        loadConversationSession(c.id);
      };

      const dt = c.updated_at ? new Date(c.updated_at).toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
      el.innerHTML = `
        <div class="flex-1 space-y-1 min-w-0">
          <div class="flex items-center space-x-2">
            <p class="font-medium text-neutral-900 truncate flex-1">${escapeHtml(c.title || 'Untitled Session')}</p>
            ${isActive ? '<span class="text-[9px] font-mono-code font-bold uppercase bg-amber-200 text-amber-900 px-1.5 py-0.2 rounded flex-shrink-0">Active</span>' : ''}
          </div>
          <div class="flex items-center space-x-2 text-[10px] text-neutral-400 font-mono-code">
            <span>${dt}</span>
            <span>•</span>
            <span>${c.message_count || 0} msgs</span>
          </div>
        </div>
        <button id="conv-del-btn-${c.id}" onclick="deleteConversationSession('${c.id}', event)" class="text-neutral-400 hover:text-rose-600 p-1 rounded transition cursor-pointer flex-shrink-0" title="Delete chat">
          <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
        </button>
      `;
      container.appendChild(el);
    });

    if (window.lucide) lucide.createIcons();
  } catch (err) {
    container.innerHTML = `
      <div class="p-3 text-xs text-rose-600 font-mono-code">
        Error loading conversations: ${err.message}
      </div>
    `;
  }
}

function showDirectCitation(citation) {
  if (!citation) return;
  const drawer = document.getElementById('citation-drawer');
  const sourceEl = document.getElementById('drawer-source');
  const pageEl = document.getElementById('drawer-page');
  const excerptEl = document.getElementById('drawer-excerpt');

  if (sourceEl) sourceEl.textContent = citation.source || 'Medical Document';
  if (pageEl) pageEl.textContent = `Original PDF Page ${citation.page || 1}`;
  if (excerptEl) excerptEl.textContent = `"${citation.excerpt || citation.text || 'Excerpt not available'}"`;

  closeMobileSidebar();
  closeConversationsDrawer();

  const backdrop = document.getElementById('conversations-backdrop');
  if (backdrop) backdrop.classList.remove('hidden');

  if (drawer) {
    drawer.classList.remove('translate-x-full');
  }
  if (window.lucide) lucide.createIcons();
}
window.showDirectCitation = showDirectCitation;

async function loadConversationSession(convId, autoClose = true, autoSwitch = true) {
  try {
    if (autoSwitch) {
      switchView('chat');
    }
    if (autoClose) {
      closeConversationsDrawer();
    }

    const chatMessages = document.getElementById('chat-messages');
    if (chatMessages && autoSwitch) {
      chatMessages.innerHTML = `
        <div class="py-16 text-center text-xs text-neutral-400 font-mono-code space-y-3">
          <div class="inline-block animate-spin w-6 h-6 border-2 border-darktext border-t-transparent rounded-full"></div>
          <p class="font-medium text-neutral-700">Loading conversation history...</p>
        </div>
      `;
    }

    const res = await fetch(apiEndpoint(`/api/v1/conversations/${convId}`));
    if (res.status === 404) {
      // Clean up stale or deleted conversation ID
      localStorage.removeItem('perfusion_current_conv_id');
      if (state.currentConversationId === convId) {
        state.currentConversationId = null;
      }
      return;
    }
    if (!res.ok) throw new Error('Unable to retrieve conversation.');
    const conv = await res.json();

    state.currentConversationId = conv.id;
    localStorage.setItem('perfusion_current_conv_id', conv.id);
    state.chatHistory = [];

    const sub = document.getElementById('chat-session-subtitle');
    if (sub && conv.title) {
      sub.textContent = `Session: "${conv.title}"`;
      sub.className = 'text-[11px] text-amber-900 font-mono-code mt-0.5 truncate max-w-md font-semibold';
    }

    if (!chatMessages) return;
    chatMessages.innerHTML = '';

    const messages = conv.messages || [];
    if (messages.length === 0) {
      chatMessages.innerHTML = `
        <div class="py-12 text-center text-xs text-neutral-400 font-mono-code space-y-2">
          <i data-lucide="message-square" class="w-8 h-8 mx-auto text-neutral-300"></i>
          <p class="font-medium text-neutral-600">This conversation session has no stored messages.</p>
          <p class="text-[11px] text-neutral-400">Ask a question below to begin this thread.</p>
        </div>
      `;
    } else {
      messages.forEach((m) => {
        state.chatHistory.push({ role: m.role, content: m.content });
        if (m.role === 'user') {
          const userEl = document.createElement('div');
          userEl.className = 'flex justify-end';
          userEl.innerHTML = `
            <div class="bg-[#18181B] text-white rounded-2xl rounded-tr-sm px-4 py-3 text-xs max-w-xl leading-relaxed shadow-xs space-y-1">
              <div class="flex items-center justify-between text-[10px] text-neutral-400 font-mono-code mb-1">
                <span>You</span>
              </div>
              <p class="whitespace-pre-wrap">${escapeHtml(m.content || '')}</p>
            </div>
          `;
          chatMessages.appendChild(userEl);
        } else {
          const asstEl = document.createElement('div');
          asstEl.className = 'flex items-start space-x-3 max-w-3xl';

          let parsedContent = m.content || '';
          try {
            if (window.marked && typeof window.marked.parse === 'function') {
              parsedContent = window.marked.parse(parsedContent);
            } else if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
              parsedContent = marked.parse(parsedContent);
            } else {
              parsedContent = escapeHtml(parsedContent).replace(/\n/g, '<br>');
            }
          } catch (e) {
            parsedContent = escapeHtml(parsedContent).replace(/\n/g, '<br>');
          }

          asstEl.innerHTML = `
            <div class="w-8 h-8 rounded-lg bg-[#18181B] text-amber-300 flex items-center justify-center flex-shrink-0 mt-0.5 shadow-xs">
              <i data-lucide="activity" class="w-4 h-4"></i>
            </div>
            <div class="bg-white border border-subtleborder rounded-2xl rounded-tl-sm p-4 shadow-xs space-y-2 flex-1 text-xs text-neutral-800">
              <div class="flex items-center justify-between border-b border-subtleborder/60 pb-1.5">
                <div class="flex items-center space-x-2">
                  <span class="w-2 h-2 rounded-full ${m.grounded !== false ? 'bg-emerald-500' : 'bg-amber-500'}"></span>
                  <span class="font-mono-code font-bold text-neutral-900 text-[11px]">Perfusion AI</span>
                </div>
              </div>
              <div class="prose-clinical text-xs leading-relaxed text-neutral-800">
                ${parsedContent}
              </div>
            </div>
          `;

          chatMessages.appendChild(asstEl);
        }
      });
    }

    loadConversationsList();
    scrollChatToBottom();
    if (window.lucide) lucide.createIcons();
  } catch (err) {
    console.error('Failed to load conversation:', err);
    showToastNotification(`Could not load chat: ${err.message}`, 'error');
  }
}

async function deleteConversationSession(convId, event) {
  if (event) event.stopPropagation();
  const card = document.getElementById(`conv-card-${convId}`);
  const delBtn = document.getElementById(`conv-del-btn-${convId}`);

  try {
    const confirmed = await showConfirmDialog({
      title: 'Delete Chat Session',
      message: 'Are you sure you want to delete this conversation? This action cannot be undone.',
      confirmText: 'Delete',
      danger: true,
      loadingText: 'Deleting...',
      onConfirm: async () => {
        // Show loading state immediately on card
        if (card) {
          card.classList.add('opacity-40', 'pointer-events-none', 'bg-rose-50/50');
        }
        if (delBtn) {
          delBtn.innerHTML = '<div class="inline-block animate-spin w-3.5 h-3.5 border-2 border-rose-600 border-t-transparent rounded-full"></div>';
        }

        const res = await fetch(apiEndpoint(`/api/v1/conversations/${convId}`), { method: 'DELETE' });
        if (!res.ok) throw new Error('Delete failed on server.');

        if (state.currentConversationId === convId) {
          clearChat(false);
        }
      }
    });

    if (!confirmed) return;

    // Smoothly animate card removal
    if (card) {
      card.style.transition = 'all 0.22s ease-out';
      card.style.transform = 'translateX(18px)';
      card.style.opacity = '0';
      setTimeout(() => {
        loadConversationsList();
      }, 220);
    } else {
      loadConversationsList();
    }
    showToastNotification('Conversation deleted successfully', 'success');
  } catch (err) {
    if (card) {
      card.classList.remove('opacity-40', 'pointer-events-none', 'bg-rose-50/50');
    }
    if (delBtn) {
      delBtn.innerHTML = '<i data-lucide="trash-2" class="w-3.5 h-3.5"></i>';
      if (window.lucide) lucide.createIcons();
    }
    showToastNotification(`Delete failed: ${err.message}`, 'error');
  }
}

function startFreshChatFromDrawer() {
  switchView('chat');
  closeConversationsDrawer();
  clearChat(false);
}
