/* ── App State ────────────────────────────────────────────────────────────── */
let currentView = 'dashboard';
let currentConvId = null;
let conversations = [];
let selectedTags = [];
let pollTimers = [];
let lastWAStatus = '';
let waStatusTimer = null;
let lastSentBodyQueue = [];
let _sseSource = null;
let _sending = false;

/* ── Estado de conversas (portugués) ─────────────────────────────────────── */
const CONV_STATUS = { new: 'Novo', open: 'Aberto', waiting: 'Aguardando', resolved: 'Resolvido', closed: 'Fechado' };
function statusLabel(s) { return CONV_STATUS[s] || s || ''; }
let contextMenuConvId = null;

/* ── Bulk selection ─────────────────────────────────────────────────────── */
let selectedConvIds = new Set();

/* ── Global agent toggle ───────────────────────────────────────────────── */
async function loadGlobalAgentMode() {
    const data = await api('/api/settings/agent-mode');
    if (data && data.auto_mode !== undefined) {
        const toggle = document.getElementById('global-agent-toggle');
        if (toggle) toggle.checked = !!data.auto_mode;
    }
}

async function toggleGlobalAgent(checked) {
    const res = await api('/api/settings/agent-mode', {
        method: 'PUT',
        body: JSON.stringify({ auto_mode: checked })
    });
    if (res && !res.error) {
        toast(checked ? 'Agente IA ativado para novas conversas' : 'Agente IA desativado (modo manual)', 'success');
    }
}

/* ── Toast Notifications ─────────────────────────────────────────────────── */
let _toastCounter = 0;

function toast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    const icons = {
        success: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#22c55e" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
        error: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        info: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#6366f1" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };
    el.innerHTML = `${icons[type] || icons.info}<span>${esc(message)}</span><button class="toast-close" onclick="event.stopPropagation(); this.parentElement.remove()">&times;</button>`;
    el.addEventListener('click', e => e.stopPropagation());
    container.appendChild(el);
    setTimeout(() => { el.classList.add('toast-exit'); }, 3000);
    setTimeout(() => { el.remove(); }, 3400);
}

function toastLoading(message) {
    const container = document.getElementById('toast-container');
    const id = `toast-${++_toastCounter}`;
    const el = document.createElement('div');
    el.id = id;
    el.className = 'toast toast-loading';
    el.innerHTML = `<span class="spinner toast-spinner"></span><span>${esc(message)}</span>`;
    el.addEventListener('click', e => e.stopPropagation());
    container.appendChild(el);
    return id;
}

function toastDone(id, message, type = 'success') {
    const el = document.getElementById(id);
    if (!el) { toast(message, type); return; }
    const icons = {
        success: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#22c55e" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
        error: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        warning: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#f59e0b" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    };
    el.className = `toast toast-${type}`;
    el.innerHTML = `${icons[type] || icons.success}<span>${esc(message)}</span><button class="toast-close" onclick="event.stopPropagation(); this.parentElement.remove()">&times;</button>`;
    setTimeout(() => { el.classList.add('toast-exit'); }, 3000);
    setTimeout(() => { el.remove(); }, 3400);
}

/* ── View Animations ─────────────────────────────────────────────────────── */
function animateViewIn(viewId) {
    const el = document.getElementById(`view-${viewId}`);
    if (!el) return;
    el.style.animation = 'none';
    el.offsetHeight; // reflow
    el.style.animation = 'fadeIn 0.3s ease';
}

/* ── Navigation ──────────────────────────────────────────────────────────── */
document.querySelectorAll('.nav-item[data-view]').forEach(el => {
    el.addEventListener('click', e => {
        e.preventDefault();
        switchView(el.dataset.view);
    });
});

function switchView(view) {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelector(`.nav-item[data-view="${view}"]`).classList.add('active');
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    // Bot e Fila Humana reutilizam a view-conversations
    const domView = (view === 'bot' || view === 'human-queue') ? 'conversations' : view;
    document.getElementById(`view-${domView}`).classList.add('active');
    // Limpa lista de conversas ao trocar de view (evita flash de conteúdo antigo)
    if (domView === 'conversations') {
        const list = document.getElementById('conv-list');
        if (list) {
            list.dataset.sig = '';
            list.dataset.loaded = '';
            list.innerHTML = skeletonRows(5);
        }
    }
    currentView = view;
    animateViewIn(view);
    loadView(view);
    closeSidebar();
    closeChatMobile();
}

function loadView(view) {
    pollTimers.forEach(clearInterval);
    pollTimers = [];
    if (waStatusTimer) { clearInterval(waStatusTimer); waStatusTimer = null; }
    switch (view) {
        case 'dashboard':
            loadDashboard();
            pollTimers.push(setInterval(loadDashboard, 15000));
            break;
        case 'conversations':
            loadConversations();
            // Atualiza o painel da conversa aberta sem reconstruir o chat (evita animação de reabrir)
            if (currentConvId) refreshConversationPanel(currentConvId);
            pollTimers.push(setInterval(loadConversations, 10000));
            break;
        case 'bot':
            loadConversations(1);
            if (currentConvId) refreshConversationPanel(currentConvId);
            pollTimers.push(setInterval(() => loadConversations(1), 10000));
            break;
        case 'human-queue':
            loadConversations(0);
            if (currentConvId) refreshConversationPanel(currentConvId);
            pollTimers.push(setInterval(() => loadConversations(0), 10000));
            updateHumanQueueBadge();
            break;
        case 'contacts': loadContacts(); break;
        case 'tags': loadTags(); break;
        case 'templates': loadTemplates(); break;
        case 'knowledge':
            loadKnowledge();
            break;
        case 'whatsapp':
            loadWAConnection();
            loadWAConfig();
            loadTransferMessage();
            loadWATemplates();
            startWAConnectionPolling();
            break;
        case 'crm':
            switchCrmView('automations');
            break;
        case 'agendamentos':
            loadAgendamentosPendentes();
            pollTimers.push(setInterval(loadAgendamentosPendentes, 20000));
            break;
        case 'horarios':
            loadHorarios();
            break;
        case 'agenda':
            loadAgendaConfig();
            loadAgenda();
            pollTimers.push(setInterval(agendaAtualizarEmSegundoPlano, 20000));
            break;
    }
}

/* ── API Helpers ──────────────────────────────────────────────────────────── */
async function api(url, opts = {}) {
    const res = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    if (res.status === 401 || res.redirected) {
        window.location.href = '/login';
        return null;
    }
    // Erro com pagina HTML (429, 502 do Render acordando...) nao e JSON: sem
    // isto a promessa quebrava e a tela ficava esperando a proxima rodada.
    try {
        return await res.json();
    } catch (e) {
        console.warn(`[api] ${url}: resposta ${res.status} sem JSON`);
        return null;
    }
}

/* ── Dashboard ────────────────────────────────────────────────────────────── */
async function loadDashboard() {
    const grid = document.getElementById('stats-grid');
    if (!grid.dataset.loaded) grid.innerHTML = skeletonCards(5);
    const stats = await api('/api/dashboard');
    if (!stats) {
        grid.innerHTML = '<p class="muted">Erro ao carregar</p>';
        return;
    }
    grid.dataset.loaded = '1';
    grid.innerHTML = `
        <div class="stat-card">
            <div class="stat-icon"><svg viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>
            <div class="stat-value">${stats.total_contacts}</div>
            <div class="stat-label">Contatos</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon"><svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div>
            <div class="stat-value">${stats.open_conversations}</div>
            <div class="stat-label">Conversas Abertas</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon"><svg viewBox="0 0 24 24"><path d="M22 2L11 13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></div>
            <div class="stat-value">${stats.total_messages}</div>
            <div class="stat-label">Mensagens Totais</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div>
            <div class="stat-value">${stats.messages_today}</div>
            <div class="stat-label">Mensagens Hoje</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon"><svg viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg></div>
            <div class="stat-value">${stats.unread_messages}</div>
            <div class="stat-label">Não Lidas</div>
        </div>
    `;
}

/* ── Conversations ────────────────────────────────────────────────────────── */
document.getElementById('conv-filter').addEventListener('change', () => loadConversations());

let _loadConvToken = 0;

async function loadConversations(autoMode = null) {
    const myToken = ++_loadConvToken;
    const status = document.getElementById('conv-filter').value;
    const list = document.getElementById('conv-list');
    const archivedParam = status === 'archived' ? '&archived=1' : '';
    const statusParam = status === 'archived' ? '' : status;
    const autoModeParam = autoMode !== null ? `&auto_mode=${autoMode}` : '';
    // Reset assinatura se autoMode mudou (evita mostrar conteúdo da view errada)
    if (list.dataset.lastAutoMode !== String(autoMode)) {
        list.dataset.sig = '';
        list.dataset.lastAutoMode = autoMode;
    }
    if (!list.dataset.loaded) list.innerHTML = skeletonRows(5);
    const scrollPos = list.scrollTop;
    conversations = await api(`/api/conversations?status=${statusParam}${archivedParam}${autoModeParam}`);
    if (!conversations || myToken !== _loadConvToken) return;
    list.dataset.loaded = '1';
    if (conversations.length === 0) {
        if (list.dataset.sig !== 'empty') {
            list.innerHTML = '<div class="empty-state">Nenhuma conversa</div>';
            list.dataset.sig = 'empty';
        }
        return;
    }
    const html = conversations.map(c => {
        const name = c.contact_name || c.contact_phone;
        const initials = esc(name.slice(0, 2).toUpperCase());
        const avatarBg = c.contact_avatar_color || '';
        const avatarStyle = avatarBg ? `background:${avatarBg}` : '';
        const avatar = c.contact_avatar
            ? `<img src="${esc(c.contact_avatar)}" alt="" class="conv-avatar-img" onerror="this.remove()">`
            : '';
        const lastMsg = c.last_message_at ? new Date(c.last_message_at + 'Z').toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'}) : '';
        const tagChips = (c.tags || []).map(t =>
            `<span class="conv-tag-chip" style="background:${t.color}" title="${esc(t.name)}">${esc(t.name)}</span>`
        ).join('');
        const badges = [];
        if (c.pinned) badges.push('<span class="conv-badge" title="Fixada">📌</span>');
        if (c.muted) badges.push('<span class="conv-badge" title="Silenciado">🔇</span>');
        if (c.favorite) badges.push('<span class="conv-badge" title="Favorita">⭐</span>');
        if (c.archived) badges.push('<span class="conv-badge" title="Arquivada">📦</span>');
        const isSelected = selectedConvIds.has(c.id);
        return `
            <div class="conv-item ${c.id === currentConvId ? 'active' : ''}${isSelected ? ' selected' : ''}" data-conv-id="${c.id}" onclick="selectConversation(${c.id})" oncontextmenu="openContextMenu(event, ${c.id})">
                <div class="conv-check-visual${isSelected ? ' checked' : ''}" onclick="event.stopPropagation(); toggleConvSelect(${c.id})"></div>
                <div class="conv-avatar" style="${avatarStyle}">${avatar}${initials}</div>
                <div class="conv-meta">
                    <div class="conv-name">${esc(name)} ${badges.join('')}</div>
                    <div class="conv-preview"><span class="status-dot status-${c.status}"></span>${esc(statusLabel(c.status))}${c.last_message_body ? ' · ' + esc(c.last_message_body.length > 40 ? c.last_message_body.slice(0, 40) + '…' : c.last_message_body) : ''}</div>
                    ${tagChips ? `<div class="conv-tags">${tagChips}</div>` : ''}
                </div>
                <div style="text-align:right">
                    <div class="conv-time">${lastMsg}</div>
                    ${c.unread_count > 0 ? `<div class="conv-unread">${c.unread_count}</div>` : ''}
                </div>
            </div>`;
    }).join('');
    // Evita piscar: só substitui o DOM se algo mudou de verdade.
    // (O poll de 10s e os eventos SSE chamam isto constantemente.)
    if (list.dataset.sig === html) {
        list.scrollTop = scrollPos;
        return;
    }
    list.dataset.sig = html;
    list.innerHTML = html;
    list.scrollTop = scrollPos;
}

async function selectConversation(convId) {
    // Se já está aberta esta conversa, apenas atualiza em contexto
    // (sem recargar skeleton nem saltar o scroll): refresh rápido.
    if (convId === currentConvId) {
        document.querySelectorAll('.conv-item').forEach(el => {
            el.classList.toggle('active', Number(el.dataset.convId) === convId);
        });
        refreshConversationPanel(convId);
        const data = await api(`/api/conversations/${convId}`);
        if (data && data.messages) {
            renderMessages(data.messages);
        }
        return;
    }

    // Render completo (header + mensagens + painel) — usado ao abrir uma conversa
    currentConvId = convId;
    // Mostra painel do chat no desktop
    const layout = document.querySelector('.conv-layout');
    if (layout) layout.classList.remove('chat-closed');
    // Mostra botao de detalhes
    const showBtn = document.getElementById('info-panel-show-btn');
    if (showBtn && _infoPanelHidden) showBtn.classList.add('visible');
    document.querySelectorAll('.conv-item').forEach(el => {
        el.classList.toggle('active', Number(el.dataset.convId) === convId);
    });

    setChatLoading(true);
    const msgDiv = document.getElementById('chat-messages');
    msgDiv.innerHTML = skeletonMsgs();
    try {
        // Consultas independentes em paralelo (evita esperas em sequência).
        const [data, allTags] = await Promise.all([
            api(`/api/conversations/${convId}`),
            api('/api/tags'),
        ]);
        if (!data) return;
        const { conversation: conv, contact, messages, tags } = data;

        renderChatHeader(conv, contact);
        msgDiv.innerHTML = messages.map(m => msgHTML(m, false)).join('');
        bindMsgMedia(msgDiv);
        scrollChatBottom();

        document.getElementById('chat-input-area').style.display = 'flex';
        autoResizeChatInput();

        renderInfoPanel(conv, contact, tags, allTags || []);

        // Abre o chat no mobile
        openChatMobile();

        // Mark as read
        await api(`/api/conversations/${convId}/read`, { method: 'PUT' });
        loadConversations();
        updateUnreadBadge();
    } finally {
        setChatLoading(false);
    }
}

// Renderiza mensagens preservando a posição de scroll (salta só se está abaixo).
function renderMessages(messages) {
    const el = document.getElementById('chat-messages');
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    const oldHeight = el.scrollHeight;
    el.innerHTML = messages.map(m => msgHTML(m, false)).join('');
    bindMsgMedia(el);
    if (atBottom) {
        scrollChatBottom();
    } else {
        el.scrollTop = oldHeight;
    }
}

function isNearBottom(el) {
    return (el.scrollHeight - el.scrollTop - el.clientHeight) < 60;
}

// Carregamento minimalista ao abrir conversa: apenas uma barra fina de
// progresso no topo do painel do chat (sem overlay/skeleton pesado).
function setChatLoading(show) {
    const panel = document.querySelector('.conv-chat-panel');
    if (panel) panel.classList.toggle('chat-loading', !!show);
}

// Botão que disparou a ação (via onclick inline). Ignora itens do menu de
// contexto para não trocar o rótulo deles por spinner.
function _btnFromEvent() {
    const b = (typeof event !== 'undefined' && event) ? event.currentTarget : null;
    return (b && !b.classList.contains('ctx-menu-item')) ? b : null;
}

function deselectConversation() {
    currentConvId = null;
    // Esconde painel do chat no desktop
    const layout = document.querySelector('.conv-layout');
    if (layout) layout.classList.add('chat-closed');
    // Esconde botao de detalhes
    const showBtn = document.getElementById('info-panel-show-btn');
    if (showBtn) showBtn.classList.remove('visible');
    // Esconde painel de detalhes
    const panel = document.getElementById('conv-info-panel');
    if (panel) panel.classList.add('hidden');
    _infoPanelHidden = true;
    document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
    const header = document.getElementById('chat-header');
    if (header) header.innerHTML = '<span>Selecione uma conversa</span>';
    const msgDiv = document.getElementById('chat-messages');
    // Animación de salida breve antes de limpiar el chat.
    if (msgDiv && msgDiv.innerHTML) {
        msgDiv.style.animation = 'msgOut 0.16s ease forwards';
        setTimeout(() => {
            if (msgDiv) { msgDiv.innerHTML = ''; msgDiv.style.animation = ''; }
        }, 140);
    }
    const inputArea = document.getElementById('chat-input-area');
    if (inputArea) inputArea.style.display = 'none';
    const info = document.getElementById('info-panel');
    if (info) info.innerHTML = '<p class="muted">Selecione uma conversa para ver detalhes</p>';
}

/* ── Context menu (clique direito em conversa) ────────────────────────────── */
function openContextMenu(event, convId) {
    event.preventDefault();
    event.stopPropagation();
    contextMenuConvId = convId;
    closeContextMenu();

    const found = conversations.find(c => c.id === convId);
    const c = found || {};
    const archLabel = c.archived ? 'Desarquivar' : 'Arquivar';
    const muteLabel = c.muted ? 'Ativar som' : 'Silenciar';
    const pinLabel = c.pinned ? 'Desafixar' : 'Fixar';
    const favLabel = c.favorite ? 'Remover dos favoritos' : 'Adicionar aos favoritos';
    const isUnread = (c.unread_count || 0) > 0;
    const readLabel = isUnread ? 'Marcar como lida' : 'Marcar como não lida';
    const readFn = isUnread ? `markReadConv(${convId})` : `markUnreadConv(${convId})`;

    const menu = document.createElement('div');
    menu.className = 'ctx-menu';
    menu.style.position = 'fixed';
    menu.style.left = `${Math.min(event.clientX, window.innerWidth - 220)}px`;
    menu.style.top = `${Math.min(event.clientY, window.innerHeight - 260)}px`;
    menu.innerHTML = `
        <div class="ctx-menu-item" onclick="setConvFlag(${convId}, 'archived', ${c.archived ? 0 : 1})">${archLabel}</div>
        <div class="ctx-menu-item" onclick="setConvFlag(${convId}, 'muted', ${c.muted ? 0 : 1})">${muteLabel}</div>
        <div class="ctx-menu-item" onclick="setConvFlag(${convId}, 'pinned', ${c.pinned ? 0 : 1})">${pinLabel}</div>
        <div class="ctx-menu-item" onclick="setConvFlag(${convId}, 'favorite', ${c.favorite ? 0 : 1})">${favLabel}</div>
        <div class="ctx-menu-sep"></div>
        <div class="ctx-menu-item" onclick="${readFn}">${readLabel}</div>
        <div class="ctx-menu-item" onclick="clearConv(${convId})">Limpar conversa</div>
        <div class="ctx-menu-item danger" onclick="deleteConv(${convId})">Apagar conversa</div>
    `;
    document.body.appendChild(menu);
}

function closeContextMenu() {
    const existing = document.querySelector('.ctx-menu');
    if (existing) existing.remove();
}

/* ── Bulk selection ─────────────────────────────────────────────────────── */
function toggleConvSelect(convId) {
    if (selectedConvIds.has(convId)) {
        selectedConvIds.delete(convId);
    } else {
        selectedConvIds.add(convId);
    }
    const item = document.querySelector(`.conv-item[data-conv-id="${convId}"]`);
    if (item) {
        item.classList.toggle('selected', selectedConvIds.has(convId));
        const vis = item.querySelector('.conv-check-visual');
        if (vis) vis.classList.toggle('checked', selectedConvIds.has(convId));
    }
    _syncSelectAll();
    updateBulkToolbar();
}

function toggleSelectAll(checked) {
    const items = document.querySelectorAll('.conv-item');
    items.forEach(el => {
        const id = Number(el.dataset.convId);
        if (checked) {
            selectedConvIds.add(id);
        } else {
            selectedConvIds.delete(id);
        }
        el.classList.toggle('selected', checked);
        const vis = el.querySelector('.conv-check-visual');
        if (vis) vis.classList.toggle('checked', checked);
    });
    updateBulkToolbar();
}

function _syncSelectAll() {
    const items = document.querySelectorAll('.conv-item');
    const allChecked = items.length > 0 && [...items].every(el => selectedConvIds.has(Number(el.dataset.convId)));
    const selectAll = document.getElementById('conv-select-all');
    if (selectAll) selectAll.classList.toggle('checked', allChecked);
}

function deselectAllConvs() {
    selectedConvIds.clear();
    document.querySelectorAll('.conv-item').forEach(el => {
        el.classList.remove('selected');
        const vis = el.querySelector('.conv-check-visual');
        if (vis) vis.classList.remove('checked');
    });
    const selectAll = document.getElementById('conv-select-all');
    if (selectAll) selectAll.classList.remove('checked');
    updateBulkToolbar();
    _hideBulkMenus();
}

function updateBulkToolbar() {
    const toolbar = document.getElementById('bulk-toolbar');
    const count = document.getElementById('bulk-count');
    if (!toolbar) return;
    const n = selectedConvIds.size;
    if (n > 0) {
        toolbar.style.display = 'flex';
        count.textContent = `${n} selecionada${n > 1 ? 's' : ''}`;
    } else {
        toolbar.style.display = 'none';
        _hideBulkMenus();
    }
}

function _hideBulkMenus() {
    const sm = document.getElementById('bulk-status-menu');
    const tm = document.getElementById('bulk-tag-menu');
    if (sm) sm.style.display = 'none';
    if (tm) tm.style.display = 'none';
}

async function bulkAction(action, params = {}) {
    const ids = [...selectedConvIds];
    if (!ids.length) return;
    _hideBulkMenus();
    const actionLabels = { read: 'Marcando como lido...', unread: 'Marcando como nao lido...', archive: 'Arquivando...', delete: 'Excluindo...', clear: 'Limpando...' };
    const loadingToast = toastLoading(actionLabels[action] || 'Processando...');
    const res = await api('/api/conversations/bulk', {
        method: 'POST',
        body: JSON.stringify({ ids, action, params })
    });
    const loadingEl = document.getElementById(loadingToast);
    if (loadingEl) loadingEl.remove();
    if (res && !res.error) {
        const n = res.processed || ids.length;
        toast(`${n} conversa${n > 1 ? 's' : ''} atualizada${n > 1 ? 's' : ''}`, 'success');
        deselectAllConvs();
        loadConversations();
    } else {
        toast(res?.error || 'Erro ao executar ação em massa', 'error');
    }
}

function bulkConfirmAction(action) {
    const ids = [...selectedConvIds];
    if (!ids.length) return;
    const msg = action === 'delete'
        ? `Apagar ${ids.length} conversa${ids.length > 1 ? 's' : ''}?`
        : `Limpar ${ids.length} conversa${ids.length > 1 ? 's' : ''}?`;
    if (!confirm(msg)) return;
    bulkAction(action);
}

function bulkShowStatusMenu(e) {
    e.stopPropagation();
    const menu = document.getElementById('bulk-status-menu');
    if (!menu) return;
    const wasVisible = menu.style.display === 'block';
    _hideBulkMenus();
    if (wasVisible) return;
    const rect = e.currentTarget.getBoundingClientRect();
    menu.style.display = 'block';
    menu.style.position = 'fixed';
    menu.style.left = rect.left + 'px';
    menu.style.top = (rect.bottom + 4) + 'px';
}

async function bulkShowTagMenu(e) {
    e.stopPropagation();
    const menu = document.getElementById('bulk-tag-menu');
    if (!menu) return;
    const wasVisible = menu.style.display === 'block';
    _hideBulkMenus();
    if (wasVisible) return;
    const allTags = await api('/api/tags');
    if (!allTags || !allTags.length) {
        toast('Nenhuma tag disponível', 'info');
        return;
    }
    menu.innerHTML = allTags.map(t =>
        `<div class="bulk-dropdown-item" onclick="bulkAction('add_tag', {tag_id:${t.id}})">${esc(t.name || t.label || 'Tag ' + t.id)}</div>`
    ).join('');
    const rect = e.currentTarget.getBoundingClientRect();
    menu.style.display = 'block';
    menu.style.position = 'fixed';
    menu.style.left = rect.left + 'px';
    menu.style.top = (rect.bottom + 4) + 'px';
}

document.addEventListener('click', (e) => {
    if (!e.target.closest('#bulk-status-menu') && !e.target.closest('[onclick*="bulkShowStatus"]')) {
        const sm = document.getElementById('bulk-status-menu');
        if (sm) sm.style.display = 'none';
    }
    if (!e.target.closest('#bulk-tag-menu') && !e.target.closest('[onclick*="bulkShowTag"]')) {
        const tm = document.getElementById('bulk-tag-menu');
        if (tm) tm.style.display = 'none';
    }
});

async function setConvFlag(convId, flag, value) {
    closeContextMenu();
    const btn = _btnFromEvent();
    setBtnLoading(btn, true);
    let res = null;
    try {
        res = await api(`/api/conversations/${convId}/flags`, {
            method: 'PUT',
            body: JSON.stringify({ [flag]: !!value }),
        });
    } finally {
        setBtnLoading(btn, false);
    }
    if (res && !res.error) {
        const flagLabels = {
            archived: res.archived ? 'Conversa arquivada' : 'Conversa desarquivada',
            pinned: res.pinned ? 'Conversa fixada' : 'Conversa desafixada',
            muted: res.muted ? 'Conversa silenciada' : 'Som reativado',
            favorite: res.favorite ? 'Adicionada aos favoritos' : 'Removida dos favoritos'
        };
        toast(flagLabels[flag] || 'Conversa atualizada', 'success');
    } else {
        toast('Erro ao atualizar', 'error');
    }
    if (currentConvId === convId) refreshConversationPanel(convId);
    loadConversations();
}

async function markReadConv(convId) {
    closeContextMenu();
    const res = await api(`/api/conversations/${convId}/read`, { method: 'PUT' });
    if (res && !res.error) toast('Conversa marcada como lida', 'success');
    else toast('Erro ao marcar', 'error');
    loadConversations();
    updateUnreadBadge();
}

async function markUnreadConv(convId) {
    closeContextMenu();
    const res = await api(`/api/conversations/${convId}/unread`, { method: 'PUT' });
    if (res && !res.error) toast('Conversa marcada como não lida', 'success');
    else toast('Erro ao marcar', 'error');
    loadConversations();
    updateUnreadBadge();
}

async function clearConv(convId) {
    closeContextMenu();
    if (!confirm('Limpar esta conversa?')) return;
    const res = await api(`/api/conversations/${convId}/clear`, { method: 'POST' });
    if (res && !res.error) {
        toast('Conversa limpa', 'success');
        if (currentConvId === convId) {
            document.getElementById('chat-messages').innerHTML = '';
        }
        loadConversations();
    } else {
        toast('Erro ao limpar', 'error');
    }
}

async function deleteConv(convId) {
    closeContextMenu();
    if (!confirm('Apagar esta conversa?')) return;
    const res = await api(`/api/conversations/${convId}`, { method: 'DELETE' });
    if (res && !res.error) {
        toast('Conversa apagada', 'success');
        if (currentConvId === convId) deselectConversation();
        loadConversations();
    } else {
        toast('Erro ao apagar', 'error');
    }
}

// Atualiza header + painel de detalhes sem reconstruir as mensagens (sem animação de "reabrir")
// Etiquetas mudam raramente: 1 busca a cada minuto basta. Antes iam junto a
// cada mensagem da conversa aberta.
let _tagsCache = { em: 0, tags: null };
async function tagsEmCache() {
    if (_tagsCache.tags && Date.now() - _tagsCache.em < 60000) return _tagsCache.tags;
    const tags = await api('/api/tags');
    if (tags) _tagsCache = { em: Date.now(), tags };
    return tags || _tagsCache.tags || [];
}

async function refreshConversationPanel(convId, dadosProntos = null) {
    if (!convId) return;
    const [data, allTags] = await Promise.all([
        dadosProntos || api(`/api/conversations/${convId}`),
        tagsEmCache(),
    ]);
    if (!data) return;
    const { conversation: conv, contact, tags } = data;
    renderChatHeader(conv, contact);
    document.getElementById('chat-input-area').style.display = 'flex';
    autoResizeChatInput();
    renderInfoPanel(conv, contact, tags, allTags || []);
}

function renderChatHeader(conv, contact) {
    const name = contact?.name || contact?.phone || 'Desconhecido';
    const autoMode = contact?.auto_mode ? 'Auto' : 'Humano';
    const autoClass = contact?.auto_mode ? 'auto-on' : 'auto-off';
    const avatarBg = contact?.avatar_color || '';
    const avatarStyle = avatarBg ? `background:${avatarBg}` : '';
    const avatar = contact?.avatar_url
        ? `<img src="${esc(contact.avatar_url)}" alt="" class="conv-avatar-img" onerror="this.remove()">`
        : '';
    const initials = esc(name.slice(0, 2).toUpperCase());
    const backBtn = `<button class="chat-back-btn" onclick="closeChatMobile()"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg></button>`;
    document.getElementById('chat-header').innerHTML = `
        ${backBtn}
        <div class="chat-header-avatar" style="${avatarStyle}">${avatar}${initials}</div>
        <span>${esc(name)} (${esc(statusLabel(conv.status))})</span>
        <span class="auto-badge ${autoClass}">${autoMode}</span>
    `;
}

const MEDIA_LABELS = {
    image: 'Imagem', video: 'Vídeo', audio: 'Áudio', ptt: 'Áudio',
    document: 'Documento', sticker: 'Figurinha', gif: 'GIF',
};

// Rótulos que o webhook grava quando não há legenda ([Imagem], [Video]...).
// Não devem aparecer junto com a mídia renderizada — são redundantes.
const MEDIA_PLACEHOLDER_RE = /^\[(Imagem|Image|V[íi]deo|Video|[ÁaA]udio|Figurinha|Documento|Document|Sticker|GIF|Media|M[íi]dia)[^\]]*\](:.*)?$/i;

function isMediaPlaceholder(text) {
    return MEDIA_PLACEHOLDER_RE.test(String(text || '').trim());
}

// Tipos que renderizam mídia. "media" é o tipo genérico que instâncias v3 da
// UAZAPI enviam para qualquer mídia — o elemento certo é criado após buscar
// a mídia, conforme o mimeType real da data-URI.
const MEDIA_RENDER_TYPES = new Set(['image', 'video', 'audio', 'ptt', 'document', 'sticker', 'gif', 'media']);

function msgMediaHTML(m) {
    const type = (m.msg_type || 'text').toLowerCase().trim();
    // Renderiza mídia se o tipo é conhecido OU se o body é um placeholder
    // ([Imagem]/[Media]/...): cobre linhas antigas com tipo genérico.
    const isMediaType = MEDIA_RENDER_TYPES.has(type);
    if (!isMediaType && !isMediaPlaceholder(m.body)) return '';
    return `<div class="msg-media-box msg-media-lazy" data-media-dbid="${esc(m.id)}" data-media-kind="${esc(isMediaType ? type : 'media')}">
                <span class="spinner"></span>
                <div class="msg-media-host"></div>
            </div>`;
}

function msgHTML(m, isNew) {
    const timeStr = m.created_at ? new Date(m.created_at.endsWith('Z') ? m.created_at : m.created_at + 'Z').toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '';

    // Mensagens internas do sistema (transferência, etc.)
    if (m.direction === 'internal') {
        return `<div class="msg msg-internal">
            <div class="msg-body">${esc(m.body)}</div>
            <div class="msg-time">${timeStr}</div>
        </div>`;
    }

    const senderName = m.sender || (m.direction === 'in' ? 'Contato' : 'Atendente');
    const msgId = m.uazapi_id || m.id || '';
    const type = (m.msg_type || 'text').toLowerCase();

    // Corpo próprio + (opcionalmente) media adjunta da UAZAPI.
    // O rótulo placeholder ([Imagem], [Audio]...) é escondido quando a mídia
    // renderiza — só legendas reais acompanham a mídia.
    const mediaHTML = msgMediaHTML(m);
    let bodyHTML = '';
    if (m.body && !(mediaHTML && isMediaPlaceholder(m.body))) {
        bodyHTML += `<div class="msg-body">${esc(m.body)}</div>`;
    }
    if (mediaHTML) bodyHTML += mediaHTML;

    // Estado de envio/lectura (só mensagens enviadas pelo panel).
    let statusIcon = '';
    if (m.direction === 'out' && (m.status === 'sending' || (m.id && String(m.id).startsWith('temp-')))) {
        statusIcon = `<span class="msg-status sending"><span class="spinner" style="width:11px;height:11px;border-width:2px"></span></span>`;
    }
    if (m.direction === 'out' && m.status === 'sent') {
        statusIcon = `<span class="msg-status sent" title="Enviado">✓✓</span>`;
    }
    if (m.direction === 'out' && m.status === 'error') {
        statusIcon = `<span class="msg-status error" title="Erro de envio">!</span>`;
    }

    return `<div class="msg msg-${m.direction === 'in' ? 'in' : 'out'}${isNew ? ' msg-new' : ''}${mediaHTML ? ' msg-has-media' : ''}" data-msg-id="${esc(msgId)}">
                ${bodyHTML}
                <div class="msg-time"><span>${esc(senderName)}</span> · ${timeStr}${statusIcon}</div>
            </div>`;
}

function appendMessage(msg) {
    const msgDiv = document.getElementById('chat-messages');
    if (!msgDiv) return;
    msgDiv.insertAdjacentHTML('beforeend', msgHTML(msg, true));
    bindMsgMedia(msgDiv);
    scrollChatBottom();
}

function scrollChatBottom() {
    const msgDiv = document.getElementById('chat-messages');
    if (msgDiv) msgDiv.scrollTop = msgDiv.scrollHeight;
}

/* ── Media lazy-load (imagens/áudio/vídeo/figurinhas UAZAPI) ──────────────── */
let _mediaObserver = null;
let _mediaCache = new Map();
let _mediaInFlight = new Map();

function ensureMediaObserver() {
    if (_mediaObserver) return _mediaObserver;
    _mediaObserver = new IntersectionObserver(entries => {
        for (const entry of entries) {
            if (entry.isIntersecting) {
                _loadMsgMedia(entry.target);
                _mediaObserver.unobserve(entry.target);
            }
        }
    }, { rootMargin: '120px' });
    return _mediaObserver;
}

function bindMsgMedia(container) {
    if (!container) return;
    const boxes = container.querySelectorAll('.msg-media-lazy[data-media-dbid]');
    if (!boxes.length) return;
    const observer = ensureMediaObserver();
    boxes.forEach(b => observer.observe(b));
}

async function _loadMsgMedia(box) {
    const dbid = box?.dataset?.mediaDbid;
    if (!dbid) return;
    // Evita chamadas duplicadas / ya resueltas.
    if (box.dataset.state === 'loading' || box.dataset.state === 'loaded') return;

    const msgId = dbid;
    if (_mediaCache.has(msgId)) {
        _applyMsgMedia(box, _mediaCache.get(msgId));
        return;
    }

    box.dataset.state = 'loading';
    _mediaInFlight.set(msgId, true);
    let data = null;
    try {
        data = await api(`/api/messages/${encodeURIComponent(msgId)}/media`);
    } finally {
        _mediaInFlight.delete(msgId);
    }

    // O endpoint baixa a media on-demand (pode levar alguns segundos) e
    // persiste: se ainda não vier, reintenta poucas vezes antes do fallback.
    if (!data || !data.media_url) {
        const attempts = Number(box.dataset.mediaAttempt || 0) + 1;
        if (attempts <= 3) {
            box.dataset.mediaAttempt = String(attempts);
            box.dataset.state = '';
            setTimeout(() => _loadMsgMedia(box), 3000 * attempts);
            return;
        }
        box.dataset.state = 'loaded';
        _fallbackMsgMedia(box, data?.body);
        return;
    }
    _mediaCache.set(msgId, data.media_url);
    _applyMsgMedia(box, data.media_url);
}

function _buildWaPlayer(container, src) {
    const audio = new Audio();
    audio.preload = 'metadata';
    audio.src = src;

    const playSvg = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,3 20,12 6,21"/></svg>';
    const pauseSvg = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="3" width="4" height="18"/><rect x="15" y="3" width="4" height="18"/></svg>';

    const player = document.createElement('div');
    player.className = 'wa-player';

    const btnPlay = document.createElement('button');
    btnPlay.type = 'button';
    btnPlay.className = 'wa-player-play';
    btnPlay.innerHTML = playSvg;

    const track = document.createElement('div');
    track.className = 'wa-player-track';

    const wave = document.createElement('div');
    wave.className = 'wa-player-wave';

    const info = document.createElement('div');
    info.className = 'wa-player-info';

    const timeEl = document.createElement('span');
    timeEl.className = 'wa-player-time';
    timeEl.textContent = '0:00';

    const speedBtn = document.createElement('button');
    speedBtn.type = 'button';
    speedBtn.className = 'wa-player-speed';
    speedBtn.textContent = '1x';
    const speeds = [1, 1.5, 2];
    let speedIdx = 0;
    speedBtn.onclick = (e) => {
        e.stopPropagation();
        speedIdx = (speedIdx + 1) % speeds.length;
        audio.playbackRate = speeds[speedIdx];
        speedBtn.textContent = speeds[speedIdx] + 'x';
    };

    info.appendChild(timeEl);
    info.appendChild(speedBtn);
    track.appendChild(wave);
    track.appendChild(info);
    player.appendChild(btnPlay);
    player.appendChild(track);
    container.appendChild(player);

    const BAR_COUNT = 32;
    const bars = [];
    for (let i = 0; i < BAR_COUNT; i++) {
        const bar = document.createElement('div');
        bar.className = 'bar';
        bar.style.height = (4 + Math.random() * 20) + 'px';
        wave.appendChild(bar);
        bars.push(bar);
    }

    function fmt(s) {
        if (!isFinite(s)) return '0:00';
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return m + ':' + String(sec).padStart(2, '0');
    }

    function updateWave() {
        const dur = audio.duration || 0;
        const cur = audio.currentTime;
        const pct = dur ? cur / dur : 0;
        const filled = Math.round(pct * BAR_COUNT);
        bars.forEach((b, i) => {
            b.classList.toggle('filled', i < filled);
        });
    }

    audio.addEventListener('loadedmetadata', () => {
        timeEl.textContent = fmt(audio.duration);
    });

    audio.addEventListener('timeupdate', () => {
        timeEl.textContent = fmt(audio.currentTime);
        updateWave();
    });

    audio.addEventListener('ended', () => {
        btnPlay.innerHTML = playSvg;
        btnPlay.classList.remove('playing');
        audio.currentTime = 0;
        updateWave();
    });

    btnPlay.onclick = (e) => {
        e.stopPropagation();
        if (audio.paused) {
            document.querySelectorAll('.wa-player audio').forEach(a => { if (a !== audio) a.pause(); });
            audio.play();
            btnPlay.innerHTML = pauseSvg;
            btnPlay.classList.add('playing');
        } else {
            audio.pause();
            btnPlay.innerHTML = playSvg;
            btnPlay.classList.remove('playing');
        }
    };

    wave.onclick = (e) => {
        e.stopPropagation();
        if (!audio.duration) return;
        const rect = wave.getBoundingClientRect();
        const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        audio.currentTime = pct * audio.duration;
        updateWave();
    };
}

function _applyMsgMedia(box, dataUri) {
    box.dataset.state = 'loaded';
    const spinner = box.querySelector('.spinner');
    if (spinner) spinner.remove();
    if (!dataUri) return;

    // Cria o elemento certo conforme o mimeType real da data-URI
    // (data:image/jpeg;base64,...) — funciona até para o tipo genérico "media".
    const host = box.querySelector('.msg-media-host') || box;
    const kind = (box.dataset.mediaKind || '').toLowerCase();
    const uri = String(dataUri);
    let mime = '';
    if (uri.startsWith('data:')) {
        mime = (uri.match(/^data:([^;,]+)/) || [])[1] || '';
    } else if (/^https?:/i.test(uri)) {
        // URL do payload: deduz o mime pela extensão do arquivo.
        const ext = ((uri.split('?')[0]).match(/\.([a-z0-9]{2,5})$/i) || [])[1] || '';
        const MIME_BY_EXT = {
            jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp',
            gif: 'image/gif', mp4: 'video/mp4', mov: 'video/quicktime', webm: 'video/webm',
            ogg: 'audio/ogg', oga: 'audio/ogg', opus: 'audio/ogg', mp3: 'audio/mpeg',
            wav: 'audio/wav', m4a: 'audio/mp4', pdf: 'application/pdf',
        };
        mime = MIME_BY_EXT[ext.toLowerCase()] || '';
    }
    let el;

    const wantAudio = kind === 'audio' || kind === 'ptt' || mime.startsWith('audio/');
    const wantVideo = kind === 'video' || mime.startsWith('video/');
    const wantDoc = kind === 'document'
        || (mime && !mime.startsWith('image/') && !mime.startsWith('video/') && !mime.startsWith('audio/'));

    if (wantAudio) {
        el = document.createElement('div');
        el.className = 'msg-media-audio msg-media';
        _buildWaPlayer(el, uri);
        host.appendChild(el);
        return;
    } else if (wantVideo) {
        el = document.createElement('video');
        el.controls = true;
        el.preload = 'metadata';
        el.playsInline = true;
        el.className = 'msg-media-video msg-media';
    } else if (wantDoc) {
        el = document.createElement('a');
        el.className = 'msg-media-doc msg-media';
        el.target = '_blank';
        el.rel = 'noopener';
        el.textContent = 'Baixar anexo';
        el.href = uri;
        el.setAttribute('download', '');
        el.style.overflow = 'hidden';
        el.style.textOverflow = 'ellipsis';
        el.style.whiteSpace = 'nowrap';
    } else {
        el = document.createElement('img');
        el.alt = '';
        el.className = (kind === 'sticker') ? 'msg-sticker msg-media' : 'msg-media-img msg-media';
        el.loading = 'lazy';
    }

    if (el.tagName !== 'A') el.src = uri;

    if (el.tagName === 'IMG' || el.tagName === 'VIDEO') {
        el.style.cursor = 'pointer';
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            const fname = uri.startsWith('data:')
                ? ((uri.match(/^data:[^/]+\/([^;,]+)/) || [])[1] || 'midia')
                : decodeURIComponent(uri.split('/').pop().split('?')[0] || 'midia');
            openLightbox(uri, fname);
        });
    }

    host.appendChild(el);

    requestAnimationFrame(() => {
        const msgDiv = document.getElementById('chat-messages');
        if (msgDiv && isNearBottom(msgDiv)) scrollChatBottom();
    });
}

function _fallbackMsgMedia(box, body) {
    const spinner = box.querySelector('.spinner');
    if (spinner) spinner.remove();
    box.querySelector('.msg-media')?.remove?.();
    box.querySelector('.msg-media-host')?.remove?.();
    const text = String(body || '').trim();
    if (!text) {
        box.remove();
        return;
    }
    // Placeholder sem mídia disponível: chip estilizado em vez de texto cru.
    if (isMediaPlaceholder(text)) {
        box.innerHTML = `<div class="msg-media-unavailable">Mídia não disponível</div>`;
    } else {
        box.innerHTML = `<div class="msg-body">${esc(text)}</div>`;
    }
}

function renderInfoPanel(conv, contact, tags, allTags) {
    document.getElementById('info-panel').innerHTML = `
        <div style="font-size:13px">
            <div><strong>Nome:</strong> ${esc(contact?.name || '-')}</div>
            <div><strong>Telefone:</strong> ${esc(contact?.phone || '-')}</div>
            <div><strong>Email:</strong> ${esc(contact?.email || '-')}</div>
            <div><strong>Empresa:</strong> ${esc(contact?.company || '-')}</div>
            <div style="margin-top:8px;display:flex;align-items:center;gap:8px">
                <strong>Cor do avatar:</strong>
                <input type="color" value="${esc(contact?.avatar_color || '#6366f1')}"
                       onchange="updateContactAvatarColor(${conv.id}, ${contact?.id}, this.value)"
                       style="width:32px;height:28px;padding:1px;cursor:pointer;border:none;border-radius:4px;background:transparent">
                <span id="avatar-color-preview" style="width:24px;height:24px;border-radius:50%;background:${esc(contact?.avatar_color || '#6366f1')};display:inline-block;vertical-align:middle;border:2px solid var(--border)"></span>
            </div>
            <div style="margin-top:12px">
                <strong>Tags:</strong>
                <div class="tag-chips">
                    ${tags.length ? tags.map(t => `
                        <span class="tag-chip" style="background:${t.color}">
                            ${esc(t.name)}
                            <button class="tag-chip-remove" onclick="removeConvTag(${conv.id}, ${t.id})" title="Remover tag">&times;</button>
                        </span>
                    `).join('') : '<span class="muted">nenhuma</span>'}
                </div>
                ${allTags?.length ? `
                <div style="display:flex;gap:6px;margin-top:8px">
                    <select class="select-sm" id="conv-tag-select">
                        ${allTags.filter(t => !tags.some(tg => tg.id === t.id)).map(t =>
                            `<option value="${t.id}">${esc(t.name)}</option>`
                        ).join('') || '<option value="">Sem tags disponíveis</option>'}
                    </select>
                    <button class="btn-sm btn-secondary" onclick="addConvTag(${conv.id}, document.getElementById('conv-tag-select').value)">+</button>
                </div>` : ''}
            </div>
            <div><strong>Notas:</strong> <span class="muted">${esc(contact?.notes || '-')}</span></div>
            <div style="margin-top:16px">
                <strong>Status:</strong>
                <select class="select-sm" onchange="updateConvStatus(${conv.id}, this.value)">
                    ${['new','open','waiting','resolved','closed'].map(s =>
                        `<option value="${s}" ${conv.status===s?'selected':''}>${esc(statusLabel(s))}</option>`
                    ).join('')}
                </select>
            </div>
            <div style="margin-top:8px">
                <strong>Arquivada:</strong>
                <button class="btn-sm ${conv.archived ? 'btn-warning' : 'btn-secondary'}"
                        onclick="setConvFlag(${conv.id}, 'archived', ${conv.archived ? 0 : 1})">
                    ${conv.archived ? 'Desarquivar' : 'Arquivar'}
                </button>
            </div>
            <div style="margin-top:8px">
                <strong>Modo:</strong>
                <button class="btn-sm ${contact?.auto_mode ? 'btn-primary' : 'btn-secondary'}"
                        data-mode-toggle
                        onclick="toggleMode(${conv.id})">
                    ${contact?.auto_mode ? 'Agente Auto' : 'Humano'}
                </button>
            </div>
            ${conv.transferred_at ? `
            <div style="margin-top:8px">
                <strong>Transferido em:</strong> ${new Date(conv.transferred_at + 'Z').toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
            </div>
            ` : ''}
        </div>
    `;
}

async function updateContactAvatarColor(convId, contactId, color) {
    await api(`/api/contacts/${contactId}`, { method: 'PUT', body: JSON.stringify({ avatar_color: color }) });
    // Atualiza preview no painel
    const preview = document.getElementById('avatar-color-preview');
    if (preview) preview.style.background = color;
    // Atualiza avatar no header do chat
    const headerAvatar = document.querySelector('#chat-header .chat-header-avatar');
    if (headerAvatar) headerAvatar.style.background = color;
    // Atualiza avatar na lista de conversas
    const convItem = document.querySelector(`.conv-item[data-conv-id="${convId}"] .conv-avatar`);
    if (convItem) convItem.style.background = color;
    loadConversations();
}

async function updateConvStatus(convId, status) {
    const res = await api(`/api/conversations/${convId}/status`, { method: 'PUT', body: JSON.stringify({ status }) });
    if (!res || res.error) return;

    // Aplica localmente na lista
    const found = conversations.find(c => c.id === convId);
    if (found) found.status = status;

    // Atualiza o cabeçalho do chat imediatamente
    if (currentConvId === convId) {
        const header = document.querySelector('#chat-header span');
        if (header) {
            const name = header.textContent.replace(/\s*\([^)]*\)\s*$/, '');
            header.textContent = `${name} (${esc(statusLabel(status))})`;
        }
        // Atualiza painel de detalhes + lista sem reconstruir as mensagens (sem animação)
        refreshConversationPanel(convId);
    }
    loadConversations();
}

async function toggleMode(convId) {
    const btn = _btnFromEvent();
    setBtnLoading(btn, true);
    let res = null;
    try {
        res = await api(`/api/conversations/${convId}/mode`, { method: 'PUT' });
    } finally {
        setBtnLoading(btn, false);
    }
    if (!res || res.error) return;

    // Atualiza imediatamente o badge do cabeçalho do chat e o botão do painel
    const autoMode = res.auto_mode ? 'Auto' : 'Humano';
    const autoClass = res.auto_mode ? 'auto-on' : 'auto-off';

    const headerBadge = document.querySelector('#chat-header .auto-badge');
    if (headerBadge) {
        headerBadge.textContent = autoMode;
        headerBadge.className = `auto-badge ${autoClass}`;
    }

    // Troca o rótulo/estilo do botão no painel de informações sem refazer tudo
    const modeBtn = document.querySelector('#info-panel [data-mode-toggle]');
    if (modeBtn) {
        modeBtn.className = `btn-sm ${res.auto_mode ? 'btn-primary' : 'btn-secondary'}`;
        modeBtn.lastChild.textContent = res.auto_mode ? 'Agente Auto' : 'Humano';
    }

    // Auto-switch: navega para a view de destino e abre a conversa
    const targetView = res.auto_mode ? 'bot' : 'human-queue';
    if (currentView === targetView) {
        loadConversations();
        selectConversation(convId);
    } else {
        switchView(targetView);
        const _waitAndSelect = (tries = 0) => {
            if (conversations.some(c => c.id === convId) || tries > 10) {
                selectConversation(convId);
            } else {
                setTimeout(() => _waitAndSelect(tries + 1), 200);
            }
        };
        setTimeout(() => _waitAndSelect(), 600);
    }
}

async function addConvTag(convId, tagId) {
    if (!tagId) return;
    const btn = _btnFromEvent();
    setBtnLoading(btn, true);
    let res = null;
    try {
        res = await api(`/api/conversations/${convId}/tags`, { method: 'POST', body: JSON.stringify({ tag_id: Number(tagId) }) });
    } finally {
        setBtnLoading(btn, false);
    }
    if (res && !res.error) {
        toast('Tag adicionada', 'success');
        loadConversations();
        if (currentConvId === convId) refreshConversationPanel(convId);
    }
}

async function removeConvTag(convId, tagId) {
    const btn = _btnFromEvent();
    setBtnLoading(btn, true);
    let res = null;
    try {
        res = await api(`/api/conversations/${convId}/tags/${tagId}`, { method: 'DELETE' });
    } finally {
        setBtnLoading(btn, false);
    }
    if (res && !res.error) {
        toast('Tag removida', 'success');
        loadConversations();
        if (currentConvId === convId) refreshConversationPanel(convId);
    }
}

/* ── Templates quick ─────────────────────────────────────────────────── */
let templatesCache = [];

async function toggleTemplateMenu(e) {
    if (e) e.stopPropagation();
    const menu = document.getElementById('template-menu');
    if (!menu) return;
    const willOpen = menu.style.display !== 'flex';
    if (!willOpen) {
        menu.style.display = 'none';
        return;
    }

    templatesCache = await api('/api/templates') || [];
    if (templatesCache.length === 0) {
        toast('Nenhum template cadastrado. Crie em "Templates" no menu.', 'info');
        return;
    }

    menu.innerHTML = `
        <div class="template-menu-header">
            <span>Modelos de Resposta</span>
            <button type="button" class="template-menu-close" onclick="closeTemplateMenu(event)" title="Fechar">&times;</button>
        </div>
        <div class="template-menu-list">
            ${templatesCache.map((t, i) => `
                <div class="template-item" onclick="useTemplate(${i}, false)">
                    <div class="template-item-main">
                        <div class="template-item-title">${esc(t.title)}</div>
                        <div class="template-item-body">${esc(t.body)}</div>
                    </div>
                    <div class="template-item-actions">
                        <button type="button" class="template-send-btn" onclick="event.stopPropagation(); useTemplate(${i}, true)" title="Enviar mensagem agora">
                            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                            Enviar
                        </button>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
    menu.style.display = 'flex';
}

function closeTemplateMenu(e) {
    if (e) e.stopPropagation();
    const menu = document.getElementById('template-menu');
    if (menu) menu.style.display = 'none';
}

// Fechar menu de templates ao clicar fora
document.addEventListener('click', e => {
    const menu = document.getElementById('template-menu');
    const btn = document.getElementById('chat-template-btn');
    if (menu && menu.style.display === 'flex') {
        if (!menu.contains(e.target) && !btn?.contains(e.target)) {
            menu.style.display = 'none';
        }
    }
});

async function useTemplate(index, andSend = false) {
    const t = templatesCache[index];
    if (!t) return;
    const input = document.getElementById('chat-input');
    if (input) {
        input.value = t.body;
        autoResizeChatInput();
        input.focus();
        input.scrollTop = input.scrollHeight;
    }
    const menu = document.getElementById('template-menu');
    if (menu) menu.style.display = 'none';

    if (andSend) {
        toast(`Enviando modelo: "${t.title}"...`, 'info');
        await sendMessage();
    } else {
        toast(`Modelo "${t.title}" aplicado`, 'success');
    }
}

/* ── Chat input auto-resize & send ─────────────────────────────────────────── */
const chatInput = document.getElementById('chat-input');
if (chatInput) {
    chatInput.addEventListener('input', autoResizeChatInput);
}

function autoResizeChatInput() {
    const input = document.getElementById('chat-input');
    if (!input) return;
    input.style.height = 'auto';
    const minHeight = 42;
    const maxHeight = 140; // Limite estilo WhatsApp Web (~6 linhas)
    if (!input.value || input.value.trim() === '') {
        input.style.height = minHeight + 'px';
        input.style.overflowY = 'hidden';
    } else {
        const targetHeight = Math.min(input.scrollHeight, maxHeight);
        input.style.height = Math.max(minHeight, targetHeight) + 'px';
        input.style.overflowY = input.scrollHeight > maxHeight ? 'auto' : 'hidden';
    }
}

document.getElementById('chat-send').addEventListener('click', () => sendMessage());
document.getElementById('chat-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const btn = document.getElementById('chat-send');
    const text = input.value.trim();
    if (!text || !currentConvId) return;
    if (_sending) return;

    const conv = conversations.find(c => c.id === currentConvId);
    if (!conv) return;

    // ── Mensaje optimista: se muestra al instante con spinner de "enviando",
    //    sin esperar la respuesta del servidor (evita la sensación de "congelado").
    const tempId = 'temp-' + Date.now();
    appendMessage({
        id: tempId, direction: 'out', sender: 'Atendente',
        body: text, status: 'sending', msg_type: 'text',
        created_at: new Date().toISOString(), uazapi_id: '',
    });

    input.value = '';
    autoResizeChatInput();

    setBtnLoading(btn, true);
    _sending = true;
    lastSentBodyQueue.push(text);
    if (lastSentBodyQueue.length > 5) lastSentBodyQueue.shift();
    let res = null;
    try {
        res = await api('/api/messages/send', {
            method: 'POST',
            body: JSON.stringify({ phone: conv.contact_phone, body: text }),
        });
    } finally {
        setBtnLoading(btn, false);
        _sending = false;
    }

    if (!res || res.error) {
        lastSentBodyQueue = [];
        markTempMsgError(tempId);
        toast(friendlyError(res?.error), 'error');
        return;
    }

    toast('Mensagem enviada', 'success');
    // El evento SSE message_sent re-renderiza la conversa y reemplaza el temporal.
    // Como respaldo, si SSE no llega en ~3s, marcamos el temporal como enviado.
    setTimeout(() => markTempMsgSent(tempId), 1500);
}

function markTempMsgError(tempId) {
    const el = document.querySelector(`#chat-messages .msg[data-msg-id="${tempId}"]`);
    if (!el) return;
    el.setAttribute('data-status', 'error');
    const st = el.querySelector('.msg-status');
    if (st) { st.className = 'msg-status error'; st.textContent = '!'; st.title = 'Erro de envio'; }
    const spinner = el.querySelector('.spinner');
    if (spinner) spinner.remove();
}

function markTempMsgSent(tempId) {
    const el = document.querySelector(`#chat-messages .msg[data-msg-id="${tempId}"]`);
    if (!el) return;
    el.setAttribute('data-status', 'sent');
    const st = el.querySelector('.msg-status');
    if (st) { st.className = 'msg-status sent'; st.textContent = '✓✓'; st.title = 'Enviado'; }
    const spinner = el.querySelector('.spinner');
    if (spinner) spinner.remove();
}

/* ── Contacts ─────────────────────────────────────────────────────────────── */
async function loadContacts() {
    document.getElementById('contacts-list').innerHTML = skeletonRows(5);
    const contacts = await api('/api/contacts');
    if (!contacts) return;
    if (contacts.length === 0) {
        document.getElementById('contacts-list').innerHTML = '<div class="empty-state">Nenhum contato</div>';
        return;
    }
    document.getElementById('contacts-list').innerHTML = `
        <div class="contacts-bulk-bar" id="contacts-bulk-bar" style="display:none">
            <span id="contacts-selected-count">0 selecionados</span>
            <button class="btn-sm btn-danger" onclick="bulkDeleteContacts()">Excluir selecionados</button>
        </div>
        <table>
            <thead><tr>
                <th style="width:36px"><input type="checkbox" id="contacts-select-all" onchange="toggleAllContacts(this)"></th>
                <th>Telefone</th><th>Nome</th><th>Email</th><th>Modo</th><th>Ações</th>
            </tr></thead>
            <tbody>
            ${contacts.map(c => `
                <tr>
                    <td><input type="checkbox" class="contact-checkbox" value="${c.id}" onchange="updateBulkBar()"></td>
                    <td>${esc(c.phone)}</td>
                    <td>${esc(c.name || '-')}</td>
                    <td>${esc(c.email || '-')}</td>
                    <td><span class="auto-badge ${c.auto_mode ? 'auto-on' : 'auto-off'}">${c.auto_mode ? 'Auto' : 'Humano'}</span></td>
                    <td class="table-actions">
                        <button class="btn-sm btn-secondary" onclick="editContact(${c.id})">Editar</button>
                        <button class="btn-sm btn-danger" onclick="deleteContact(${c.id})">Excluir</button>
                    </td>
                </tr>
            `).join('')}
            </tbody>
        </table>`;
}

function toggleAllContacts(master) {
    document.querySelectorAll('.contact-checkbox').forEach(cb => cb.checked = master.checked);
    updateBulkBar();
}

function updateBulkBar() {
    const checked = document.querySelectorAll('.contact-checkbox:checked');
    const bar = document.getElementById('contacts-bulk-bar');
    const count = document.getElementById('contacts-selected-count');
    if (!bar || !count) return;
    if (checked.length > 0) {
        bar.style.display = 'flex';
        count.textContent = `${checked.length} selecionado${checked.length > 1 ? 's' : ''}`;
    } else {
        bar.style.display = 'none';
    }
}

async function bulkDeleteContacts() {
    const ids = [...document.querySelectorAll('.contact-checkbox:checked')].map(cb => Number(cb.value));
    if (!ids.length) return;
    if (!confirm(`Excluir ${ids.length} contato${ids.length > 1 ? 's' : ''}?`)) return;
    
    const bar = document.getElementById('contacts-bulk-bar');
    const btn = bar?.querySelector('.btn-danger');
    const countEl = document.getElementById('contacts-selected-count');
    if (btn) setBtnLoading(btn, true, 'Excluindo...');
    if (countEl) countEl.textContent = 'Excluindo...';
    
    let ok = 0, fail = 0;
    for (const id of ids) {
        try {
            const res = await api(`/api/contacts/${id}`, { method: 'DELETE' });
            if (res && !res.error) ok++; else fail++;
        } catch { fail++; }
    }
    
    if (ok) toast(`${ok} contato${ok > 1 ? 's' : ''} excluído${ok > 1 ? 's' : ''}`, 'success');
    if (fail) toast(`${fail} falha${fail > 1 ? 's' : ''}`, 'error');
    loadContacts();
}

function showContactForm(contact = null) {
    const title = contact ? 'Editar Contato' : 'Novo Contato';
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = `
        <form onsubmit="saveContact(event, ${contact?.id || 'null'})">
            <div class="form-group"><label>Telefone</label><input name="phone" value="${esc(contact?.phone || '')}" ${contact ? 'disabled' : ''} required></div>
            <div class="form-group"><label>Nome</label><input name="name" value="${esc(contact?.name || '')}"></div>
            <div class="form-group"><label>Email</label><input name="email" value="${esc(contact?.email || '')}"></div>
            <div class="form-group"><label>Empresa</label><input name="company" value="${esc(contact?.company || '')}"></div>
            <div class="form-group"><label>Cor do avatar</label><input type="color" name="avatar_color" value="${esc(contact?.avatar_color || '#6366f1')}"></div>
            <div class="form-group"><label>Notas</label><textarea name="notes" rows="3">${esc(contact?.notes || '')}</textarea></div>
            <button type="submit" class="btn-primary">Salvar</button>
        </form>`;
    document.getElementById('modal-overlay').style.display = 'flex';
}

async function saveContact(e, id) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const data = Object.fromEntries(new FormData(form));
    setBtnLoading(btn, true, 'Salvando...');
    if (id) {
        await api(`/api/contacts/${id}`, { method: 'PUT', body: JSON.stringify(data) });
        toast('Contato atualizado', 'success');
    } else {
        await api('/api/contacts', { method: 'POST', body: JSON.stringify(data) });
        toast('Contato criado', 'success');
    }
    setBtnLoading(btn, false);
    closeModal();
    loadContacts();
    // Atualiza o painel da conversa aberta com os dados novos do contato (sem reconstruir o chat)
    if (currentConvId) refreshConversationPanel(currentConvId);
}

async function editContact(id) {
    const data = await api(`/api/contacts/${id}`);
    if (data) showContactForm(data.contact);
}

async function deleteContact(id) {
    if (!confirm('Excluir este contato?')) return;
    await api(`/api/contacts/${id}`, { method: 'DELETE' });
    toast('Contato excluído', 'success');
    loadContacts();
}

/* ── Tags ─────────────────────────────────────────────────────────────────── */
// Reaplica as tags em toda a interface (lista de conversas + painel aberto),
// usado ao criar/atualizar/excluir tags ou receber atualização via SSE.
function refreshTagsUI() {
    loadConversations();
    if (currentConvId) refreshConversationPanel(currentConvId);
}

async function loadTags() {
    document.getElementById('tags-list').innerHTML = skeletonRows(4);
    const tags = await api('/api/tags');
    if (!tags) return;
    if (tags.length === 0) {
        document.getElementById('tags-list').innerHTML = '<div class="empty-state">Nenhuma tag</div>';
        return;
    }
    document.getElementById('tags-list').innerHTML = `
        <table>
            <thead>
                <tr>
                    <th style="width:80px">Cor</th>
                    <th>Nome</th>
                    <th style="width:180px;text-align:right">Ações</th>
                </tr>
            </thead>
            <tbody>
            ${tags.map(t => `
                <tr>
                    <td><span class="tag-color-dot" style="background:${t.color}"></span></td>
                    <td class="tag-name-cell">${esc(t.name)}</td>
                    <td class="table-actions" style="justify-content:flex-end">
                        <button class="btn-edit" onclick="editTag(${t.id},'${esc(t.name)}','${t.color}')">
                            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                            Editar
                        </button>
                        <button class="btn-delete" onclick="deleteTag(${t.id})">
                            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                            Excluir
                        </button>
                    </td>
                </tr>
            `).join('')}
            </tbody>
        </table>`;
}

function showTagForm(tag = null) {
    const title = tag ? 'Editar Tag' : 'Nova Tag';
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = `
        <form onsubmit="saveTag(event, ${tag?.id || 'null'})">
            <div class="form-group"><label>Nome</label><input name="name" value="${esc(tag?.name || '')}" required></div>
            <div class="form-group"><label>Cor</label><input type="color" name="color" value="${tag?.color || '#6366f1'}"></div>
            <button type="submit" class="btn-primary">Salvar</button>
        </form>`;
    requestAnimationFrame(() => {
        document.getElementById('modal-overlay').style.display = 'flex';
    });
}

async function saveTag(e, id) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const data = Object.fromEntries(new FormData(form));
    setBtnLoading(btn, true, 'Salvando...');
    if (id) {
        await api(`/api/tags/${id}`, { method: 'PUT', body: JSON.stringify(data) });
        toast('Tag atualizada', 'success');
    } else {
        await api('/api/tags', { method: 'POST', body: JSON.stringify(data) });
        toast('Tag criada', 'success');
    }
    setBtnLoading(btn, false);
    closeModal();
    loadTags();
    refreshTagsUI();
}

function editTag(id, name, color) { showTagForm({ id, name, color }); }

async function deleteTag(id) {
    if (!confirm('Excluir esta tag?')) return;
    await api(`/api/tags/${id}`, { method: 'DELETE' });
    toast('Tag excluída', 'success');
    loadTags();
    refreshTagsUI();
}

/* ── Templates ────────────────────────────────────────────────────────────── */
async function loadTemplates() {
    document.getElementById('templates-list').innerHTML = skeletonRows(4);
    const tpls = await api('/api/templates');
    if (!tpls) return;
    if (tpls.length === 0) {
        document.getElementById('templates-list').innerHTML = '<div class="empty-state">Nenhum template</div>';
        return;
    }
    document.getElementById('templates-list').innerHTML = `
        <table>
            <thead><tr><th>Título</th><th>Corpo</th><th>Ações</th></tr></thead>
            <tbody>
            ${tpls.map(t => `
                <tr>
                    <td>${esc(t.title)}</td>
                    <td style="max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.body)}</td>
                    <td class="table-actions">
                        <button class="btn-sm btn-secondary" onclick="editTemplate(${t.id})">Editar</button>
                        <button class="btn-sm btn-danger" onclick="deleteTemplate(${t.id})">Excluir</button>
                    </td>
                </tr>
            `).join('')}
            </tbody>
        </table>`;
}

function showTemplateForm(tpl = null) {
    const title = tpl ? 'Editar Template' : 'Novo Template';
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = `
        <form onsubmit="saveTemplate(event, ${tpl?.id || 'null'})">
            <div class="form-group"><label>Título</label><input name="title" value="${esc(tpl?.title || '')}" required></div>
            <div class="form-group"><label>Corpo</label><textarea name="body" rows="5" required>${esc(tpl?.body || '')}</textarea></div>
            <button type="submit" class="btn-primary">Salvar</button>
        </form>`;
    requestAnimationFrame(() => {
        document.getElementById('modal-overlay').style.display = 'flex';
    });
}

async function saveTemplate(e, id) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const data = Object.fromEntries(new FormData(form));
    setBtnLoading(btn, true, 'Salvando...');
    if (id) {
        await api(`/api/templates/${id}`, { method: 'PUT', body: JSON.stringify(data) });
        toast('Template atualizado', 'success');
    } else {
        await api('/api/templates', { method: 'POST', body: JSON.stringify(data) });
        toast('Template criado', 'success');
    }
    setBtnLoading(btn, false);
    closeModal();
    loadTemplates();
}

async function editTemplate(id) {
    const tpls = await api('/api/templates');
    const tpl = tpls?.find(t => t.id === id);
    if (tpl) showTemplateForm(tpl);
}

async function deleteTemplate(id) {
    if (!confirm('Excluir este template?')) return;
    await api(`/api/templates/${id}`, { method: 'DELETE' });
    toast('Template excluído', 'success');
    loadTemplates();
}

/* ── Knowledge ────────────────────────────────────────────────────────────── */
let currentKnowledgeFile = null;

function deselectKnowledgeFile() {
    currentKnowledgeFile = null;
    document.querySelectorAll('.knowledge-file').forEach(el => el.classList.remove('active'));
    document.getElementById('knowledge-editor-header').innerHTML = '<span>Selecione um arquivo</span>';
    const editor = document.getElementById('knowledge-editor');
    if (editor) {
        editor.value = '';
        delete editor.dataset.filename;
        delete editor.dataset.isPrompt;
    }
    const descBar = document.querySelector('.knowledge-desc-bar');
    if (descBar) descBar.style.display = '';
    document.getElementById('knowledge-description').value = '';
    document.getElementById('knowledge-actions').style.display = 'none';
    const deleteBtn = document.getElementById('knowledge-delete-btn');
    if (deleteBtn) deleteBtn.style.display = 'none';
    // Desmarca prompts tambem
    document.querySelectorAll('.knowledge-prompt-item').forEach(el => el.classList.remove('active'));
}

async function loadKnowledge() {
    document.getElementById('knowledge-list').innerHTML = skeletonRows(4);
    const files = await api('/api/knowledge');
    if (!files) return;
    const list = document.getElementById('knowledge-list');
    if (files.length === 0) {
        list.innerHTML = '<div class="empty-state">Nenhum arquivo</div>';
    } else {
        list.innerHTML = files.map(f => {
            const status = f.status || 'indexed';
            return `
            <div class="knowledge-file ${f.filename === currentKnowledgeFile ? 'active' : ''}" onclick="selectKnowledgeFile('${esc(f.filename)}')">
                <div class="knowledge-file-info">
                    <div class="knowledge-file-name">${esc(f.filename)}</div>
                    <div class="knowledge-file-meta">
                        <span class="knowledge-file-size">${f.chunks} chunks</span>
                        <span class="knowledge-status-badge ${status}">${status === 'pending' ? 'Pendente' : status === 'indexed' ? 'Indexado' : 'Erro'}</span>
                    </div>
                </div>
                <button class="btn-icon btn-danger" onclick="event.stopPropagation();deleteKnowledge('${esc(f.filename)}')" title="Deletar">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
            </div>
        `}).join('');
    }
    loadKnowledgePrompts();
}

/* ── Prompt da Secretária ───────────────────────────────────────────────── */
async function loadKnowledgePrompts() {
    const list = document.getElementById('knowledge-prompts-list');
    if (!list) return;
    list.innerHTML = skeletonRows(1);
    const p = await api('/api/knowledge/prompt');
    if (!p || p.error) { list.innerHTML = ''; return; }
    list.innerHTML = `
        <div class="knowledge-prompt-item" onclick="selectKnowledgePrompt()">
            <div class="knowledge-prompt-info">
                <div class="knowledge-prompt-agent">Secretária</div>
                <div class="knowledge-prompt-meta">
                    <span class="knowledge-prompt-source disk">${esc(p.filename)}</span>
                    <span class="knowledge-prompt-chars">${(p.content || '').length} chars</span>
                </div>
            </div>
        </div>`;
}

async function selectKnowledgePrompt() {
    const editor = document.getElementById('knowledge-editor');
    const header = document.getElementById('knowledge-editor-header');
    const actions = document.getElementById('knowledge-actions');
    const descBar = document.querySelector('.knowledge-desc-bar');
    const deleteBtn = document.getElementById('knowledge-delete-btn');
    if (!editor) return;
    const data = await api('/api/knowledge/prompt');
    if (!data || data.error) return;
    editor.value = data.content || '';
    editor.dataset.filename = data.filename;
    editor.dataset.isPrompt = 'true';
    header.innerHTML = `<span>Prompt da secretária (${esc(data.filename)})</span>`;
    if (descBar) descBar.style.display = 'none';
    if (deleteBtn) deleteBtn.style.display = 'none';
    if (actions) actions.style.display = 'flex';
    editor.focus();
}

async function saveKnowledgePrompt() {
    const editor = document.getElementById('knowledge-editor');
    if (!editor) return;
    const res = await api('/api/knowledge/prompt', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editor.value })
    });
    if (res && res.ok) {
        showToast('Prompt salvo e recarregado', 'success');
        loadKnowledgePrompts();
    } else {
        showToast('Erro ao salvar prompt', 'error');
    }
}

async function reloadAgentPrompts() {
    const btn = document.getElementById('reload-prompts-btn');
    const icon = btn ? btn.querySelector('.reload-icon') : null;
    if (icon) icon.classList.add('spinning');
    if (btn) btn.disabled = true;
    const res = await api('/api/knowledge/reload', { method: 'POST' });
    if (icon) icon.classList.remove('spinning');
    if (btn) btn.disabled = false;
    if (res && res.ok) {
        showToast('Prompt recarregado', 'success');
        loadKnowledgePrompts();
    }
}

/* ── Knowledge Dropdown ─────────────────────────────────────────────────── */
function toggleKnowledgeDropdown(e) {
    e.stopPropagation();
    const wrapper = document.querySelector('.knowledge-actions-wrapper');
    wrapper.classList.toggle('open');
}

function handleKnowledgeNew(e) {
    e.stopPropagation();
    closeKnowledgeDropdown();
    showKnowledgeForm();
}

function handleKnowledgeImport(e) {
    e.stopPropagation();
    closeKnowledgeDropdown();
    document.getElementById('knowledge-import-input').click();
}

function closeKnowledgeDropdown() {
    const wrapper = document.querySelector('.knowledge-actions-wrapper');
    if (wrapper) {
        wrapper.classList.add('closing');
        wrapper.classList.remove('open');
        setTimeout(() => wrapper.classList.remove('closing'), 50);
    }
}

document.addEventListener('click', (e) => {
    const wrapper = document.querySelector('.knowledge-actions-wrapper');
    if (wrapper && !wrapper.contains(e.target)) {
        wrapper.classList.remove('open');
    }
});

/* ── Sidebar Toggle (Mobile) ────────────────────────────────────────────── */
function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    const isOpen = sidebar.classList.contains('open');
    if (isOpen) {
        sidebar.classList.remove('open');
        overlay.classList.remove('visible');
    } else {
        sidebar.classList.add('open');
        overlay.classList.add('visible');
    }
}

function closeSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    sidebar.classList.remove('open');
    overlay.classList.remove('visible');
}

/* ── Chat Mobile ────────────────────────────────────────────────────────── */
function openChatMobile() {
    const layout = document.querySelector('.conv-layout');
    if (layout) layout.classList.add('chat-open');
}

let _infoPanelHidden = true;

function toggleInfoPanel() {
    const panel = document.getElementById('conv-info-panel');
    const showBtn = document.getElementById('info-panel-show-btn');
    if (!panel) return;

    _infoPanelHidden = !_infoPanelHidden;

    if (_infoPanelHidden) {
        panel.classList.add('hidden');
        if (showBtn) showBtn.classList.add('visible');
    } else {
        panel.classList.remove('hidden');
        if (showBtn) showBtn.classList.remove('visible');
    }
}

function showInfoPanel() {
    const panel = document.getElementById('conv-info-panel');
    const showBtn = document.getElementById('info-panel-show-btn');
    if (panel) panel.classList.remove('hidden');
    if (showBtn) showBtn.classList.remove('visible');
    _infoPanelHidden = false;
}

function closeChatMobile() {
    const layout = document.querySelector('.conv-layout');
    if (layout) layout.classList.remove('chat-open');
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (_xlsxFullscreen) {
            toggleXlsxFullscreen();
            return;
        }
        closeSidebar();
        closeChatMobile();
    }
});

async function selectKnowledgeFile(filename) {
    currentKnowledgeFile = filename;
    document.querySelectorAll('.knowledge-file').forEach(el => el.classList.remove('active'));
    event.currentTarget?.classList.add('active');

    document.getElementById('knowledge-editor-header').innerHTML = `<span>${esc(filename)}</span>
                            <button class="btn-icon btn-danger" id="knowledge-delete-btn" onclick="deleteKnowledge(currentKnowledgeFile)" title="Deletar arquivo">
                                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                            </button>`;
    document.getElementById('knowledge-editor').value = 'Carregando...';
    document.getElementById('knowledge-description').value = '';
    document.getElementById('knowledge-actions').style.display = 'flex';

    // Verifica se é um arquivo xlsx
    const isXlsx = filename.toLowerCase().endsWith('.xlsx');
    
    // Se for xlsx, busca dados estruturados
    if (isXlsx) {
        const xlsxData = await api(`/api/knowledge/${encodeURIComponent(filename)}/xlsx-data`);
        const regularData = await api(`/api/knowledge/${encodeURIComponent(filename)}`);
        
        if (!regularData || regularData.error) {
            document.getElementById('knowledge-editor').value = '';
            toast(regularData?.error || 'Erro ao carregar', 'error');
            return;
        }
        
        document.getElementById('knowledge-description').value = regularData.description || '';
        
        // Renderiza visualização xlsx
        renderXlsxPreview(filename, xlsxData);
        return;
    }

    const data = await api(`/api/knowledge/${encodeURIComponent(filename)}`);
    if (!data || data.error) {
        document.getElementById('knowledge-editor').value = '';
        toast(data?.error || 'Erro ao carregar', 'error');
        return;
    }
    document.getElementById('knowledge-editor').value = data.content;
    document.getElementById('knowledge-description').value = data.description || '';
    
    // Remove preview xlsx se existir
    const existingPreview = document.querySelector('.knowledge-xlsx-preview');
    if (existingPreview) existingPreview.remove();
    
    // Mostra editor de texto
    document.getElementById('knowledge-editor').style.display = 'block';
}

// Estado de paginação do xlsx
let _xlsxPageState = {};
let _xlsxFullscreen = false;

// Renderiza visualização de planilha xlsx
function renderXlsxPreview(filename, xlsxData) {
    // Remove preview anterior
    const existingPreview = document.querySelector('.knowledge-xlsx-preview');
    if (existingPreview) existingPreview.remove();
    
    // Esconde editor de texto
    document.getElementById('knowledge-editor').style.display = 'none';
    
    const editorPanel = document.querySelector('.knowledge-editor-panel');
    if (!editorPanel) return;
    
    if (!xlsxData || !xlsxData.sheets || xlsxData.sheets.length === 0) {
        const preview = document.createElement('div');
        preview.className = 'knowledge-xlsx-preview';
        preview.innerHTML = `
            <div class="knowledge-xlsx-header">
                <h4>Visualizacao da Planilha</h4>
            </div>
            <div class="knowledge-xlsx-empty">
                Nao foi possivel carregar a visualizacao da planilha.
                <br>O conteudo esta disponivel no editor de texto.
            </div>
        `;
        editorPanel.insertBefore(preview, document.getElementById('knowledge-actions'));
        document.getElementById('knowledge-editor').style.display = 'block';
        return;
    }
    
    // Inicializa paginação
    _xlsxPageState = { currentSheet: 0, pages: {} };
    xlsxData.sheets.forEach((sheet, i) => {
        _xlsxPageState.pages[i] = { page: 0, perPage: 50 };
    });
    
    const preview = document.createElement('div');
    preview.className = 'knowledge-xlsx-preview';
    
    // Tabs para múltiplas abas
    let tabsHtml = '';
    if (xlsxData.sheets.length > 1) {
        tabsHtml = `<div class="knowledge-xlsx-tabs">
            ${xlsxData.sheets.map((sheet, i) => 
                `<button class="knowledge-xlsx-tab ${i === 0 ? 'active' : ''}" onclick="switchXlsxSheet(${i})" data-sheet-index="${i}">${esc(sheet.name)}</button>`
            ).join('')}
        </div>`;
    }
    
    // Renderiza primeira aba
    const firstSheet = xlsxData.sheets[0];
    let tableHtml = renderXlsxSheetTable(firstSheet, 0);
    
    preview.innerHTML = `
        <div class="knowledge-xlsx-header">
            <div class="knowledge-xlsx-header-left">
                <h4>Visualizacao da Planilha</h4>
                ${tabsHtml}
                <span class="knowledge-xlsx-info">${firstSheet.rowCount || 0} linhas x ${firstSheet.colCount || 0} colunas</span>
            </div>
            <div class="knowledge-xlsx-header-right">
                <button class="btn-icon knowledge-xlsx-fullscreen-btn" onclick="toggleXlsxFullscreen()" title="Tela cheia">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
                    </svg>
                </button>
            </div>
        </div>
        ${tableHtml}
    `;
    
    preview.dataset.xlsxData = JSON.stringify(xlsxData);
    editorPanel.insertBefore(preview, document.getElementById('knowledge-actions'));
}

// Alterna modo tela cheia
function toggleXlsxFullscreen() {
    const preview = document.querySelector('.knowledge-xlsx-preview');
    if (!preview) return;
    
    _xlsxFullscreen = !_xlsxFullscreen;
    preview.classList.toggle('knowledge-xlsx-fullscreen', _xlsxFullscreen);
    document.body.classList.toggle('knowledge-xlsx-fullscreen-body', _xlsxFullscreen);
    
    const btn = preview.querySelector('.knowledge-xlsx-fullscreen-btn');
    if (btn) {
        btn.innerHTML = _xlsxFullscreen
            ? '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 14h6v6m10-10h-6V4m0 6l7-7M3 21l7-7"/></svg>'
            : '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>';
        btn.title = _xlsxFullscreen ? 'Sair da tela cheia' : 'Tela cheia';
    }
}

// Renderiza tabela de uma aba com paginação
function renderXlsxSheetTable(sheet, sheetIndex) {
    if (!sheet.headers && !sheet.data) return '';
    
    // Fallback: dados em texto - tenta parsear em tabela
    if (sheet.data && !sheet.headers) {
        const lines = sheet.data.split('\n').filter(l => l.trim());
        if (lines.length > 2) {
            // Tenta detectar separador (tab ou 2+ espacos)
            const firstDataLine = lines.find(l => !l.trim().startsWith('===')) || lines[0];
            const hasTab = firstDataLine.includes('\t');
            const separator = hasTab ? /\t/ : /\s{2,}/;
            
            // Primeira linha nao-vazia que nao comeca com === vira header
            let headerIdx = 0;
            for (let i = 0; i < lines.length; i++) {
                if (!lines[i].trim().startsWith('===')) {
                    headerIdx = i;
                    break;
                }
            }
            
            const headers = lines[headerIdx].split(separator).map(h => h.trim()).filter(Boolean);
            const dataLines = lines.slice(headerIdx + 1).filter(l => !l.trim().startsWith('==='));
            const rows = dataLines.map(line => {
                const cells = line.split(separator).map(c => c.trim());
                // Preenche celulas faltantes
                while (cells.length < headers.length) cells.push('');
                return cells.slice(0, headers.length);
            }).filter(row => row.some(c => c !== ''));
            
            if (headers.length > 0 && rows.length > 0) {
                // Forca como sheet com headers/rows para usar a renderizacao normal
                sheet = { ...sheet, headers, rows, rowCount: rows.length, colCount: headers.length };
            }
        }
    }
    
    if (!sheet.headers) return '';
    
    // Se headers sao genericos (Col_1, Col_2...) e tem dados, tenta usar a primeira linha como header
    let headers = sheet.headers || [];
    let allRows = sheet.rows || [];
    
    if (headers.length > 0 && /^col_?\d+$/i.test(headers[0]) && allRows.length > 0) {
        const firstRow = allRows[0];
        if (firstRow && firstRow.length === headers.length) {
            const looksLikeHeader = firstRow.every(cell => {
                const s = String(cell || '').trim();
                return s !== '' && isNaN(s.replace(',', '.'));
            });
            if (looksLikeHeader) {
                headers = firstRow.map(h => String(h || '').trim() || '-');
                allRows = allRows.slice(1);
            }
        }
    }
    
    const pageState = _xlsxPageState.pages[sheetIndex] || { page: 0, perPage: 50 };
    const totalRows = allRows.length;
    const perPage = pageState.perPage;
    const totalPages = Math.ceil(totalRows / perPage);
    const currentPage = Math.min(pageState.page, totalPages - 1);
    const startIdx = currentPage * perPage;
    const endIdx = Math.min(startIdx + perPage, totalRows);
    const displayRows = allRows.slice(startIdx, endIdx);
    
    let paginationHtml = '';
    if (totalPages > 1) {
        paginationHtml = `
            <div class="knowledge-xlsx-pagination">
                <button class="knowledge-xlsx-page-btn" onclick="xlsxGoPage(${sheetIndex}, 0)" ${currentPage === 0 ? 'disabled' : ''}>&laquo;</button>
                <button class="knowledge-xlsx-page-btn" onclick="xlsxGoPage(${sheetIndex}, ${currentPage - 1})" ${currentPage === 0 ? 'disabled' : ''}>&lsaquo;</button>
                <span class="knowledge-xlsx-page-info">Pagina ${currentPage + 1} de ${totalPages}</span>
                <button class="knowledge-xlsx-page-btn" onclick="xlsxGoPage(${sheetIndex}, ${currentPage + 1})" ${currentPage >= totalPages - 1 ? 'disabled' : ''}>&rsaquo;</button>
                <button class="knowledge-xlsx-page-btn" onclick="xlsxGoPage(${sheetIndex}, ${totalPages - 1})" ${currentPage >= totalPages - 1 ? 'disabled' : ''}>&raquo;</button>
                <span class="knowledge-xlsx-page-count">${totalRows} linhas total</span>
            </div>
        `;
    }
    
    return `
        <div class="knowledge-xlsx-container">
            <table class="knowledge-xlsx-table">
                <thead>
                    <tr>
                        <th class="knowledge-xlsx-row-num">#</th>
                        ${headers.map(h => `<th>${esc(h)}</th>`).join('')}
                    </tr>
                </thead>
                <tbody>
                    ${displayRows.length === 0 ? `<tr><td colspan="${headers.length + 1}" class="knowledge-xlsx-empty-row">Nenhum dado</td></tr>` : ''}
                    ${displayRows.map((row, i) => {
                        return `<tr>
                            <td class="knowledge-xlsx-row-num">${startIdx + i + 1}</td>
                            ${row.map((cell, ci) => {
                                const val = String(cell || '').trim();
                                const display = val === '' ? '' : esc(val);
                                return `<td contenteditable="true" data-row="${startIdx + i}" data-col="${ci}" class="knowledge-xlsx-cell" title="${esc(val)}">${display}</td>`;
                            }).join('')}
                        </tr>`;
                    }).join('')}
                </tbody>
            </table>
        </div>
        ${paginationHtml}
    `;
}

// Navega para uma pagina especifica
function xlsxGoPage(sheetIndex, page) {
    const preview = document.querySelector('.knowledge-xlsx-preview');
    if (!preview) return;
    const xlsxData = JSON.parse(preview.dataset.xlsxData || '{}');
    if (!xlsxData.sheets || !xlsxData.sheets[sheetIndex]) return;
    
    // Preserva edits da pagina atual antes de navegar
    _preserveCurrentSheetEdits();
    
    const totalPages = Math.ceil((xlsxData.sheets[sheetIndex].rows || []).length / 50);
    page = Math.max(0, Math.min(page, totalPages - 1));
    _xlsxPageState.pages[sheetIndex].page = page;
    
    const sheet = xlsxData.sheets[sheetIndex];
    const container = preview.querySelector('.knowledge-xlsx-container');
    const pagination = preview.querySelector('.knowledge-xlsx-pagination');
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = renderXlsxSheetTable(sheet, sheetIndex);
    
    const newContainer = tempDiv.querySelector('.knowledge-xlsx-container');
    const newPagination = tempDiv.querySelector('.knowledge-xlsx-pagination');
    if (newContainer && container) container.replaceWith(newContainer);
    if (newPagination && pagination) pagination.replaceWith(newPagination);
    else if (newPagination && !pagination) preview.appendChild(newPagination);
}

// Troca aba da planilha xlsx
function switchXlsxSheet(sheetIndex) {
    // Preserva edits da aba atual antes de trocar
    _preserveCurrentSheetEdits();
    
    _xlsxPageState.currentSheet = sheetIndex;
    _xlsxPageState.pages[sheetIndex].page = 0;
    
    const preview = document.querySelector('.knowledge-xlsx-preview');
    if (!preview) return;
    
    const xlsxData = JSON.parse(preview.dataset.xlsxData || '{}');
    if (!xlsxData.sheets || !xlsxData.sheets[sheetIndex]) return;
    
    // Atualiza tabs
    preview.querySelectorAll('.knowledge-xlsx-tab').forEach((tab, i) => {
        tab.classList.toggle('active', i === sheetIndex);
    });
    
    const sheet = xlsxData.sheets[sheetIndex];
    const tableHtml = renderXlsxSheetTable(sheet, sheetIndex);
    
    // Remove container e pagination antigos
    const oldContainer = preview.querySelector('.knowledge-xlsx-container');
    const oldPagination = preview.querySelector('.knowledge-xlsx-pagination');
    if (oldContainer) oldContainer.remove();
    if (oldPagination) oldPagination.remove();
    
    // Atualiza info
    const header = preview.querySelector('.knowledge-xlsx-header');
    const infoSpan = header.querySelector('.knowledge-xlsx-info');
    if (infoSpan) {
        infoSpan.textContent = `${sheet.rowCount || 0} linhas x ${sheet.colCount || 0} colunas`;
    }
    
    // Insere novo conteudo
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = tableHtml;
    const newContainer = tempDiv.querySelector('.knowledge-xlsx-container');
    const newPagination = tempDiv.querySelector('.knowledge-xlsx-pagination');
    if (newContainer) preview.appendChild(newContainer);
    if (newPagination) preview.appendChild(newPagination);
}

// Preserva edicoes da aba atual no xlsxData antes de trocar de aba
function _preserveCurrentSheetEdits() {
    const preview = document.querySelector('.knowledge-xlsx-preview');
    if (!preview) return;
    const xlsxData = JSON.parse(preview.dataset.xlsxData || '{}');
    if (!xlsxData.sheets) return;
    
    const cells = preview.querySelectorAll('.knowledge-xlsx-cell[data-row]');
    cells.forEach(cell => {
        const rowIdx = parseInt(cell.dataset.row);
        const colIdx = parseInt(cell.dataset.col);
        const sheetIdx = _xlsxPageState.currentSheet;
        const sheet = xlsxData.sheets[sheetIdx];
        if (sheet && sheet.rows && rowIdx >= 0 && rowIdx < sheet.rows.length && colIdx >= 0 && colIdx < sheet.headers.length) {
            sheet.rows[rowIdx][colIdx] = cell.textContent.trim();
        }
    });
    
    // Salva de volta no dataset
    preview.dataset.xlsxData = JSON.stringify(xlsxData);
}

// Coleta dados editados da planilha.
//
// So a aba VISIVEL tem celulas no DOM. Antes, o laco sobre essas celulas rodava
// dentro do map de todas as abas, entao os valores da aba aberta eram gravados
// por indice em cima das outras: editar uma aba e salvar sobrescrevia as
// demais. Agora a consolidacao da aba
// atual fica a cargo de _preserveCurrentSheetEdits() e as demais abas saem do
// xlsxData intactas.
function collectXlsxEdits() {
    _preserveCurrentSheetEdits();

    const preview = document.querySelector('.knowledge-xlsx-preview');
    if (!preview) return null;
    const xlsxData = JSON.parse(preview.dataset.xlsxData || '{}');
    if (!xlsxData.sheets) return null;

    const editedSheets = xlsxData.sheets.map(sheet => ({
        name: sheet.name,
        headers: sheet.headers || [],
        rows: (sheet.rows || []).map(r => [...r]),
    }));

    return { sheets: editedSheets };
}

async function saveKnowledge() {
    const editor = document.getElementById('knowledge-editor');
    // Se estamos editando o prompt da secretaria
    if (editor && editor.dataset.isPrompt === 'true') {
        return saveKnowledgePrompt();
    }
    if (!currentKnowledgeFile) return;
    const btn = event.currentTarget;
    const description = document.getElementById('knowledge-description').value;
    setBtnLoading(btn, true, 'Salvando...');
    
    const isXlsx = currentKnowledgeFile.toLowerCase().endsWith('.xlsx');
    
    if (isXlsx) {
        // Salva dados estruturados da planilha
        const editedData = collectXlsxEdits();
        if (!editedData) {
            setBtnLoading(btn, false);
            toast('Erro ao coletar dados da planilha', 'error');
            return;
        }
        
        const data = await api(`/api/knowledge/${encodeURIComponent(currentKnowledgeFile)}/xlsx-data`, {
            method: 'PUT',
            body: JSON.stringify({ sheets: editedData.sheets, description })
        });
        setBtnLoading(btn, false);
        if (data?.error) {
            toast(friendlyError(data.error), 'error');
        } else {
            toast('Planilha salva com sucesso!', 'success');
            loadKnowledge();
        }
    } else {
        // Salva texto normal
        const content = document.getElementById('knowledge-editor').value;
        const data = await api(`/api/knowledge/${encodeURIComponent(currentKnowledgeFile)}`, {
            method: 'PUT',
            body: JSON.stringify({ content, description })
        });
        setBtnLoading(btn, false);
        if (data?.error) {
            toast(friendlyError(data.error), 'error');
        } else {
            toast(data?.unchanged
                ? 'Salvo - o texto não mudou, continua indexado'
                : 'Knowledge salvo (pendente de embedding)', 'success');
            loadKnowledge();
        }
    }
}

function showKnowledgeForm(prefill = {}) {
    document.getElementById('modal-title').textContent = 'Novo Arquivo Knowledge';
    document.getElementById('modal-body').innerHTML = `
        <form onsubmit="createKnowledge(event)">
            <div class="form-group"><label>Nome do arquivo</label><input name="filename" value="${esc(prefill.filename || '')}" placeholder="ex: 04-horarios.md" required></div>
            <div class="form-group"><label>Descricao (para o agente saber quando usar)</label><input name="description" value="${esc(prefill.description || '')}" placeholder="ex: Horario de funcionamento e entregas"></div>
            <div class="form-group"><label>Conteudo</label><textarea name="content" rows="10" required>${esc(prefill.content || '')}</textarea></div>
            <button type="submit" class="btn-primary">Criar</button>
        </form>`;
    requestAnimationFrame(() => {
        document.getElementById('modal-overlay').style.display = 'flex';
    });
}

async function importKnowledgeFile(event) {
    const input = event.target;
    const file = input.files && input.files[0];
    input.value = ''; // permite re-importar o mesmo arquivo
    if (!file) return;
    const lower = (file.name || '').toLowerCase();
    const isBinary = lower.endsWith('.docx') || lower.endsWith('.xlsx');
    if (!lower.endsWith('.md') && !lower.endsWith('.txt') && !isBinary) {
        toast('So sao permitidos arquivos .md, .txt, .docx ou .xlsx', 'error');
        return;
    }
    if (isBinary) {
        // .docx/.xlsx: envia direto ao server para parse
        const formData = new FormData();
        formData.append('files', file);
        toast('Enviando arquivo...', 'info');
        try {
            const res = await fetch('/api/knowledge/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.saved && data.saved.length > 0) {
                toast(`${data.saved.length} arquivo(s) salvo(s) como pendente`, 'success');
                loadKnowledge();
                selectKnowledgeFile(data.saved[0]);
            }
            if (data.errors && data.errors.length > 0) {
                data.errors.forEach(err => toast(`${err.filename}: ${err.error}`, 'error'));
            }
        } catch (e) {
            toast('Erro ao enviar arquivo', 'error');
        }
        return;
    }
    try {
        const content = await file.text();
        // Abre el modal pre-rellenado para revisar / añadir descripcion antes de indexar
        showKnowledgeForm({ filename: file.name, content: content });
        toast('Arquivo cargado, revisa y pulsa Criar', 'info');
    } catch (e) {
        toast('Erro ao ler o arquivo', 'error');
    }
}

async function createKnowledge(e) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const data = Object.fromEntries(new FormData(form));
    setBtnLoading(btn, true, 'Criando...');
    const res = await api('/api/knowledge', { method: 'POST', body: JSON.stringify(data) });
    setBtnLoading(btn, false);
    if (res?.error) {
        toast(friendlyError(res.error), 'error');
    } else {
        toast('Arquivo criado (pendente de embedding)', 'success');
        closeModal();
        currentKnowledgeFile = data.filename;
        loadKnowledge();
        selectKnowledgeFile(data.filename);
    }
}

async function deleteKnowledge(filename) {
    if (!confirm(`Deletar "${filename}"? Essa ação não pode ser desfeita.`)) return;
    const res = await api(`/api/knowledge/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    if (res?.error) {
        toast(friendlyError(res.error), 'error');
    } else {
        toast('Arquivo deletado', 'success');
        if (currentKnowledgeFile === filename) {
            currentKnowledgeFile = null;
            document.getElementById('knowledge-editor').value = '';
            document.getElementById('knowledge-editor-header').innerHTML = '<span>Selecione um arquivo</span>';
            document.getElementById('knowledge-actions').style.display = 'none';
        }
        loadKnowledge();
    }
}

/* ── Knowledge Multi-Upload ─────────────────────────────────────────────── */
function handleKnowledgeImportMultiple(e) {
    e.stopPropagation();
    closeKnowledgeDropdown();
    document.getElementById('knowledge-import-multi-input').click();
}

async function importKnowledgeMultiple(event) {
    const input = event.target;
    const files = input.files;
    input.value = '';
    if (!files || files.length === 0) return;

    const formData = new FormData();
    let validCount = 0;
    for (const file of files) {
        const lower = (file.name || '').toLowerCase();
        if (!lower.endsWith('.md') && !lower.endsWith('.txt') && !lower.endsWith('.docx') && !lower.endsWith('.xlsx')) {
            toast(`Arquivo ignorado: ${file.name} (so .md, .txt, .docx, .xlsx)`, 'error');
            continue;
        }
        formData.append('files', file);
        validCount++;
    }

    if (validCount === 0) {
        toast('Nenhum arquivo válido selecionado', 'error');
        return;
    }

    toast(`Enviando ${validCount} arquivo(s)...`, 'info');

    try {
        const res = await fetch('/api/knowledge/upload', {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();

        if (data.saved && data.saved.length > 0) {
            toast(`${data.saved.length} arquivo(s) salvo(s) como pendente`, 'success');
        }
        if (data.errors && data.errors.length > 0) {
            data.errors.forEach(err => {
                toast(`${err.filename}: ${err.error}`, 'error');
            });
        }
        loadKnowledge();
    } catch (e) {
        toast('Erro ao enviar arquivos', 'error');
    }
}

/* ── Knowledge Embed All ─────────────────────────────────────────────── */
async function handleEmbedAll(e) {
    e.stopPropagation();
    closeKnowledgeDropdown();

    const toastId = toastLoading('Gerando embeddings para arquivos pendentes...');

    const res = await api('/api/knowledge/embed-all', { method: 'POST' });
    if (res?.error) {
        toastDone(toastId, friendlyError(res.error), 'error');
    } else {
        const msg = res.processed > 0
            ? `${res.processed} arquivo(s) indexado(s)`
            : 'Nenhum arquivo pendente para indexar';
        if (res.errors > 0) {
            toastDone(toastId, `${msg} (${res.errors} erro(s))`, 'warning');
        } else {
            toastDone(toastId, msg, 'success');
        }
        loadKnowledge();
    }
}

/* ── Knowledge Reload Prompt ─────────────────────────────────────── */
async function handleReloadPrompt(e) {
    e.stopPropagation();
    closeKnowledgeDropdown();

    const toastId = toastLoading('Recarregando system prompt...');

    const res = await api('/api/knowledge/reload', { method: 'POST' });
    if (res?.error) {
        toastDone(toastId, friendlyError(res.error), 'error');
    } else {
        toastDone(toastId, `Prompt recarregado (${res.prompt_chars} chars)`, 'success');
    }
}

/* ── Knowledge Clear Embeddings ─────────────────────────────────────── */
async function handleClearEmbeddings(e) {
    e.stopPropagation();
    closeKnowledgeDropdown();

    if (!confirm('Limpar todos os embeddings? O conteúdo será mantido mas os arquivos voltarão ao status "pendente".')) return;

    const toastId = toastLoading('Limpando embeddings...');

    const res = await api('/api/knowledge/clear-embeddings', { method: 'POST' });
    if (res?.error) {
        toastDone(toastId, friendlyError(res.error), 'error');
    } else {
        toastDone(toastId, `${res.cleared} embeddings limpos`, 'success');
        loadKnowledge();
    }
}

/* ── Knowledge Delete All ─────────────────────────────────────────────── */
async function handleDeleteAll(e) {
    e.stopPropagation();
    closeKnowledgeDropdown();

    if (!confirm('Deletar TODO o knowledge? Essa ação não pode ser desfeita.')) return;

    const toastId = toastLoading('Deletando todo o knowledge...');

    const res = await api('/api/knowledge/all', { method: 'DELETE' });
    if (res?.error) {
        toastDone(toastId, friendlyError(res.error), 'error');
    } else {
        toastDone(toastId, `${res.deleted} arquivo(s) deletado(s)`, 'success');
        currentKnowledgeFile = null;
        document.getElementById('knowledge-editor').value = '';
        document.getElementById('knowledge-editor-header').innerHTML = '<span>Selecione um arquivo</span>';
        document.getElementById('knowledge-actions').style.display = 'none';
        loadKnowledge();
    }
}

/* ── WhatsApp (Datafy) ─────────────────────────────────────────────────────── */
async function loadWAConnection() {
    const el = document.getElementById('wa-status');
    if (!el) return;
    el.innerHTML = '<span class="wa-status-pill connecting"><span class="pulse-dot yellow"></span>Verificando...</span>';
    try {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 15000);
        const res = await fetch('/api/whatsapp/connection', {
            headers: { 'Content-Type': 'application/json' },
            signal: ctrl.signal,
        });
        clearTimeout(timer);
        if (res.status === 401 || res.redirected) {
            window.location.href = '/login';
            return;
        }
        let data;
        try { data = await res.json(); } catch(e) {
            el.innerHTML = '<span class="wa-status-pill error"><span class="pulse-dot red"></span>Resposta invalida do servidor</span>';
            return;
        }
        if (!data || data.error || !data.ok) {
            el.innerHTML = `<span class="wa-status-pill error" title="${esc(data?.error || '')}"><span class="pulse-dot red"></span>${esc(friendlyError(data?.error || 'Erro desconhecido'))}</span>`;
            document.getElementById('wa-info-grid').style.display = 'none';
            return;
        }
        el.innerHTML = '<span class="wa-status-pill open"><span class="pulse-dot green"></span>Conectado a Datafy API</span>';
        const infoGrid = document.getElementById('wa-info-grid');
        infoGrid.style.display = 'grid';
        document.getElementById('wa-phone').textContent = data.display_phone || data.phone_number_id || '-';
        document.getElementById('wa-display-name').textContent = data.display_name || '-';
        const qEl = document.getElementById('wa-quality');
        if (data.quality_rating) {
            const qColor = data.quality_rating === 'GREEN' ? '#22c55e' : (data.quality_rating === 'YELLOW' ? '#eab308' : '#ef4444');
            qEl.innerHTML = `<span style="color:${qColor};font-weight:600">${data.quality_rating}</span>`;
        } else { qEl.textContent = '-'; }
        document.getElementById('wa-name-status').textContent = data.name_status || '-';
        lastWAStatus = 'open';
    } catch(e) {
        const msg = e.name === 'AbortError' ? 'Servidor sem resposta (timeout)' : 'Erro de conexao';
        el.innerHTML = `<span class="wa-status-pill error"><span class="pulse-dot red"></span>${msg}</span>`;
        document.getElementById('wa-info-grid').style.display = 'none';
    }
}

function startWAConnectionPolling() {
    if (waStatusTimer) { clearInterval(waStatusTimer); waStatusTimer = null; }
    if (document.hidden) return;
    waStatusTimer = setInterval(loadWAConnection, 60000);
}

/* ── WhatsApp Config ───────────────────────────────────────────────────────── */
async function loadWAConfig() {
    const data = await api('/api/whatsapp/config');
    if (!data) return;
    for (const [key, info] of Object.entries(data)) {
        const input = document.querySelector(`#wa-config-form [name="${key}"]`);
        if (input) input.value = info.value || '';
    }
    const webhookInput = document.getElementById('wa-cfg-webhook');
    const webhookUrlEl = document.getElementById('wa-webhook-url');
    if (webhookInput) webhookUrlEl.textContent = webhookInput.value || 'Nao configurado';
}

async function saveWAConfig(e) {
    e.preventDefault();
    const form = e.target;
    const btn = document.getElementById('wa-config-save-btn');
    const payload = {};
    const inputs = form.querySelectorAll('input[name]');
    inputs.forEach(inp => { payload[inp.name] = inp.value; });
    setBtnLoading(btn, true, 'Salvando...');
    const res = await api('/api/whatsapp/config', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
    setBtnLoading(btn, false);
    if (res?.ok) {
        toast('Configuracao salva com sucesso', 'success');
        const webhookUrlEl = document.getElementById('wa-webhook-url');
        if (webhookUrlEl) webhookUrlEl.textContent = payload.WEBHOOK_URL || 'Nao configurado';
        loadWAConnection();
    } else {
        toast(res?.error || 'Erro ao salvar', 'error');
    }
}

function toggleSecretVisibility(inputId) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.type = input.type === 'password' ? 'text' : 'password';
}

async function loadTransferMessage() {
    const data = await api('/api/settings/transfer-message');
    if (!data) return;
    const textarea = document.getElementById('wa-transfer-msg');
    if (textarea) textarea.value = data.transfer_message || '';
}

async function saveTransferMessage() {
    const textarea = document.getElementById('wa-transfer-msg');
    if (!textarea) return;
    const msg = textarea.value.trim();
    if (!msg) { toast('Mensagem nao pode ser vazia', 'error'); return; }
    const res = await api('/api/settings/transfer-message', {
        method: 'PUT',
        body: JSON.stringify({ transfer_message: msg }),
    });
    if (res?.ok) {
        toast('Mensagem de transferencia salva', 'success');
    } else {
        toast(res?.error || 'Erro ao salvar', 'error');
    }
}

function copyWebhookUrl() {
    const el = document.getElementById('wa-webhook-url');
    if (!el || el.textContent === '-') return;
    navigator.clipboard.writeText(el.textContent).then(
        () => toast('URL copiada', 'success'),
        () => toast('Erro ao copiar', 'error')
    );
}

function toggleWAConfig() {
    const body = document.getElementById('wa-config-body');
    const arrow = document.getElementById('wa-config-arrow');
    if (!body || !arrow) return;
    const open = body.style.display === 'none';
    body.style.display = open ? 'block' : 'none';
    arrow.style.transform = open ? 'rotate(180deg)' : '';
}

function toggleWATransfer() {
    const body = document.getElementById('wa-transfer-body');
    const arrow = document.getElementById('wa-transfer-arrow');
    if (!body || !arrow) return;
    const open = body.style.display === 'none';
    body.style.display = open ? 'block' : 'none';
    arrow.style.transform = open ? 'rotate(180deg)' : '';
}

/* ── WhatsApp Meta Templates ──────────────────────────────────────────────── */
async function loadWATemplates() {
    const list = document.getElementById('wa-templates-list');
    if (!list) return;
    list.innerHTML = skeletonRows(3);
    const data = await api('/api/whatsapp/templates');
    if (!data || data.error) {
        list.innerHTML = `<p class="muted">${esc(data?.error || 'Erro ao carregar templates')}</p>`;
        return;
    }
    const templates = data.data || data;
    const items = Array.isArray(templates) ? templates : (templates.data || []);
    if (items.length === 0) {
        list.innerHTML = '<p class="muted">Nenhum template encontrado na WABA.</p>';
        return;
    }
    const statusColors = { APPROVED: '#22c55e', PENDING: '#f59e0b', REJECTED: '#ef4444', DISABLED: '#94a3b8' };
    list.innerHTML = items.map(t => {
        const st = t.status || 'PENDING';
        const color = statusColors[st] || '#94a3b8';
        const lang = t.language || '-';
        const cat = t.category || '-';
        const body = t.components?.find(c => c.type === 'BODY');
        const bodyText = body?.text || '-';
        return `<div style="display:flex;align-items:flex-start;justify-content:space-between;padding:10px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px">
            <div style="flex:1;min-width:0">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                    <strong style="font-size:13px">${esc(t.name)}</strong>
                    <span style="font-size:11px;padding:2px 8px;border-radius:10px;background:${color}22;color:${color};font-weight:600">${esc(st)}</span>
                    <span style="font-size:11px;color:var(--muted)">${esc(lang)} &middot; ${esc(cat)}</span>
                </div>
                <div style="font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:600px">${esc(bodyText)}</div>
            </div>
            <div style="display:flex;gap:4px;flex-shrink:0;margin-left:8px">
                <button class="btn-sm btn-secondary" onclick="viewWATemplate('${esc(t.id)}')" title="Detalhes">Ver</button>
                <button class="btn-sm btn-danger" onclick="deleteWATemplate('${esc(t.name)}')" title="Deletar">X</button>
            </div>
        </div>`;
    }).join('');
}

async function viewWATemplate(templateId) {
    const data = await api(`/api/whatsapp/templates/${templateId}`);
    if (!data || data.error) { toast(data?.error || 'Erro ao carregar', 'error'); return; }
    const t = data.data || data;
    const body = t.components?.find(c => c.type === 'BODY');
    const header = t.components?.find(c => c.type === 'HEADER');
    document.getElementById('modal-title').textContent = t.name || 'Template';
    document.getElementById('modal-body').innerHTML = `
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
            <span style="font-size:12px;padding:2px 8px;border-radius:10px;background:${t.status === 'APPROVED' ? '#22c55e22' : '#f59e0b22'};color:${t.status === 'APPROVED' ? '#22c55e' : '#f59e0b'};font-weight:600">${esc(t.status)}</span>
            <span style="font-size:12px;color:var(--muted)">${esc(t.language)} &middot; ${esc(t.category)}</span>
        </div>
        ${header ? `<div style="margin-bottom:8px"><strong>Header:</strong><div style="font-size:13px;margin-top:4px">${esc(header.text || '-')}</div></div>` : ''}
        <div style="margin-bottom:8px"><strong>Body:</strong><div style="font-size:13px;margin-top:4px;white-space:pre-wrap">${esc(body?.text || '-')}</div></div>
        <div style="margin-top:12px"><button class="btn-secondary" onclick="closeModal()">Fechar</button></div>`;
    document.getElementById('modal-overlay').style.display = 'flex';
}

function showCreateWATemplateForm() {
    document.getElementById('modal-title').textContent = 'Criar Template Meta';
    document.getElementById('modal-body').innerHTML = `
        <form onsubmit="saveWATemplate(event)">
            <div class="form-group"><label>Nome (sem espacos)</label><input name="name" required placeholder="ex: lembrete_3d"></div>
            <div class="form-row">
                <div class="form-group"><label>Categoria</label>
                    <select name="category">
                        <option value="UTILITY">Utility</option>
                        <option value="MARKETING">Marketing</option>
                        <option value="AUTHENTICATION">Authentication</option>
                    </select>
                </div>
                <div class="form-group"><label>Idioma</label><input name="language" value="pt_BR"></div>
            </div>
            <div class="form-group"><label>Header (opcional)</label><input name="header_text" placeholder="Texto do cabecalho"></div>
            <div class="form-group"><label>Body (use {{1}}, {{2}} etc para variaveis)</label><textarea name="body" rows="4" required placeholder="Ola {{1}}, tudo bem?"></textarea></div>
            <button type="submit" class="btn-primary">Criar Template</button>
        </form>`;
    document.getElementById('modal-overlay').style.display = 'flex';
}

async function saveWATemplate(e) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const fd = new FormData(form);
    const data = {};
    fd.forEach((v, k) => { if (v) data[k] = v; });
    setBtnLoading(btn, true, 'Criando...');
    const r = await api('/api/whatsapp/templates', { method: 'POST', body: JSON.stringify(data) });
    setBtnLoading(btn, false);
    if (r && r.ok) {
        toast('Template criado! Aguardando aprovacao da Meta.', 'success');
        closeModal();
        loadWATemplates();
    } else {
        toast(r?.error || 'Erro ao criar template', 'error');
    }
}

async function deleteWATemplate(templateName) {
    if (!confirm(`Deletar template "${templateName}"?`)) return;
    const r = await api(`/api/whatsapp/templates/${encodeURIComponent(templateName)}`, { method: 'DELETE' });
    if (r && r.ok) {
        toast('Template deletado', 'success');
        loadWATemplates();
    } else {
        toast(r?.error || 'Erro ao deletar', 'error');
    }
}

/* ── Modal ────────────────────────────────────────────────────────────────── */
function showModal(title, bodyHtml) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal-overlay').style.display = 'flex';
}

function closeModal() {
    const overlay = document.getElementById('modal-overlay');
    if (!overlay) return;
    const modal = overlay.querySelector('.modal');
    if (modal) modal.style.animation = 'msgOut 0.18s ease forwards';
    setTimeout(() => { 
        overlay.style.display = 'none'; 
        if (modal) modal.style.animation = '';
    }, 140);
}

/* ── Lightbox de mídia (tela cheia) ─────────────────────────────────────── */
let _lbCurrentSrc = '';
let _lbCurrentFilename = 'midia';

function openLightbox(src, filename) {
    _lbCurrentSrc = src;
    _lbCurrentFilename = filename || 'midia';
    const lb = document.getElementById('media-lightbox');
    const content = document.getElementById('media-lightbox-content');
    if (!lb || !content) return;
    content.innerHTML = '';
    const ext = (_lbCurrentFilename.split('.').pop() || '').toLowerCase();
    const isVideo = /^mp4|mov|webm|ogg$/.test(ext) || src.startsWith('data:video');
    const isAudio = /^mp3|wav|m4a|ogg|opus$/.test(ext) || src.startsWith('data:audio');
    let el;
    if (isVideo) {
        el = document.createElement('video');
        el.controls = true;
        el.autoplay = true;
        el.playsInline = true;
        el.src = src;
    } else if (isAudio) {
        el = document.createElement('audio');
        el.controls = true;
        el.autoplay = true;
        el.src = src;
    } else {
        el = document.createElement('img');
        el.src = src;
        el.alt = filename || '';
    }
    content.appendChild(el);
    lb.classList.add('open');
    document.body.style.overflow = 'hidden';
}

function closeLightbox(e) {
    if (e && e.target !== e.currentTarget && !e.target.classList.contains('media-lightbox-close')) return;
    const lb = document.getElementById('media-lightbox');
    if (lb) lb.classList.remove('open');
    document.body.style.overflow = '';
    _lbCurrentSrc = '';
}

function downloadLightboxMedia() {
    if (!_lbCurrentSrc) return;
    const a = document.createElement('a');
    a.href = _lbCurrentSrc;
    a.download = _lbCurrentFilename;
    a.click();
}

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        const lb = document.getElementById('media-lightbox');
        if (lb && lb.classList.contains('open')) {
            e.stopPropagation();
            closeLightbox();
        }
    }
});

/* ── SSE ──────────────────────────────────────────────────────────────────── */
let _convDebounce = null;
let _dashDebounce = null;
let _lidaTimer = null;
function marcarLidaEmBreve(convId) {
    clearTimeout(_lidaTimer);
    _lidaTimer = setTimeout(() => {
        if (currentConvId === convId) api(`/api/conversations/${convId}/read`, { method: 'PUT' });
    }, 1500);
}

function debouncedLoadConversations() {
    clearTimeout(_convDebounce);
    _convDebounce = setTimeout(() => {
        if (currentView === 'conversations') loadConversations();
        else if (currentView === 'bot') loadConversations(1);
        else if (currentView === 'human-queue') { loadConversations(0); updateHumanQueueBadge(); }
    }, 500);
}
function debouncedLoadDashboard() {
    clearTimeout(_dashDebounce);
    _dashDebounce = setTimeout(() => {
        if (currentView === 'dashboard') loadDashboard();
    }, 1000);
}
function connectSSE() {
    if (_sseSource) {
        _sseSource.close();
        _sseSource = null;
    }
    const source = new EventSource('/api/events');
    _sseSource = source;
    source.onmessage = async e => {
        if (e.data === ': keepalive') return;
        const { event, data } = JSON.parse(e.data);
        if (event === 'new_message') {
            if (currentView === 'conversations' || currentView === 'bot' || currentView === 'human-queue') {
                if (currentConvId === data.conversation_id) {
                    // Uma busca so, reaproveitada no cabecalho e nas mensagens.
                    // Eram 4 requisicoes juntas a cada mensagem, no mesmo
                    // instante em que o agente precisava do banco para responder.
                    const d = await api(`/api/conversations/${data.conversation_id}`);
                    if (d && currentConvId === data.conversation_id) refreshConversationPanel(data.conversation_id, d);
                    if (d?.messages?.length) {
                        const last = d.messages[d.messages.length - 1];
                        if (lastSentBodyQueue.includes(last.body)) {
                            lastSentBodyQueue = lastSentBodyQueue.filter(b => b !== last.body);
                        } else {
                            const lastEl = document.querySelector('#chat-messages .msg:last-child');
                            const lastId = lastEl?.dataset?.msgId;
                            if (!(lastId && lastId === String(last.uazapi_id || last.id || ''))) {
                                appendMessage(last);
                            }
                        }
                    }
                    // A conversa está aberta e visível: marca como lida (agrupado:
                    // varias mensagens seguidas viram uma marcacao so).
                    marcarLidaEmBreve(data.conversation_id);
                    debouncedLoadConversations();
                } else {
                    debouncedLoadConversations();
                }
            }
            updateUnreadBadge();
            if (currentView === 'dashboard') debouncedLoadDashboard();
        } else if (event === 'message_sent') {
            lastSentBodyQueue = [];
            if ((currentView === 'conversations' || currentView === 'bot' || currentView === 'human-queue') && currentConvId === data.conversation_id) {
                const d = await api(`/api/conversations/${data.conversation_id}`);
                if (d && currentConvId === data.conversation_id) {
                    refreshConversationPanel(data.conversation_id, d);
                    if (d.messages?.length) renderMessages(d.messages);
                }
            }
            if (currentView === 'dashboard') debouncedLoadDashboard();
        } else if (event === 'google_agenda_mudou') {
            // Alguem mexeu direto no Google Agenda: a grade aberta se atualiza.
            agendaAtualizarEmSegundoPlano();
        } else if (event === 'agendamento_atualizado') {
            updateAgendamentosBadge();
            if (currentView === 'agendamentos') loadAgendamentosPendentes();
            else if (currentView === 'agenda') { agendaCache.clear(); loadAgenda(); }
        } else if (event === 'conversation_updated') {
            debouncedLoadConversations();
            updateUnreadBadge();   // ja atualiza a Fila Humana
        } else if (event === 'tags_updated') {
            refreshTagsUI();
        } else if (event === 'crm_follow_up_sent') {
            if (currentView === 'crm') {
                if (crmCurrentView === 'dashboard') loadCrmDashboard();
                else if (crmCurrentView === 'followups') loadCrmFollowUps();
                else if (crmCurrentView === 'logs') loadCrmLogs();
            }
        } else if (event === 'wa_status') {
            if (currentView === 'whatsapp') {
                loadWAConnection();
            }
        }
    };
    source.onerror = () => {
        source.close();
        _sseSource = null;
        setTimeout(connectSSE, 3000);
    };
}

// Os contadores do menu: varias mensagens seguidas viram UMA atualizacao.
// Cada uma recalculava as estatisticas do painel inteiro no banco.
let _badgeTimer = null;
function updateUnreadBadge() {
    clearTimeout(_badgeTimer);
    _badgeTimer = setTimeout(_atualizarBadges, 1000);
}

async function _atualizarBadges() {
    const stats = await api('/api/dashboard');
    if (!stats) return;
    const badge = document.getElementById('unread-badge');
    if (stats.unread_messages > 0) {
        badge.textContent = stats.unread_messages;
        badge.style.display = 'inline-flex';
    } else {
        badge.style.display = 'none';
    }
    updateHumanQueueBadge();
}

async function updateHumanQueueBadge() {
    const data = await api('/api/conversations/human-queue/count');
    if (!data) return;
    const badge = document.getElementById('human-queue-badge');
    if (data.count > 0) {
        badge.textContent = data.count;
        badge.style.display = 'inline-flex';
    } else {
        badge.style.display = 'none';
    }
}

/* ── Helpers ──────────────────────────────────────────────────────────────── */
function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function spinHTML(label) {
    return `<span class="spinner"></span>${label ? ' ' + esc(label) : ''}`;
}

function setBtnLoading(btn, loading, label) {
    if (!btn) return;
    if (loading) {
        btn.dataset.originalHtml = btn.innerHTML;
        btn.classList.add('btn-loading');
        btn.disabled = true;
        btn.innerHTML = spinHTML(label);
    } else {
        btn.classList.remove('btn-loading');
        btn.disabled = false;
        btn.innerHTML = btn.dataset.originalHtml || '';
    }
}

function skeletonCards(n) {
    return Array.from({length: n}, () =>
        '<div class="skeleton skeleton-card"></div>'
    ).join('');
}

function skeletonRows(n) {
    return Array.from({length: n}, () =>
        '<div class="skeleton-row"><div class="skeleton skeleton-avatar"></div><div class="skeleton" style="flex:1;height:14px"></div><div class="skeleton" style="width:60px;height:14px"></div></div>'
    ).join('');
}

function skeletonMsgs() {
    return '<div class="skeleton-msg in"><div class="skeleton" style="height:30px;border-radius:12px;width:55%"></div></div>'
         + '<div class="skeleton-msg out"><div class="skeleton" style="height:30px;border-radius:12px;width:42%"></div></div>';
}

function friendlyError(err) {
    if (!err) return 'Erro desconhecido';
    if (err.includes('401')) return 'Token invalido. Verifique as configuracoes.';
    if (err.includes('404')) return 'Recurso nao encontrado.';
    if (err.includes('Connection error') || err.includes('Timeout')) return 'Servidor indisponivel.';
    return err;
}

function closeDiagnose() {
    // Removido: diagnostic container nao existe mais na aba Datafy
}

function closeQR() {
    // Removido: QR container nao existe mais na aba Datafy
}

/* ── Agendamentos (Confirmação de Agendamento) ─────────────────────────────── */
const DIAS_CURTOS = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho',
               'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
let agendaDuracaoPadrao = 60;

function pad2(n) { return String(n).padStart(2, '0'); }
function isoDia(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }
function quandoAgendamento(inicio) {
    if (!inicio) return '-';
    const d = new Date(inicio);
    return `${DIAS_CURTOS[d.getDay()]}, ${pad2(d.getDate())}/${pad2(d.getMonth() + 1)} às ${pad2(d.getHours())}h${pad2(d.getMinutes())}`;
}
function duracaoTexto(min) {
    min = Number(min) || 60;
    const h = Math.floor(min / 60), m = min % 60;
    return h ? `${h}h${m ? pad2(m) : ''}` : `${m} min`;
}

async function updateAgendamentosBadge() {
    const data = await api('/api/agendamentos/pendentes/count');
    const badge = document.getElementById('agendamentos-badge');
    if (!data || !badge) return;
    badge.textContent = data.count;
    badge.style.display = data.count > 0 ? 'inline-flex' : 'none';
}

async function loadAgendamentosPendentes() {
    const lista = document.getElementById('ag-pendentes');
    if (!lista) return;
    const primeira = !lista.dataset.loaded;
    if (primeira) lista.innerHTML = skeletonRows(3);
    const ags = await api('/api/agendamentos?status=pendente');
    lista.dataset.loaded = '1';
    updateAgendamentosBadge();
    // Atualizacao automatica (a cada 20s) so redesenha se algo mudou: antes a
    // lista inteira piscava mesmo igual.
    const assinatura = JSON.stringify((ags || []).map(a => [a.id, a.updated_at]));
    if (!primeira && assinatura === lista.dataset.sig) return;
    lista.dataset.sig = assinatura;
    if (!ags || ags.length === 0) {
        lista.innerHTML = '<div class="empty-state">Nenhum agendamento aguardando confirmação 🎉</div>';
        return;
    }
    lista.innerHTML = ags.map((a, i) => {
        const recebido = a.created_at ? new Date(a.created_at + 'Z').toLocaleString('pt-BR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';
        const disp = (a.ficha && a.ficha.disponibilidade) || '';
        return `
        <div class="ag-card ag-entra" data-ag-id="${a.id}" style="--i:${Math.min(i, 8)}">
            <div class="ag-card-topo">
                <div>
                    <div class="ag-nome">${esc(a.nome)}</div>
                    <div class="muted ag-meta">${esc(a.phone)} · pedido em ${recebido}</div>
                </div>
                ${disp ? `<div class="ag-pref">Prefere: <strong>${esc(disp.replace(/\n/g, ' / '))}</strong></div>` : ''}
            </div>
            <pre class="ag-resumo">${esc(a.resumo || '')}</pre>
            <div class="ag-acoes">
                <button class="btn-secondary btn-sm" onclick="abrirConversaAgendamento(${a.conversation_id})">Abrir conversa</button>
                <button class="btn-secondary btn-sm ag-cancelar" onclick="cancelarAgendamento(${a.id}, false)">Cancelar pedido</button>
                <button class="btn-primary btn-sm" onclick="formHorarioAgendamento(${a.id}, false)">Confirmar horário</button>
            </div>
        </div>`;
    }).join('');
}

function abrirConversaAgendamento(convId) {
    if (!convId) { toast('Conversa não encontrada', 'error'); return; }
    closeModal();
    switchView('conversations');
    selectConversation(convId);
}

async function formHorarioAgendamento(agId, remarcar) {
    const a = await api(`/api/agendamentos/${agId}`);
    if (!a || a.error) { toast('Agendamento não encontrado', 'error'); return; }
    const ini = a.inicio ? new Date(a.inicio) : null;
    const data = ini ? isoDia(ini) : '';
    const hora = ini ? `${pad2(ini.getHours())}:${pad2(ini.getMinutes())}` : '';
    const duracao = a.duracao_min || agendaDuracaoPadrao;
    const opcoes = [30, 45, 60, 90, 120];
    if (!opcoes.includes(Number(duracao))) opcoes.push(Number(duracao));
    const disp = (a.ficha && a.ficha.disponibilidade) || '';
    document.getElementById('modal-title').textContent = remarcar ? 'Remarcar avaliação' : 'Confirmar horário';
    document.getElementById('modal-body').innerHTML = `
        <form onsubmit="salvarHorarioAgendamento(event, ${agId}, ${remarcar}, false)">
            <p><strong>${esc(a.nome)}</strong> · ${esc(a.phone)}</p>
            ${disp ? `<p class="muted">Preferência do paciente: ${esc(disp.replace(/\n/g, ' / '))}</p>` : ''}
            <div class="ag-form-linha">
                <div class="form-group"><label>Data</label><input type="date" name="data" value="${data}" min="${isoDia(new Date())}" required></div>
                <div class="form-group"><label>Horário</label><input type="time" name="hora" value="${hora}" step="300" required></div>
                <div class="form-group"><label>Duração</label>
                    <select name="duracao_min">${opcoes.sort((x, y) => x - y).map(m =>
                        `<option value="${m}" ${Number(duracao) === m ? 'selected' : ''}>${duracaoTexto(m)}</option>`).join('')}</select></div>
            </div>
            <div class="form-group"><label>Observações (opcional)</label><textarea name="observacoes" rows="2">${esc(a.observacoes || '')}</textarea></div>
            <label class="ag-check"><input type="checkbox" name="avisar" checked> Avisar o paciente no WhatsApp</label>
            <div id="ag-conflito"></div>
            <button type="submit" class="btn-primary">${remarcar ? 'Salvar novo horário' : 'Confirmar agendamento'}</button>
        </form>`;
    document.getElementById('modal-overlay').style.display = 'flex';
}

async function salvarHorarioAgendamento(e, agId, remarcar, forcar) {
    if (e) e.preventDefault();
    const form = document.querySelector('#modal-body form');
    const f = new FormData(form);
    const corpo = {
        data: f.get('data'), hora: f.get('hora'), duracao_min: Number(f.get('duracao_min')),
        observacoes: f.get('observacoes') || '', avisar: f.get('avisar') === 'on', forcar,
    };
    const btn = form.querySelector('button[type="submit"]');
    setBtnLoading(btn, true, 'Salvando...');
    const r = await api(remarcar ? `/api/agendamentos/${agId}` : `/api/agendamentos/${agId}/confirmar`,
                        { method: remarcar ? 'PUT' : 'POST', body: JSON.stringify(corpo) });
    setBtnLoading(btn, false);
    if (r && r.error === 'conflito') {
        document.getElementById('ag-conflito').innerHTML = `
            <div class="ag-alerta">Já existe avaliação nesse horário: ${r.conflitos.map(c =>
                `<strong>${esc(c.nome)}</strong> (${quandoAgendamento(c.inicio)})`).join(', ')}.
                <button type="button" class="btn-secondary btn-sm" onclick="salvarHorarioAgendamento(null, ${agId}, ${remarcar}, true)">Agendar mesmo assim</button>
            </div>`;
        return;
    }
    if (!r || r.error) { toast(friendlyError(r?.error || 'Erro ao salvar'), 'error'); return; }
    closeModal();
    let msg = remarcar ? 'Avaliação remarcada' : 'Agendamento confirmado';
    if (corpo.avisar) msg += r.avisado ? ' e paciente avisado' : ' (o aviso no WhatsApp não saiu)';
    toast(msg, r.avisado || !corpo.avisar ? 'success' : 'error');
    if (r.erro_google) toast('Não sincronizou com o Google Calendar: ' + r.erro_google, 'error');
    aposMudancaDeAgendamento(agId);
}

// Pedido resolvido: o cartao sai animado antes da lista se refazer, e a
// Agenda descarta o que tinha guardado (o horario mudou).
async function aposMudancaDeAgendamento(agId) {
    agendaCache.clear();
    updateAgendamentosBadge();
    if (currentView === 'agendamentos') {
        const card = document.querySelector(`.ag-card[data-ag-id="${agId}"]`);
        if (card && !reduzirMovimento()) {
            card.classList.add('ag-sai');
            await new Promise(r => setTimeout(r, 260));
        }
        loadAgendamentosPendentes();
    }
    if (currentView === 'agenda') loadAgenda();
}

async function cancelarAgendamento(agId, confirmado) {
    document.getElementById('modal-title').textContent = confirmado ? 'Cancelar avaliação' : 'Cancelar pedido';
    document.getElementById('modal-body').innerHTML = `
        <p>${confirmado ? 'A avaliação sai da Agenda (e do Google Calendar, se conectado).' : 'O pedido sai da lista de confirmação.'}</p>
        ${confirmado ? '<label class="ag-check"><input type="checkbox" id="ag-cancelar-avisar" checked> Avisar o paciente no WhatsApp</label>' : ''}
        <div class="ag-acoes">
            <button class="btn-secondary" onclick="closeModal()">Voltar</button>
            <button class="btn-primary ag-btn-perigo" onclick="executarCancelamento(${agId})">Cancelar ${confirmado ? 'avaliação' : 'pedido'}</button>
        </div>`;
    document.getElementById('modal-overlay').style.display = 'flex';
}

async function executarCancelamento(agId) {
    const avisar = !!document.getElementById('ag-cancelar-avisar')?.checked;
    const r = await api(`/api/agendamentos/${agId}/cancelar`, { method: 'POST', body: JSON.stringify({ avisar }) });
    if (!r || r.error) { toast(friendlyError(r?.error || 'Erro ao cancelar'), 'error'); return; }
    closeModal();
    toast(avisar ? (r.avisado ? 'Cancelado e paciente avisado' : 'Cancelado (o aviso não saiu)') : 'Cancelado', 'success');
    aposMudancaDeAgendamento(agId);
}

/* ── Agenda (calendário de confirmados) ────────────────────────────────────── */
let agendaRef = new Date();
let agendaModoAtual = 'mes';
let agendaReq = 0;
let agendaChaveNaTela = '';
// Periodos ja carregados: voltar a um mes visto aparece na hora, e o mes
// anterior/seguinte e buscado de antemao. Qualquer mudanca de agendamento
// limpa tudo (aposMudancaDeAgendamento).
const agendaCache = new Map();

function reduzirMovimento() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function agendaIntervalo(ref = agendaRef, modo = agendaModoAtual) {
    if (modo === 'semana') {
        const ini = new Date(ref); ini.setHours(0, 0, 0, 0);
        ini.setDate(ini.getDate() - ini.getDay());
        const fim = new Date(ini); fim.setDate(fim.getDate() + 7);
        return [ini, fim];
    }
    const primeiro = new Date(ref.getFullYear(), ref.getMonth(), 1);
    const ini = new Date(primeiro); ini.setDate(1 - primeiro.getDay());
    const fim = new Date(ini); fim.setDate(fim.getDate() + 42);
    return [ini, fim];
}

function agendaRefDeslocada(delta) {
    if (agendaModoAtual === 'semana') {
        const d = new Date(agendaRef); d.setDate(d.getDate() + 7 * delta); return d;
    }
    return new Date(agendaRef.getFullYear(), agendaRef.getMonth() + delta, 1);
}

function agendaMover(delta) {
    agendaRef = agendaRefDeslocada(delta);
    loadAgenda(delta > 0 ? 'prox' : 'ant');
}
function agendaHoje() {
    const antes = agendaIntervalo()[0];
    agendaRef = new Date();
    const depois = agendaIntervalo()[0];
    loadAgenda(depois > antes ? 'prox' : depois < antes ? 'ant' : null);
}
function agendaModo(modo) {
    if (modo === agendaModoAtual) return;
    agendaModoAtual = modo;
    document.getElementById('agenda-modo-mes').classList.toggle('active', modo === 'mes');
    document.getElementById('agenda-modo-semana').classList.toggle('active', modo === 'semana');
    document.querySelector('.agenda-modo')?.classList.toggle('semana', modo === 'semana');
    loadAgenda('modo');
}

function agendaUrl(ini, fim) {
    return `/api/agendamentos?status=confirmado&de=${isoDia(ini)}&ate=${isoDia(fim)}`;
}

// Configuracao e status do Google: uma vez ao abrir a aba, nao a cada clique.
async function loadAgendaConfig() {
    const box = document.getElementById('agenda-google');
    if (box && !box.dataset.carregado) {
        box.innerHTML = '<span class="skeleton agenda-google-esqueleto"></span>';
    }
    const cfg = await api('/api/settings/agenda');
    if (box) box.dataset.carregado = '1';
    if (!cfg) return;
    agendaDuracaoPadrao = cfg.duracao_padrao || 60;
    const sel = document.getElementById('agenda-duracao-padrao');
    if (sel) {
        if (![...sel.options].some(o => Number(o.value) === agendaDuracaoPadrao)) {
            sel.insertAdjacentHTML('beforeend', `<option value="${agendaDuracaoPadrao}">${duracaoTexto(agendaDuracaoPadrao)}</option>`);
        }
        sel.value = String(agendaDuracaoPadrao);
    }
    renderGoogleStatus(cfg.google || {});
}

// Agendamentos do painel + o que foi marcado direto no Google, juntos por periodo.
const agendaGoogle = new Map();   // id do evento -> evento (para o detalhe)
let agendaNovaTentativa = null;
async function agendaBuscar(ini, fim) {
    // Uma ida so: agendamentos + Google. O servidor tem a agenda do Google em
    // memoria, entao isto nao espera o Google responder.
    const r = await api(`/api/agenda?de=${isoDia(ini)}&ate=${isoDia(fim)}`).catch(() => null);
    if (!r || !Array.isArray(r.ags)) return null;
    const google = Array.isArray(r.google) ? r.google : [];
    google.forEach(e => agendaGoogle.set(e.id, e));
    return { ags: r.ags, google };
}

// `silencioso`: atualizacao em segundo plano (a cada minuto e ao voltar para
// a aba). So redesenha se algo mudou - sem piscar, sem animacao.
async function loadAgenda(animacao = null, silencioso = false) {
    const req = ++agendaReq;
    const [ini, fim] = agendaIntervalo();
    const chave = agendaUrl(ini, fim);
    document.getElementById('agenda-titulo').textContent = agendaModoAtual === 'semana'
        ? `${pad2(ini.getDate())}/${pad2(ini.getMonth() + 1)} – ${pad2(new Date(fim - 1).getDate())}/${pad2(new Date(fim - 1).getMonth() + 1)}`
        : `${MESES[agendaRef.getMonth()][0].toUpperCase()}${MESES[agendaRef.getMonth()].slice(1)} de ${agendaRef.getFullYear()}`;

    // A grade do periodo novo aparece NA HORA (com o que estiver guardado);
    // os horarios chegam depois, sem esperar o servidor para mudar de tela.
    const guardado = agendaCache.get(chave);
    if (!silencioso) renderAgenda(guardado || { ags: [], google: [] }, ini, fim, animacao, !guardado);
    agendaChaveNaTela = chave;

    const dados = await agendaBuscar(ini, fim);
    if (req !== agendaReq) return;  // usuario ja navegou para outro periodo
    if (!dados) {
        clearTimeout(agendaNovaTentativa);
        agendaNovaTentativa = setTimeout(() => { if (currentView === 'agenda') loadAgenda(null, true); }, 2000);
        if (!guardado) return;          // segue com a barra de carregamento
    }
    if (dados) agendaCache.set(chave, dados);
    if (dados && (!guardado || JSON.stringify(guardado) !== JSON.stringify(dados))) {
        renderAgenda(dados, ini, fim, null, false);
    } else {
        document.getElementById('agenda-grade').classList.remove('carregando');
    }
    if (!silencioso) agendaPrecarregar();
}

function agendaPrecarregar() {
    [-1, 1].forEach(delta => {
        const [ini, fim] = agendaIntervalo(agendaRefDeslocada(delta));
        const url = agendaUrl(ini, fim);
        if (!agendaCache.has(url)) agendaBuscar(ini, fim).then(r => { if (r) agendaCache.set(url, r); });
    });
}

// Com a aba Agenda aberta: o que alguem marcar no Google aparece sozinho.
function agendaAtualizarEmSegundoPlano() {
    if (currentView !== 'agenda' || document.hidden) return;
    const guardado = agendaCache.get(agendaChaveNaTela);
    agendaCache.clear();
    if (guardado) agendaCache.set(agendaChaveNaTela, guardado);  // base da comparacao
    loadAgenda(null, true);
}
window.addEventListener('focus', agendaAtualizarEmSegundoPlano);

function renderAgenda(dados, ini, fim, animacao, carregando) {
    const { ags = [], google = [] } = dados || {};
    const porDia = {};
    ags.forEach(a => {
        (porDia[(a.inicio || '').slice(0, 10)] ||= []).push({ tipo: 'ag', hora: (a.inicio || '').slice(11, 16), item: a });
    });
    google.forEach(e => {
        if (e.dia_inteiro) {
            // Evento de dia inteiro (ferias, congresso...): aparece em cada dia.
            for (let d = new Date(e.inicio); d < new Date(e.fim); d.setDate(d.getDate() + 1)) {
                (porDia[isoDia(d)] ||= []).push({ tipo: 'g', hora: '', item: e });
            }
        } else {
            (porDia[e.inicio.slice(0, 10)] ||= []).push({ tipo: 'g', hora: e.inicio.slice(11, 16), item: e });
        }
    });
    Object.values(porDia).forEach(l => l.sort((a, b) => a.hora.localeCompare(b.hora)));
    const hoje = isoDia(new Date());
    const dias = [];
    for (let d = new Date(ini); d < fim; d.setDate(d.getDate() + 1)) dias.push(new Date(d));
    const chip = (x, i) => x.tipo === 'ag'
        ? `<button class="agenda-evento" style="--i:${Math.min(i, 6)}" onclick="detalheAgendamento(${x.item.id})" title="${esc(x.item.nome)}">
            <span class="agenda-hora">${x.hora}</span> ${esc(x.item.nome)}</button>`
        : `<button class="agenda-evento google" style="--i:${Math.min(i, 6)}" data-gid="${esc(x.item.id)}" onclick="detalheEventoGoogle(this.dataset.gid)" title="${esc(x.item.titulo)} (Google Agenda)">
            <span class="agenda-hora">${x.hora || 'Dia todo'}</span> ${esc(x.item.titulo)}</button>`;
    const semana = agendaModoAtual === 'semana';
    const grade = document.getElementById('agenda-grade');
    grade.classList.toggle('carregando', !!carregando);
    // Cabecalho fixo; so o corpo entra animado (desliza no ‹ ›, zoom no modo).
    if (!grade.querySelector('.agenda-cabecalho')) {
        grade.innerHTML = `<div class="agenda-cabecalho">${DIAS_CURTOS.map(d => `<div>${d}</div>`).join('')}</div>
            <div class="agenda-corpo"></div>
            <div class="agenda-aviso-carregando" role="status" aria-live="polite">
                <span class="agenda-spinner"></span> Carregando agenda…
            </div>`;
    }
    const corpo = grade.querySelector('.agenda-corpo');
    corpo.innerHTML = `
        <div class="agenda-dias ${semana ? 'agenda-semana' : ''}">
            ${dias.map(d => {
                const k = isoDia(d);
                const fora = !semana && d.getMonth() !== agendaRef.getMonth();
                return `<div class="agenda-dia ${fora ? 'fora' : ''} ${k === hoje ? 'hoje' : ''}">
                    <div class="agenda-num">${semana ? `${DIAS_CURTOS[d.getDay()]} ` : ''}${d.getDate()}</div>
                    ${carregando ? agendaEsqueletos(d, semana) : (porDia[k] || []).map(chip).join('')}
                </div>`;
            }).join('')}
        </div>
        ${ags.length || google.length || carregando ? '' : '<p class="muted agenda-vazia">Nenhum compromisso neste período.</p>'}`;
    if (animacao && !reduzirMovimento()) {
        corpo.classList.remove('anim-prox', 'anim-ant', 'anim-modo');
        void corpo.offsetWidth;  // reinicia a animacao
        corpo.classList.add(`anim-${animacao}`);
    }
}

// Blocos com brilho no lugar dos compromissos enquanto a agenda chega. A
// distribuicao e fixa por dia (nao sorteada): trocar de mes nao "pula".
function agendaEsqueletos(d, semana) {
    const n = semana ? 1 + (d.getDate() * 7) % 3 : ((d.getDate() * 7 + d.getMonth()) % 5 === 0 ? 2 : (d.getDate() * 3) % 4 === 0 ? 1 : 0);
    return Array.from({ length: n }, (_, i) =>
        `<span class="agenda-esqueleto skeleton" style="width:${70 + ((d.getDate() + i * 13) % 25)}%"></span>`).join('');
}

function detalheEventoGoogle(id) {
    const e = agendaGoogle.get(id);
    if (!e) return;
    const quando = e.dia_inteiro ? 'Dia todo' : `${quandoAgendamento(e.inicio)} · ${duracaoTexto(e.duracao_min)}`;
    const dia = e.dia_inteiro ? `${pad2(Number(e.inicio.slice(8, 10)))}/${e.inicio.slice(5, 7)} · ` : '';
    document.getElementById('modal-title').textContent = e.titulo;
    document.getElementById('modal-body').innerHTML = `
        <div class="ag-detalhe">
            <p><strong>${esc(dia + quando)}</strong></p>
            <p class="muted">Marcado direto no Google Agenda${e.ocupa ? '' : ' · aparece como livre'}</p>
            ${e.local ? `<p><strong>Local:</strong> ${esc(e.local)}</p>` : ''}
            ${e.descricao ? `<pre class="ag-resumo">${esc(e.descricao)}</pre>` : ''}
            <p class="muted">Para alterar ou apagar, use o Google Agenda.</p>
            ${e.link ? `<div class="ag-acoes"><a class="btn-primary btn-sm" href="${esc(e.link)}" target="_blank" rel="noopener">Abrir no Google Agenda</a></div>` : ''}
        </div>`;
    document.getElementById('modal-overlay').style.display = 'flex';
}

async function detalheAgendamento(agId) {
    const a = await api(`/api/agendamentos/${agId}`);
    if (!a || a.error) { toast('Agendamento não encontrado', 'error'); return; }
    document.getElementById('modal-title').textContent = a.nome;
    document.getElementById('modal-body').innerHTML = `
        <div class="ag-detalhe">
            <p><strong>${quandoAgendamento(a.inicio)}</strong> · ${duracaoTexto(a.duracao_min)}</p>
            <p class="muted">${esc(a.phone)}${a.google_event_id ? ' · no Google Calendar' : ''}</p>
            ${a.observacoes ? `<p><strong>Observações:</strong> ${esc(a.observacoes)}</p>` : ''}
            <pre class="ag-resumo">${esc(a.resumo || '')}</pre>
            <div class="ag-acoes">
                <button class="btn-secondary btn-sm" onclick="abrirConversaAgendamento(${a.conversation_id})">Abrir conversa</button>
                <button class="btn-secondary btn-sm ag-cancelar" onclick="cancelarAgendamento(${a.id}, true)">Cancelar</button>
                <button class="btn-primary btn-sm" onclick="formHorarioAgendamento(${a.id}, true)">Remarcar</button>
            </div>
        </div>`;
    document.getElementById('modal-overlay').style.display = 'flex';
}

async function salvarDuracaoPadrao(valor) {
    const r = await api('/api/settings/agenda', { method: 'PUT', body: JSON.stringify({ duracao_padrao: Number(valor) }) });
    if (r && r.ok) { agendaDuracaoPadrao = r.duracao_padrao; toast(`Duração padrão: ${duracaoTexto(r.duracao_padrao)}`, 'success'); }
    else toast(friendlyError(r?.error || 'Erro ao salvar'), 'error');
}

/* ── Horários disponíveis ──────────────────────────────────────────────────── */
// A equipe define a semana de atendimento; o servidor cruza com a Agenda e o
// Google e devolve as vagas livres. Ainda não muda nada no fluxo do agente.
let horariosCfg = null;
let horariosNomes = [];

async function loadHorarios() {
    const semana = document.getElementById('hr-semana');
    if (!horariosCfg) semana.innerHTML = skeletonRows(3);
    const r = await api('/api/settings/horarios');
    if (!r || !r.config) { semana.innerHTML = '<div class="empty-state">Não foi possível carregar os horários.</div>'; return; }
    horariosCfg = r.config;
    horariosNomes = r.dias || [];
    document.getElementById('hr-duracao').textContent =
        `Cada avaliação ocupa ${duracaoTexto(r.duracao_padrao || 60)} (duração padrão, ajustável na aba Agenda).`;
    renderHorarios();
    loadVagas();
}

function hrSelecionar(id, valor) {
    const sel = document.getElementById(id);
    if (![...sel.options].some(o => Number(o.value) === valor)) {
        sel.insertAdjacentHTML('beforeend', `<option value="${valor}">${valor}</option>`);
    }
    sel.value = String(valor);
}

function renderHorarios() {
    const cfg = horariosCfg;
    // Segunda a domingo, na ordem do weekday() do Python.
    document.getElementById('hr-semana').innerHTML = horariosNomes.map((nome, k) => {
        const faixas = cfg.dias[String(k)] || [];
        return `
        <div class="hr-dia ${faixas.length ? '' : 'fechado'}" data-dia="${k}">
            <label class="hr-dia-nome"><input type="checkbox" ${faixas.length ? 'checked' : ''} onchange="hrAlternarDia(${k}, this.checked)"> ${esc(nome)}</label>
            <div class="hr-faixas">
                ${faixas.length ? faixas.map((f, i) => `
                    <span class="hr-faixa">
                        <input type="time" class="hr-input" value="${esc(f[0])}" onchange="hrEditar(${k}, ${i}, 0, this.value)">
                        <span class="muted">às</span>
                        <input type="time" class="hr-input" value="${esc(f[1])}" onchange="hrEditar(${k}, ${i}, 1, this.value)">
                        <button class="hr-remover" title="Remover faixa" aria-label="Remover faixa" onclick="hrRemoverFaixa(${k}, ${i})">&times;</button>
                    </span>`).join('') + `<button class="hr-mais" onclick="hrNovaFaixa(${k})">+ faixa</button>`
                : '<span class="muted">Não atende</span>'}
            </div>
        </div>`;
    }).join('');
    hrSelecionar('hr-passo', cfg.passo_min);
    hrSelecionar('hr-antecedencia', cfg.antecedencia_horas);
    hrSelecionar('hr-janela', cfg.janela_dias);
    renderBloqueios();
}

function hrAlternarDia(k, atende) {
    horariosCfg.dias[String(k)] = atende ? [['08:00', '12:00'], ['14:00', '18:00']] : [];
    renderHorarios();
}
function hrEditar(k, i, lado, valor) { horariosCfg.dias[String(k)][i][lado] = valor; }
function hrRemoverFaixa(k, i) { horariosCfg.dias[String(k)].splice(i, 1); renderHorarios(); }
function hrNovaFaixa(k) {
    const faixas = horariosCfg.dias[String(k)];
    const ultima = faixas.length ? faixas[faixas.length - 1][1] : '08:00';
    const h = Math.min(Number(ultima.slice(0, 2)) + 1, 22);
    faixas.push([`${pad2(h)}:00`, `${pad2(h + 1)}:00`]);
    renderHorarios();
}

function renderBloqueios() {
    const box = document.getElementById('hr-bloqueios');
    const lista = horariosCfg.bloqueios || [];
    box.innerHTML = lista.length ? lista.map((b, i) => {
        const d = new Date(b.data + 'T12:00');
        const quando = d.toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' });
        return `<span class="hr-bloqueio">${esc(quando)}${b.motivo ? ` · ${esc(b.motivo)}` : ''}
            <button class="hr-remover" title="Desbloquear" aria-label="Desbloquear" onclick="removerBloqueio(${i})">&times;</button></span>`;
    }).join('') : '<span class="muted">Nenhum dia bloqueado.</span>';
}

function adicionarBloqueio() {
    const data = document.getElementById('hr-bloqueio-data');
    const motivo = document.getElementById('hr-bloqueio-motivo');
    if (!data.value) { toast('Escolha a data a bloquear', 'error'); return; }
    horariosCfg.bloqueios = (horariosCfg.bloqueios || []).filter(b => b.data !== data.value);
    horariosCfg.bloqueios.push({ data: data.value, motivo: motivo.value.trim() });
    horariosCfg.bloqueios.sort((a, b) => a.data.localeCompare(b.data));
    data.value = ''; motivo.value = '';
    renderBloqueios();
    toast('Dia bloqueado. Clique em Salvar para valer.', 'info');
}
function removerBloqueio(i) { horariosCfg.bloqueios.splice(i, 1); renderBloqueios(); }

async function salvarHorarios() {
    if (!horariosCfg) return;
    const corpo = {
        ...horariosCfg,
        passo_min: Number(document.getElementById('hr-passo').value),
        antecedencia_horas: Number(document.getElementById('hr-antecedencia').value),
        janela_dias: Number(document.getElementById('hr-janela').value),
    };
    const btn = document.getElementById('hr-salvar');
    btn.disabled = true;
    const r = await api('/api/settings/horarios', { method: 'PUT', body: JSON.stringify(corpo) });
    btn.disabled = false;
    if (r && r.ok) {
        horariosCfg = r.config;
        renderHorarios();
        loadVagas();
        toast('Horários salvos', 'success');
    } else toast(friendlyError(r?.error || 'Erro ao salvar'), 'error');
}

async function loadVagas() {
    const box = document.getElementById('hr-vagas');
    box.innerHTML = skeletonRows(4);
    const r = await api('/api/horarios/livres');
    if (!r || !Array.isArray(r.vagas)) { box.innerHTML = '<div class="empty-state">Não foi possível calcular as vagas.</div>'; return; }
    const aviso = r.google_erro ? '<p class="muted hr-nota">Google Agenda indisponível agora: as vagas consideram só a Agenda do painel.</p>' : '';
    if (!r.vagas.length) { box.innerHTML = aviso + '<div class="empty-state">Nenhuma vaga livre no período.</div>'; return; }
    const total = r.vagas.reduce((n, v) => n + v.horarios.length, 0);
    box.innerHTML = aviso + `<p class="muted hr-nota">${total} ${total === 1 ? 'vaga livre' : 'vagas livres'} de ${duracaoTexto(r.duracao_min)}.</p>` +
        r.vagas.map(v => {
            const d = new Date(v.data + 'T12:00');
            return `<div class="hr-vaga-dia">
                <div class="hr-vaga-data">${esc(v.dia)}, ${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}</div>
                <div class="hr-chips">${v.horarios.map(h => `<span class="hr-chip">${esc(h)}</span>`).join('')}</div>
            </div>`;
        }).join('');
}

/* ── Google Calendar ───────────────────────────────────────────────────────── */
function renderGoogleStatus(g) {
    const box = document.getElementById('agenda-google');
    if (!box) return;
    if (!g.configurado) {
        box.innerHTML = `<span class="muted google-chip-off" title="Para sincronizar, cadastre GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no Render.">Google Agenda: não configurado</span>`;
    } else if (!g.conectado) {
        // Destacado em ambar: desconectado, a Agenda nao sincroniza com o Google.
        box.innerHTML = `<a class="btn-secondary btn-sm google-conectar" href="/api/google/conectar"
            title="Google Agenda desconectado: os agendamentos não estão indo para o Google">
            <i class="google-conectar-ponto"></i>Conectar Google Agenda</a>`;
    } else {
        // So um selo: os detalhes abrem no clique, para nao poluir a Agenda.
        const a = g.atualizacao || {};
        box.innerHTML = `<details class="google-chip ${a.leitura_erro ? 'erro' : ''}">
            <summary title="Google Agenda conectado">${a.leitura_erro ? '⚠' : '<i class="google-chip-ponto"></i>'} Google Agenda</summary>
            <div class="google-pop">
                <div class="google-pop-conta">Sincronizado${g.email ? ` com <strong>${esc(g.email)}</strong>` : ''}</div>
                ${statusAtualizacaoGoogle(a)}
                <div class="muted agenda-legenda"><i class="leg-painel"></i>avaliações do painel <i class="leg-google"></i>marcados no Google</div>
                <div class="google-pop-acoes">
                    <button class="btn-secondary btn-sm" onclick="sincronizarGoogle()">Sincronizar agora</button>
                    <button class="btn-secondary btn-sm" onclick="desconectarGoogle()">Desconectar</button>
                </div>
            </div>
        </details>`;
    }
}

// Clique fora fecha os detalhes do Google.
document.addEventListener('click', e => {
    document.querySelectorAll('.google-chip[open]').forEach(d => { if (!d.contains(e.target)) d.open = false; });
});

// O que o Google marcar aparece sozinho? Mostra o motivo quando nao.
function statusAtualizacaoGoogle(a) {
    if (a.leitura_erro) {
        return `<span class="agenda-auto erro" title="${esc(a.leitura_erro)}">⚠ Não consegui ler o Google Agenda agora</span>`;
    }
    if (a.avisos_ativos) {
        return '<span class="agenda-auto ok">Atualização automática: instantânea</span>';
    }
    const motivo = a.avisos_erro ? ` (avisos do Google desligados: ${a.avisos_erro})` : '';
    return `<span class="agenda-auto" title="${esc(motivo)}">Atualização automática: a cada 20 s${a.avisos_erro ? ' ⓘ' : ''}</span>`;
}

async function sincronizarGoogle() {
    const botao = typeof event !== 'undefined' && event ? event.currentTarget : null;
    const rotulo = botao ? botao.textContent : '';
    if (botao) { botao.disabled = true; botao.classList.add('trabalhando'); botao.textContent = 'Sincronizando…'; }
    const r = await api('/api/google/sincronizar', { method: 'POST' })
        .finally(() => { if (botao) { botao.disabled = false; botao.classList.remove('trabalhando'); botao.textContent = rotulo; } });
    if (!r || r.error) { toast(friendlyError(r?.error || 'Erro ao sincronizar'), 'error'); return; }
    toast(r.erros && r.erros.length ? `Sincronizado com falhas: ${r.erros[0]}` : `Sincronizado (${r.enviados} novo(s))`,
          r.erros && r.erros.length ? 'error' : 'success');
    agendaCache.clear();
    loadAgenda();
}

async function desconectarGoogle() {
    const r = await api('/api/google/desconectar', { method: 'POST' });
    if (r && r.ok) { toast('Google Calendar desconectado. A agenda continua no painel.', 'success'); loadAgendaConfig(); }
}

function avisoRetornoGoogle() {
    const p = new URLSearchParams(location.search).get('google');
    if (!p) return;
    history.replaceState(null, '', location.pathname);
    const msgs = {
        conectado: ['Google Calendar conectado!', 'success'],
        cancelado: ['Conexão com o Google cancelada', 'info'],
        nao_configurado: ['Cadastre GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no Render antes de conectar', 'error'],
        erro: ['Não foi possível conectar ao Google Calendar', 'error'],
    };
    const [m, t] = msgs[p] || msgs.erro;
    toast(m, t);
    switchView('agenda');
}

/* ── Init ─────────────────────────────────────────────────────────────────── */
loadDashboard();
loadGlobalAgentMode();
connectSSE();
updateUnreadBadge();
updateAgendamentosBadge();
avisoRetornoGoogle();

// Pausa/retoma o polling de status da instância conforme a visibilidade da aba
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        if (currentView === 'whatsapp' && waStatusTimer) {
            clearInterval(waStatusTimer);
            waStatusTimer = null;
        }
    } else if (currentView === 'whatsapp') {
        loadWAConnection();
    }
});
setInterval(updateUnreadBadge, 30000);

/* ── Deseleccionar conversa al clicar fuera (como WhatsApp Web) ─────────── */
document.addEventListener('click', (e) => {
    // Cierra el menú de contexto en cualquier clic
    if (!e.target.closest('.ctx-menu')) closeContextMenu();
    // Não deseleciona ao clicar dentro do layout de conversação (lista, chat o detalhes),
    // nem dentro de overlays flotantes (toast, modal, loader, contexto).
    if (e.target.closest('.conv-layout')
        || e.target.closest('.ctx-menu')
        || e.target.closest('.toast-container')
        || e.target.closest('#modal-overlay')
        || e.target.closest('.media-lightbox')
        || e.target.closest('.sidebar')
        // Clique que veio de outra aba (ex.: "Abrir conversa" em Agendamentos)
        // e acabou de abrir a conversa: não pode fechá-la em seguida.
        || e.target.closest('.view:not(#view-conversations)')) return;
    if (currentConvId != null) deselectConversation();
});

/* ── ESC: cerrar modal → menú de templates → salir de la conversa ─────────── */
document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' && e.keyCode !== 27) return;
    const lb = document.getElementById('media-lightbox');
    if (lb && lb.classList.contains('open')) return;
    const overlay = document.getElementById('modal-overlay');
    if (overlay && overlay.style.display !== 'none') {
        closeModal();
        return;
    }
    const menu = document.getElementById('template-menu');
    if (menu && menu.style.display === 'flex') {
        closeTemplateMenu();
        return;
    }
    if (currentView === 'crm') {
        const profile = document.getElementById('crm-contact-profile');
        if (profile && profile.style.display !== 'none') {
            closeCrmContactProfile();
            return;
        }
    }
    if (currentView === 'knowledge') {
        if (currentKnowledgeFile != null) {
            deselectKnowledgeFile();
            return;
        }
    }
    if (currentConvId != null) {
        deselectConversation();
    }
});

/* ══════════════════════════════════════════════════════════════════════════════
   CRM
   ══════════════════════════════════════════════════════════════════════════════ */

let crmCurrentView = 'dashboard';
let crmContactProfileId = null;
// Cada troca de tela do CRM ganha um numero. Resposta que chega depois de o
// usuario ja ter ido para outra tela (ou outro contato) e descartada: era
// isso que fazia o contato antigo aparecer e depois trocar pelo novo.
let crmNavToken = 0;
let crmProfileReq = 0;

/* ── CRM Status Labels ─────────────────────────────────────────────────────── */
const CRM_STATUS = {
    novo: 'Novo', em_atendimento: 'Em Atendimento', agendamento: 'Agendamento Solicitado', cliente: 'Cliente',
    inativo: 'Inativo', nao_interessado: 'Nao Interessado'
};
const CRM_FOLLOWUP_STATUS = {
    pendente: 'Pendente', enviado: 'Enviado', cancelado: 'Cancelado', erro: 'Erro'
};
function crmStatusLabel(s) { return CRM_STATUS[s] || s || '-'; }
function crmFollowUpLabel(s) { return CRM_FOLLOWUP_STATUS[s] || s || '-'; }

/* ── CRM Navigation ────────────────────────────────────────────────────────── */
function switchCrmView(view) {
    document.querySelectorAll('.crm-nav-item').forEach(n => n.classList.remove('active'));
    document.querySelector(`.crm-nav-item[data-crm-view="${view}"]`).classList.add('active');
    document.querySelectorAll('.crm-subview').forEach(v => v.classList.remove('active'));
    document.getElementById(`crm-view-${view}`).classList.add('active');
    closeCrmContactProfile(false);
    crmCurrentView = view;
    crmNavToken++;
    loadCrmView(view);
}

function loadCrmView(view) {
    switch (view) {
        case 'dashboard': loadCrmDashboard(); break;
        case 'contacts': loadCrmContacts(); break;
        case 'automations': loadCrmAutomations(); break;
        case 'followups': loadCrmFollowUps(); break;
        case 'logs': loadCrmLogs(); break;
    }
}

/* ── CRM Dashboard ─────────────────────────────────────────────────────────── */
let crmDashboardCache = null;

async function loadCrmDashboard() {
    const tk = crmNavToken;
    const grid = document.getElementById('crm-stats-grid');
    // Ultimo resultado na tela na hora; os numeros novos chegam por cima.
    if (crmDashboardCache) renderCrmDashboard(crmDashboardCache);
    else grid.innerHTML = skeletonCards(7);
    let stats;
    try { stats = await api('/api/crm/dashboard'); } catch(e) { stats = null; }
    if (tk !== crmNavToken) return;
    if (!stats || stats.error) {
        if (!crmDashboardCache) grid.innerHTML = '<p class="muted">Erro ao carregar</p>';
        return;
    }
    crmDashboardCache = stats;
    renderCrmDashboard(stats);
}

function renderCrmDashboard(stats) {
    const grid = document.getElementById('crm-stats-grid');
    const fu = stats.follow_ups || {};
    grid.innerHTML = `
        <div class="stat-card">
            <div class="stat-icon"><svg viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>
            <div class="stat-value">${stats.total_contacts}</div>
            <div class="stat-label">Total Contatos</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon" style="color:#22c55e"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg></div>
            <div class="stat-value">${stats.novo}</div>
            <div class="stat-label">Novos</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon" style="color:#0ea5e9"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg></div>
            <div class="stat-value">${stats.agendamento || 0}</div>
            <div class="stat-label">Agendamentos a confirmar</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon" style="color:#6366f1"><svg viewBox="0 0 24 24"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72"/></svg></div>
            <div class="stat-value">${stats.cliente}</div>
            <div class="stat-label">Clientes</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon" style="color:#94a3b8"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg></div>
            <div class="stat-value">${stats.inativo}</div>
            <div class="stat-label">Inativos</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon" style="color:#f59e0b"><svg viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg></div>
            <div class="stat-value">${fu.pending || 0}</div>
            <div class="stat-label">Follow-ups Pendentes</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon" style="color:#22c55e"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div>
            <div class="stat-value">${fu.sent_today || 0}</div>
            <div class="stat-label">Enviados Hoje</div>
        </div>
    `;
}

/* ── CRM Contacts ──────────────────────────────────────────────────────────── */
let crmContactsList = [];
let crmContactsUrl = '';
let crmContactsReq = 0;

async function loadCrmContacts() {
    const list = document.getElementById('crm-contacts-list');
    const profile = document.getElementById('crm-contact-profile');
    if (profile) profile.style.display = 'none';
    list.style.display = 'block';

    const search = document.getElementById('crm-contact-search')?.value || '';
    const status = document.getElementById('crm-contact-status-filter')?.value || '';
    const days = document.getElementById('crm-contact-days-filter')?.value || '';
    const followUp = document.getElementById('crm-contact-followup-filter')?.value || '';

    let url = '/api/crm/contacts?limit=200';
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;
    if (days) url += `&days_without=${days}`;
    if (followUp) url += `&has_follow_up=${followUp}`;

    const tk = crmNavToken;
    const req = ++crmContactsReq;
    // Mesmo filtro da ultima vez: mostra a lista que ja temos e atualiza por
    // tras, em vez de esvaziar a tela a cada volta para a aba.
    if (url === crmContactsUrl && crmContactsList.length) renderCrmContacts();
    else list.innerHTML = skeletonRows(5);

    const res = await api(url);
    // Usuario mudou de tela, ou digitou de novo na busca: resposta velha.
    if (tk !== crmNavToken || req !== crmContactsReq) return;
    crmContactsList = res || [];
    crmContactsUrl = url;
    renderCrmContacts();
}

function renderCrmContacts() {
    const list = document.getElementById('crm-contacts-list');
    if (crmContactProfileId) return;  // perfil aberto: a lista fica escondida
    if (!crmContactsList || crmContactsList.length === 0) {
        list.innerHTML = '<div class="empty-state">Nenhum contato encontrado</div>';
        return;
    }

    list.innerHTML = `
        <div class="crm-table-container">
            <table class="crm-table crm-table-contatos">
                <thead><tr><th class="col-name">Nome</th><th class="col-phone">Telefone</th><th class="col-status">Status</th><th class="col-tags">Tags</th><th class="col-date">Ultima Interacao</th><th class="col-days">Dias s/ Interacao</th></tr></thead>
                <tbody>
                ${crmContactsList.map(c => {
                    const name = c.name || c.phone || '-';
                    const tags = (c.tags || []).map(t =>
                        `<span class="conv-tag-chip" style="background:${t.color}">${esc(t.name)}</span>`
                    ).join(' ');
                    const lastInt = c.last_interaction_at
                        ? new Date(c.last_interaction_at + 'Z').toLocaleDateString('pt-BR')
                        : '-';
                    const daysW = c.days_without_interaction != null ? c.days_without_interaction : '-';
                    return `<tr class="crm-contact-row" onclick="openCrmContactProfile(${c.id})">
                        <td><strong>${esc(name)}</strong></td>
                        <td>${esc(c.phone)}</td>
                        <td><span class="crm-status-badge crm-status-${c.crm_status || 'novo'}">${esc(crmStatusLabel(c.crm_status))}</span></td>
                        <td>${tags || '<span class="muted">-</span>'}</td>
                        <td>${lastInt}</td>
                        <td>${daysW}</td>
                    </tr>`;
                }).join('')}
                </tbody>
            </table>
        </div>
    `;
}

async function openCrmContactProfile(contactId) {
    const req = ++crmProfileReq;
    crmContactProfileId = contactId;
    const list = document.getElementById('crm-contacts-list');
    const profile = document.getElementById('crm-contact-profile');
    list.style.display = 'none';
    profile.style.display = 'block';

    // Troca de contato na hora: nada do contato anterior fica na tela.
    const daLista = (crmContactsList || []).find(c => c.id === contactId);
    document.getElementById('crm-profile-name').textContent =
        (daLista && (daLista.name || daLista.phone)) || 'Carregando...';
    document.getElementById('crm-profile-info').innerHTML =
        `<div class="crm-profile-card">${skeletonRows(4)}</div>`;
    document.getElementById('crm-profile-messages').innerHTML =
        `<h3>Historico de Mensagens</h3><div class="crm-messages-list">${skeletonRows(4)}</div>`;

    // Uma chamada so: o servidor ja manda tags, tarefas e mensagens juntos.
    const data = await api(`/api/crm/contacts/${contactId}`);
    if (req !== crmProfileReq) return;  // usuario ja abriu outro contato
    if (!data || data.error) {
        document.getElementById('crm-profile-info').innerHTML =
            '<div class="crm-profile-card"><p class="muted">Erro ao carregar contato</p></div>';
        document.getElementById('crm-profile-messages').innerHTML = '';
        return;
    }

    document.getElementById('crm-profile-name').textContent = data.name || data.phone || 'Contato';

    const tags = (data.tags || []).map(t =>
        `<span class="conv-tag-chip" style="background:${t.color}">${esc(t.name)} <button class="tag-chip-remove" onclick="event.stopPropagation();crmRemoveTag(${data.id},${t.id})" title="Remover">&times;</button></span>`
    ).join(' ');
    const lastInt = data.last_interaction_at
        ? new Date(data.last_interaction_at + 'Z').toLocaleString('pt-BR')
        : '-';
    const created = data.created_at
        ? new Date(data.created_at + 'Z').toLocaleString('pt-BR')
        : '-';
    const daysW = data.days_without_interaction != null ? data.days_without_interaction : '-';
    const tagOptions = (data.all_tags || []).filter(t => !(data.tags || []).some(tg => tg.id === t.id));

    document.getElementById('crm-profile-info').innerHTML = `
        <div class="crm-profile-card">
            <div class="crm-profile-field"><strong>Telefone:</strong> ${esc(data.phone)}</div>
            <div class="crm-profile-field"><strong>Email:</strong> ${esc(data.email || '-')}</div>
            <div class="crm-profile-field"><strong>Empresa:</strong> ${esc(data.company || '-')}</div>
            <div class="crm-profile-field"><strong>Primeiro contato:</strong> ${created}</div>
            <div class="crm-profile-field"><strong>Ultima interacao:</strong> ${lastInt}</div>
            <div class="crm-profile-field"><strong>Dias sem interacao:</strong> <span class="crm-days-badge">${daysW}</span></div>
            <div class="crm-profile-field">
                <strong>Status:</strong>
                <select class="select-sm" onchange="updateCrmContactStatus(${data.id}, this.value)">
                    ${Object.entries(CRM_STATUS).map(([k, v]) =>
                        `<option value="${k}" ${data.crm_status === k ? 'selected' : ''}>${v}</option>`
                    ).join('')}
                </select>
            </div>
            <div class="crm-profile-field">
                <strong>Tags:</strong>
                <div class="tag-chips">${tags || '<span class="muted">nenhuma</span>'}</div>
                <div style="margin-top:4px;display:flex;gap:4px">
                    <select class="select-sm" id="crm-tag-select-${data.id}">
                        <option value="">Adicionar tag...</option>
                        ${tagOptions.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join('')}
                    </select>
                    <button class="btn-sm btn-primary" onclick="crmAddTag(${data.id})">+</button>
                </div>
            </div>
            <div class="crm-profile-field">
                <strong>Observacoes:</strong>
                <textarea class="crm-notes-input" id="crm-notes-${data.id}" rows="3" placeholder="Observacoes internas...">${esc(data.notes || '')}</textarea>
                <button class="btn-sm btn-primary" style="margin-top:4px" onclick="saveCrmNotes(${data.id})">Salvar</button>
            </div>
        </div>
        ${(data.tasks || []).length > 0 ? `
        <div class="crm-profile-card">
            <h3>Tarefas</h3>
            ${data.tasks.map(t => `
                <div class="crm-task ${t.status === 'done' ? 'crm-task-done' : ''}">
                    <div class="crm-task-head">
                        <strong>${esc(t.title)}</strong>
                        ${t.status === 'done'
                            ? '<span class="muted">Concluída</span>'
                            : `<button class="btn-sm btn-primary" onclick="concluirCrmTask(${t.id}, ${data.id})">Concluir</button>`}
                    </div>
                    <pre class="crm-task-desc">${esc(t.description || '')}</pre>
                </div>
            `).join('')}
        </div>` : ''}
        ${(data.follow_ups || []).length > 0 ? `
        <div class="crm-profile-card">
            <h3>Follow-ups</h3>
            <table class="crm-mini-table">
                <thead><tr><th>Automacao</th><th>Previsto</th><th>Status</th></tr></thead>
                <tbody>
                ${data.follow_ups.map(fu => `
                    <tr>
                        <td>${esc(fu.automation_name)}</td>
                        <td>${new Date(fu.scheduled_for + 'Z').toLocaleString('pt-BR')}</td>
                        <td><span class="crm-fu-status-badge crm-fu-${fu.status}">${esc(crmFollowUpLabel(fu.status))}</span></td>
                    </tr>
                `).join('')}
                </tbody>
            </table>
        </div>` : ''}
    `;

    const msgs = data.messages || [];
    document.getElementById('crm-profile-messages').innerHTML = `<h3>Historico de Mensagens</h3><div class="crm-messages-list">${
        msgs.length ? msgs.map(m => {
            const time = m.created_at ? new Date(m.created_at + 'Z').toLocaleString('pt-BR', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
            const dir = m.direction === 'in' ? 'Recebido' : m.direction === 'out' ? 'Enviado' : 'Sistema';
            const dirClass = m.direction === 'in' ? 'crm-msg-in' : m.direction === 'out' ? 'crm-msg-out' : 'crm-msg-internal';
            return `<div class="crm-msg ${dirClass}"><div class="crm-msg-body">${esc(m.body)}</div><div class="crm-msg-meta">${dir} · ${time}</div></div>`;
        }).join('') : '<p class="muted">Nenhuma mensagem</p>'
    }</div>`;
}

async function concluirCrmTask(taskId, contactId) {
    const r = await api(`/api/tasks/${taskId}`, { method: 'PUT', body: JSON.stringify({ status: 'done' }) });
    if (r && r.ok) {
        toast('Tarefa concluída', 'success');
        openCrmContactProfile(contactId);
    } else {
        toast('Erro ao concluir tarefa', 'error');
    }
}

function closeCrmContactProfile(recarregar = true) {
    crmContactProfileId = null;
    crmProfileReq++;
    const list = document.getElementById('crm-contacts-list');
    const profile = document.getElementById('crm-contact-profile');
    if (profile) profile.style.display = 'none';
    if (list) list.style.display = 'block';
    // Na troca de aba quem carrega e o loadCrmView: recarregar aqui buscava a
    // lista de contatos ate para abrir a Visao Geral (e duas vezes em Contatos).
    if (recarregar) loadCrmContacts();
}

async function updateCrmContactStatus(contactId, status) {
    await api(`/api/crm/contacts/${contactId}/status`, { method: 'PUT', body: JSON.stringify({ status }) });
    toast('Status atualizado', 'success');
}

async function saveCrmNotes(contactId) {
    const textarea = document.getElementById(`crm-notes-${contactId}`);
    if (!textarea) return;
    const notes = textarea.value;
    await api(`/api/crm/contacts/${contactId}/notes`, { method: 'PUT', body: JSON.stringify({ notes }) });
    toast('Observacoes salvas', 'success');
}

async function crmAddTag(contactId) {
    const sel = document.getElementById(`crm-tag-select-${contactId}`);
    if (!sel || !sel.value) return;
    await api(`/api/contacts/${contactId}/tags`, { method: 'POST', body: JSON.stringify({ tag_id: parseInt(sel.value) }) });
    openCrmContactProfile(contactId);
}

async function crmRemoveTag(contactId, tagId) {
    await api(`/api/contacts/${contactId}/tags/${tagId}`, { method: 'DELETE' });
    openCrmContactProfile(contactId);
}

/* ── CRM Automations ───────────────────────────────────────────────────────── */
let crmAutomationsList = [];

async function loadCrmAutomations() {
    const list = document.getElementById('crm-automations-list');
    list.innerHTML = skeletonRows(3);
    const tk = crmNavToken;
    const automacoes = await api('/api/crm/automations');
    if (tk !== crmNavToken) return;
    crmAutomationsList = automacoes;
    if (!crmAutomationsList || crmAutomationsList.length === 0) {
        list.innerHTML = '<div class="empty-state">Nenhuma automacao criada</div>';
        return;
    }
    list.innerHTML = crmAutomationsList.map(a => {
        const timeDesc = [];
        if (a.days > 0) timeDesc.push(`${a.days} dia(s)`);
        if (a.hours > 0) timeDesc.push(`${a.hours} hora(s)`);
        return `
        <div class="crm-automation-card">
            <div class="crm-automation-header">
                <div>
                    <h3>${esc(a.name)}</h3>
                    <span class="crm-auto-time">Apos ${timeDesc.join(' e ') || '0'} sem interacao</span>
                </div>
                <label class="agent-toggle">
                    <input type="checkbox" ${a.is_active ? 'checked' : ''} onchange="toggleCrmAutomation(${a.id})">
                    <span class="agent-toggle-slider"></span>
                </label>
            </div>
            <div class="crm-automation-body">
                <div class="crm-auto-field"><strong>Mensagem:</strong> <span class="crm-auto-msg">${esc(a.message_template || '(template Meta)')}</span></div>
                <div class="crm-auto-field"><strong>Janela:</strong> ${esc(a.send_window_start)} - ${esc(a.send_window_end)}</div>
                ${a.action_tag_add ? `<div class="crm-auto-field"><strong>Ao enviar:</strong> Adicionar tag #${esc(a.action_tag_add)}</div>` : ''}
                ${a.action_status_change ? `<div class="crm-auto-field"><strong>Ao enviar:</strong> Status -> ${esc(crmStatusLabel(a.action_status_change))}</div>` : ''}
            </div>
            <div class="crm-automation-actions">
                <button class="btn-sm btn-secondary" onclick="editCrmAutomation(${a.id})">Editar</button>
                <button class="btn-sm btn-danger" onclick="deleteCrmAutomation(${a.id})">Excluir</button>
            </div>
        </div>`;
    }).join('');
}

async function toggleCrmAutomation(autoId) {
    await api(`/api/crm/automations/${autoId}/toggle`, { method: 'PUT' });
    loadCrmAutomations();
}

async function showCrmAutomationForm(auto = null) {
    const title = auto ? 'Editar Automacao' : 'Nova Automacao';
    document.getElementById('modal-title').textContent = title;

    let metaTemplatesHtml = `<input name="meta_template_name" value="${esc(auto?.meta_template_name || '')}" placeholder="ex: follow_up_30d">`;
    try {
        const tplData = await api('/api/whatsapp/templates');
        if (tplData && !tplData.error) {
            const raw = tplData.data || tplData;
            const items = Array.isArray(raw) ? raw : (raw.data || []);
            const approved = items.filter(t => t.status === 'APPROVED');
            if (approved.length > 0) {
                metaTemplatesHtml = `<select name="meta_template_name">
                    <option value="">Selecione um template...</option>
                    ${approved.map(t => `<option value="${esc(t.name)}" ${auto?.meta_template_name === t.name ? 'selected' : ''}>${esc(t.name)} (${esc(t.language)})</option>`).join('')}
                </select>
                <p style="font-size:11px;color:var(--muted);margin:4px 0 0 0">Templates aprovados pela Meta. Crie novos em WhatsApp > Templates Meta.</p>`;
            }
        }
    } catch(e) {}

    // Tags em lista: antes era preciso digitar o ID numerico a mao.
    let tags = [];
    try {
        const r = await api('/api/tags');
        if (Array.isArray(r)) tags = r;
    } catch(e) {}
    const opcoesTag = (selecionada) => `<option value="">Nenhuma</option>` +
        tags.map(tg => `<option value="${tg.id}" ${String(selecionada) === String(tg.id) ? 'selected' : ''}>${esc(tg.name)}</option>`).join('');

    document.getElementById('modal-body').innerHTML = `
        <form onsubmit="saveCrmAutomation(event, ${auto?.id || 'null'})">
            <div class="form-group"><label>Nome</label><input name="name" value="${esc(auto?.name || '')}" required></div>
            <div class="form-row">
                <div class="form-group"><label>Dias</label><input type="number" name="days" value="${auto?.days || 0}" min="0" oninput="avisarJanela24h(this.form)"></div>
                <div class="form-group"><label>Horas</label><input type="number" name="hours" value="${auto?.hours || 0}" min="0" max="23" oninput="avisarJanela24h(this.form)"></div>
            </div>
            <div id="aviso-24h" class="form-aviso" style="display:none;background:#fff4e5;border:1px solid #ffb74d;border-radius:6px;padding:8px 10px;margin-bottom:12px;font-size:12px;line-height:1.45"></div>
            <div class="form-group"><label>Mensagem (use {{nome}} e {{numero}})</label><textarea name="message_template" rows="4" placeholder="Ola, {{nome}}! Tudo bem?">${esc(auto?.message_template || '')}</textarea></div>
            <div class="form-group">
                <label><input type="checkbox" name="use_meta_template" value="1" ${auto?.use_meta_template ? 'checked' : ''} onchange="avisarJanela24h(this.form)"> Usar template aprovado pela Meta</label>
            </div>
            <div class="form-group"><label>Template Meta</label>${metaTemplatesHtml}</div>
            <div class="form-row">
                <div class="form-group"><label>Horario inicio</label><input type="time" name="send_window_start" value="${esc(auto?.send_window_start || '08:00')}" required></div>
                <div class="form-group"><label>Horario fim</label><input type="time" name="send_window_end" value="${esc(auto?.send_window_end || '18:00')}" required></div>
            </div>
            <p style="font-size:11px;color:var(--muted);margin:-8px 0 12px 0">Janela no horário local do consultório (TZ_OFFSET_HORAS).</p>
            <div class="form-row">
                <div class="form-group"><label>Ao enviar: adicionar tag</label>
                    <select name="action_tag_add">${opcoesTag(auto?.action_tag_add)}</select>
                </div>
                <div class="form-group"><label>Ao enviar: remover tag</label>
                    <select name="action_tag_remove">${opcoesTag(auto?.action_tag_remove)}</select>
                </div>
            </div>
            <div class="form-group"><label>Ao enviar: Alterar status para</label>
                <select name="action_status_change">
                    <option value="">Nao alterar</option>
                    ${Object.entries(CRM_STATUS).map(([k, v]) =>
                        `<option value="${k}" ${auto?.action_status_change === k ? 'selected' : ''}>${v}</option>`
                    ).join('')}
                </select>
            </div>
            <button type="submit" class="btn-primary">Salvar</button>
        </form>`;
    document.getElementById('modal-overlay').style.display = 'flex';
    avisarJanela24h(document.querySelector('#modal-body form'));
}

// Fora da janela de 24h do WhatsApp so template aprovado e entregue. Avisar no
// formulario evita descobrir isso dias depois, num log de erro.
function avisarJanela24h(form) {
    if (!form) return;
    const aviso = document.getElementById('aviso-24h');
    if (!aviso) return;
    const dias = parseInt(form.days?.value) || 0;
    const horas = parseInt(form.hours?.value) || 0;
    const total = dias * 24 + horas;
    const usaTemplate = form.use_meta_template?.checked && (form.meta_template_name?.value || '').trim();
    if (total >= 24 && !usaTemplate) {
        aviso.innerHTML = `<strong>Precisa de template aprovado.</strong> Esta automacao dispara ${total}h depois da ultima interacao, fora da janela de 24 horas do WhatsApp. Nesse prazo a Meta so entrega template aprovado — marque a opcao abaixo e escolha um template, ou reduza o prazo.`;
        aviso.style.display = 'block';
    } else {
        aviso.style.display = 'none';
    }
}

async function saveCrmAutomation(e, id) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const fd = new FormData(form);
    const data = {};
    fd.forEach((v, k) => {
        if (k === 'use_meta_template') data[k] = 1;
        else if (k === 'days' || k === 'hours') data[k] = parseInt(v) || 0;
        else data[k] = v;
    });
    setBtnLoading(btn, true, 'Salvando...');
    // Conferir a resposta: o backend recusa automacao de 24h+ sem template, e
    // antes a tela dizia "criada" mesmo quando nada tinha sido salvo.
    const resp = id
        ? await api(`/api/crm/automations/${id}`, { method: 'PUT', body: JSON.stringify(data) })
        : await api('/api/crm/automations', { method: 'POST', body: JSON.stringify(data) });
    setBtnLoading(btn, false);
    if (!resp || resp.error) {
        toast(friendlyError(resp?.error || 'Falha ao salvar automacao'), 'error');
        return;
    }
    toast(id ? 'Automacao atualizada' : 'Automacao criada', 'success');
    closeModal();
    loadCrmAutomations();
}

async function editCrmAutomation(autoId) {
    const auto = crmAutomationsList.find(a => a.id === autoId);
    if (auto) showCrmAutomationForm(auto);
}

async function deleteCrmAutomation(autoId) {
    if (!confirm('Excluir esta automacao? Follow-ups pendentes serao cancelados.')) return;
    await api(`/api/crm/automations/${autoId}`, { method: 'DELETE' });
    toast('Automacao excluida', 'success');
    loadCrmAutomations();
}

/* ── CRM Follow-ups ────────────────────────────────────────────────────────── */
async function loadCrmFollowUps() {
    const list = document.getElementById('crm-followups-list');
    list.innerHTML = skeletonRows(4);
    const status = document.getElementById('crm-followup-status-filter')?.value || '';
    let url = '/api/crm/follow-ups?limit=200';
    if (status) url += `&status=${status}`;
    const tk = crmNavToken;
    const followUps = await api(url);
    if (tk !== crmNavToken) return;
    if (!followUps || followUps.length === 0) {
        list.innerHTML = '<div class="empty-state">Nenhum follow-up encontrado</div>';
        return;
    }
    list.innerHTML = `
        <div class="crm-table-container">
            <table class="crm-table">
                <thead><tr><th class="col-name">Contato</th><th>Automacao</th><th class="col-date">Data Prevista</th><th class="col-msg">Mensagem</th><th class="col-status">Status</th></tr></thead>
                <tbody>
                ${followUps.map(fu => {
                    const sched = fu.scheduled_for ? new Date(fu.scheduled_for + 'Z').toLocaleString('pt-BR') : '-';
                    const msg = (fu.message_sent || fu.message_template || '').substring(0, 60);
                    return `<tr>
                        <td><strong>${esc(fu.contact_name || fu.contact_phone)}</strong><br><span class="muted">${esc(fu.contact_phone)}</span></td>
                        <td>${esc(fu.automation_name)}</td>
                        <td>${sched}</td>
                        <td title="${esc(msg)}">${esc(msg)}</td>
                        <td><span class="crm-fu-status-badge crm-fu-${fu.status}">${esc(crmFollowUpLabel(fu.status))}</span></td>
                    </tr>`;
                }).join('')}
                </tbody>
            </table>
        </div>
    `;
}

/* ── CRM Logs ──────────────────────────────────────────────────────────────── */
async function loadCrmLogs() {
    const list = document.getElementById('crm-logs-list');
    list.innerHTML = skeletonRows(4);
    const tk = crmNavToken;
    const logs = await api('/api/crm/logs?limit=200');
    if (tk !== crmNavToken) return;
    if (!logs || logs.length === 0) {
        list.innerHTML = '<div class="empty-state">Nenhum log registrado</div>';
        return;
    }
    list.innerHTML = `
        <div class="crm-table-container">
            <table class="crm-table">
                <thead><tr><th class="col-date">Data/Hora</th><th class="col-name">Contato</th><th>Automacao</th><th class="col-action">Acao</th><th class="col-msg">Mensagem</th><th class="col-result">Resultado</th><th class="col-error">Erro</th></tr></thead>
                <tbody>
                ${logs.map(l => {
                    const dt = l.created_at ? new Date(l.created_at + 'Z').toLocaleString('pt-BR') : '-';
                    return `<tr>
                        <td>${dt}</td>
                        <td>${esc(l.contact_name || l.contact_phone || '-')}</td>
                        <td>${esc(l.automation_name || '-')}</td>
                        <td>${esc(l.action)}</td>
                        <td title="${esc(l.message)}">${esc(l.message)}</td>
                        <td><span class="crm-fu-status-badge crm-fu-${l.result === 'enviado' ? 'enviado' : l.result === 'erro' ? 'erro' : ''}">${esc(l.result)}</span></td>
                        <td title="${esc(l.error)}">${esc(l.error)}</td>
                    </tr>`;
                }).join('')}
                </tbody>
            </table>
        </div>
    `;
}

/* ── Chat Media Send ────────────────────────────────────────────────────── */
let _selectedMedia = null;
let _selectedMediaType = null;

// Abre seletor de arquivo para mídia
function selectMedia(type) {
    const inputMap = {
        'image': 'chat-image-input',
        'video': 'chat-video-input',
        'audio': 'chat-audio-input',
        'document': 'chat-doc-input'
    };
    
    const input = document.getElementById(inputMap[type]);
    if (input) {
        input.click();
    }
}

// Processa seleção de arquivo de mídia
function handleMediaSelect(event, type) {
    const file = event.target.files[0];
    if (!file) return;
    
    // Valida tamanho (max 16MB)
    const maxSize = 16 * 1024 * 1024;
    if (file.size > maxSize) {
        toast('Arquivo muito grande (maximo 16MB)', 'error');
        event.target.value = '';
        return;
    }
    
    _selectedMedia = file;
    _selectedMediaType = type;
    
    closeMediaMenu();
    showMediaPreview(file, type);
    
    // Limpa input para permitir selecionar o mesmo arquivo novamente
    event.target.value = '';
}

// Mostra preview da mídia selecionada
function showMediaPreview(file, type) {
    const previewContainer = document.getElementById('chat-media-preview');
    if (!previewContainer) return;
    
    const reader = new FileReader();
    
    reader.onload = function(e) {
        let previewHtml = '';
        
        if (type === 'image') {
            previewHtml = `
                <img src="${e.target.result}" alt="Preview">
                <div class="file-info">
                    <div class="file-name">${esc(file.name)}</div>
                    <div class="file-size">${formatFileSize(file.size)}</div>
                </div>
            `;
        } else if (type === 'video') {
            previewHtml = `
                <video src="${e.target.result}" muted></video>
                <div class="file-info">
                    <div class="file-name">${esc(file.name)}</div>
                    <div class="file-size">${formatFileSize(file.size)}</div>
                </div>
            `;
        } else if (type === 'audio') {
            previewHtml = `
                <div class="file-icon">
                    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>
                </div>
                <div class="file-info">
                    <div class="file-name">${esc(file.name)}</div>
                    <div class="file-size">${formatFileSize(file.size)}</div>
                </div>
            `;
        } else {
            // Documento
            const ext = file.name.split('.').pop().toLowerCase();
            const iconColor = ext === 'pdf' ? '#ef4444' : ext === 'doc' || ext === 'docx' ? '#3b82f6' : '#22c55e';
            previewHtml = `
                <div class="file-icon" style="color:${iconColor}">
                    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                </div>
                <div class="file-info">
                    <div class="file-name">${esc(file.name)}</div>
                    <div class="file-size">${formatFileSize(file.size)}</div>
                </div>
            `;
        }
        
        previewHtml += `
            <button class="remove-media" onclick="event.stopPropagation(); removeSelectedMedia()" title="Remover">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
        `;
        
        previewContainer.innerHTML = previewHtml;
        previewContainer.style.display = 'flex';
        previewContainer.onclick = (e) => e.stopPropagation();
    };
    
    if (type === 'image' || type === 'video') {
        reader.readAsDataURL(file);
    } else {
        // Para áudio e documentos, mostra apenas info do arquivo
        reader.onload = function() {
            let previewHtml = '';
            if (type === 'audio') {
                previewHtml = `
                    <div class="file-icon">
                        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>
                    </div>
                    <div class="file-info">
                        <div class="file-name">${esc(file.name)}</div>
                        <div class="file-size">${formatFileSize(file.size)}</div>
                    </div>
                    <button class="remove-media" onclick="event.stopPropagation(); removeSelectedMedia()" title="Remover">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                `;
            } else {
                const ext = file.name.split('.').pop().toLowerCase();
                const iconColor = ext === 'pdf' ? '#ef4444' : ext === 'doc' || ext === 'docx' ? '#3b82f6' : '#22c55e';
                previewHtml = `
                    <div class="file-icon" style="color:${iconColor}">
                        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                    </div>
                    <div class="file-info">
                        <div class="file-name">${esc(file.name)}</div>
                        <div class="file-size">${formatFileSize(file.size)}</div>
                    </div>
                    <button class="remove-media" onclick="event.stopPropagation(); removeSelectedMedia()" title="Remover">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                `;
            }
            previewContainer.innerHTML = previewHtml;
            previewContainer.style.display = 'flex';
            previewContainer.onclick = (e) => e.stopPropagation();
        };
        reader.readAsDataURL(file);
    }
}

// Remove mídia selecionada
function removeSelectedMedia() {
    _selectedMedia = null;
    _selectedMediaType = null;
    const preview = document.getElementById('chat-media-preview');
    if (preview) {
        preview.style.display = 'none';
        preview.innerHTML = '';
    }
}

// Formata tamanho do arquivo
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Envia mídia selecionada
async function sendMediaMessage() {
    if (!_selectedMedia || !currentConvId) return;
    
    const conv = conversations.find(c => c.id === currentConvId);
    if (!conv) return;
    
    const btn = document.getElementById('chat-send');
    setBtnLoading(btn, true, 'Enviando...');
    
    try {
        const formData = new FormData();
        formData.append('media', _selectedMedia);
        formData.append('phone', conv.contact_phone);
        formData.append('type', _selectedMediaType);
        
        // Adiciona caption se houver texto
        const input = document.getElementById('chat-input');
        const caption = input.value.trim();
        if (caption) {
            formData.append('caption', caption);
        }
        
        // Mensagem optimistic
        const tempId = 'temp-media-' + Date.now();
        const mediaLabel = {
            'image': '[Imagem]',
            'video': '[Video]',
            'audio': '[Audio]',
            'document': '[Documento]'
        }[_selectedMediaType] || '[Midia]';
        
        appendMessage({
            id: tempId,
            direction: 'out',
            sender: 'Atendente',
            body: caption || mediaLabel,
            status: 'sending',
            msg_type: _selectedMediaType,
            created_at: new Date().toISOString(),
            uazapi_id: '',
        });
        
        // Limpa seleção
        removeSelectedMedia();
        if (caption) {
            input.value = '';
            autoResizeChatInput();
        }
        
        const res = await fetch('/api/messages/send-media', {
            method: 'POST',
            body: formData
        });
        
        const data = await res.json();
        
        if (!res.ok || data.error) {
            markTempMsgError(tempId);
            toast(data?.error || 'Erro ao enviar midia', 'error');
            return;
        }
        
        toast('Midia enviada', 'success');
        setTimeout(() => markTempMsgSent(tempId), 1500);
        
        // Atualiza o data-media-dbid para o ID real do banco
        if (data.db_msg_id) {
            const tempEl = document.querySelector(`#chat-messages .msg[data-msg-id="${tempId}"]`);
            if (tempEl) {
                tempEl.setAttribute('data-msg-id', String(data.db_msg_id));
                const mediaBox = tempEl.querySelector('.msg-media-lazy');
                if (mediaBox) {
                    mediaBox.setAttribute('data-media-dbid', String(data.db_msg_id));
                    mediaBox.dataset.state = '';
                    bindMsgMedia(tempEl);
                }
            }
        }
        
    } catch (e) {
        toast('Erro ao enviar midia', 'error');
    } finally {
        setBtnLoading(btn, false);
    }
}

// Modifica sendMessage para verificar se há mídia selecionada
const _originalSendMessage = sendMessage;
sendMessage = async function() {
    if (_selectedMedia) {
        await sendMediaMessage();
        return;
    }
    await _originalSendMessage();
};

/* ── Media Dropdown Menu ────────────────────────────────────────────────── */
function toggleMediaMenu(e) {
    e.stopPropagation();
    const dropdown = document.getElementById('chat-media-dropdown');
    const btn = document.getElementById('chat-media-menu-btn');
    
    if (!dropdown || !btn) return;
    
    const isOpen = dropdown.style.display !== 'none';
    
    if (isOpen) {
        dropdown.style.display = 'none';
        btn.classList.remove('active');
    } else {
        dropdown.style.display = 'block';
        btn.classList.add('active');
    }
}

function closeMediaMenu() {
    const dropdown = document.getElementById('chat-media-dropdown');
    const btn = document.getElementById('chat-media-menu-btn');
    
    if (dropdown) dropdown.style.display = 'none';
    if (btn) btn.classList.remove('active');
}

// Fecha o dropdown de mídia ao clicar fora
document.addEventListener('click', (e) => {
    const wrapper = document.querySelector('.chat-media-dropdown-wrapper');
    if (wrapper && !wrapper.contains(e.target)) {
        closeMediaMenu();
    }
});

// Fecha o dropdown de mídia ao pressionar Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeMediaMenu();
    }
});

/* ── Audio Recording ────────────────────────────────────────────────────── */
let _mediaRecorder = null;
let _audioChunks = [];
let _isRecording = false;
let _recordingStartTime = 0;
let _recordingTimer = null;
let _audioStream = null;

async function toggleAudioRecording() {
    if (_isRecording) {
        stopAudioRecording(true);
    } else {
        await startAudioRecording();
    }
}

async function startAudioRecording() {
    try {
        _audioStream = await navigator.mediaDevices.getUserMedia({ 
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                sampleRate: 44100
            } 
        });
        
        const mimeType = MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')
            ? 'audio/ogg;codecs=opus'
            : MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                ? 'audio/webm;codecs=opus'
                : 'audio/webm';
        
        _mediaRecorder = new MediaRecorder(_audioStream, { mimeType });
        _audioChunks = [];
        
        _mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) {
                _audioChunks.push(e.data);
            }
        };
        
        _mediaRecorder.onstop = () => {
            if (_audioChunks.length > 0) {
                const audioBlob = new Blob(_audioChunks, { type: mimeType });
                showRecordedAudioPreview(audioBlob);
            }
        };
        
        _mediaRecorder.start(100);
        _isRecording = true;
        _recordingStartTime = Date.now();
        
        const btn = document.getElementById('chat-record-btn');
        if (btn) btn.classList.add('recording');
        
        showRecordingPanel();
        startRecordingTimer();
        
    } catch (err) {
        console.error('Erro ao acessar microfone:', err);
        toast('Nao foi possivel acessar o microfone. Verifique as permissoes do navegador.', 'error');
    }
}

function stopAudioRecording(send = false) {
    _isRecording = false;
    
    if (_mediaRecorder && _mediaRecorder.state !== 'inactive') {
        _mediaRecorder.stop();
    }
    
    if (_audioStream) {
        _audioStream.getTracks().forEach(track => track.stop());
        _audioStream = null;
    }
    
    const btn = document.getElementById('chat-record-btn');
    if (btn) btn.classList.remove('recording');
    
    stopRecordingTimer();
    
    if (!send) {
        hideRecordingPanel();
    }
}

function showRecordingPanel() {
    const previewContainer = document.getElementById('chat-media-preview');
    if (!previewContainer) return;
    
    previewContainer.innerHTML = `
        <div class="audio-recording-panel">
            <div class="recording-indicator">
                <div class="rec-dot"></div>
                <span class="recording-time" id="recording-time">0:00</span>
            </div>
            <div class="recording-wave">
                <div class="wave-bar"></div>
                <div class="wave-bar"></div>
                <div class="wave-bar"></div>
                <div class="wave-bar"></div>
                <div class="wave-bar"></div>
            </div>
            <button class="cancel-recording" onclick="cancelAudioRecording()" title="Cancelar">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
            <button class="send-recording" onclick="stopAndSendRecording()" title="Enviar audio">
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            </button>
        </div>
    `;
    previewContainer.style.display = 'flex';
    previewContainer.onclick = (e) => e.stopPropagation();
}

function hideRecordingPanel() {
    const previewContainer = document.getElementById('chat-media-preview');
    if (previewContainer) {
        previewContainer.style.display = 'none';
        previewContainer.innerHTML = '';
    }
}

function startRecordingTimer() {
    _recordingTimer = setInterval(() => {
        const elapsed = Math.floor((Date.now() - _recordingStartTime) / 1000);
        const minutes = Math.floor(elapsed / 60);
        const seconds = elapsed % 60;
        const timeEl = document.getElementById('recording-time');
        if (timeEl) {
            timeEl.textContent = `${minutes}:${String(seconds).padStart(2, '0')}`;
        }
    }, 1000);
}

function stopRecordingTimer() {
    if (_recordingTimer) {
        clearInterval(_recordingTimer);
        _recordingTimer = null;
    }
}

function cancelAudioRecording() {
    _audioChunks = [];
    stopAudioRecording(false);
    hideRecordingPanel();
    toast('Gravacao cancelada', 'info');
}

let _recordedAudioBlob = null;
let _sendAfterRecord = false;

function showRecordedAudioPreview(audioBlob) {
    _recordedAudioBlob = audioBlob;
    
    const previewContainer = document.getElementById('chat-media-preview');
    if (!previewContainer) return;
    
    const audioUrl = URL.createObjectURL(audioBlob);
    
    previewContainer.innerHTML = `
        <div class="audio-recording-panel" style="background:rgba(99,102,241,0.1);border-color:rgba(99,102,241,0.2)">
            <div class="recording-indicator">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#6366f1" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>
                <span class="recording-time" style="color:var(--accent)">Audio gravado</span>
            </div>
            <audio id="recorded-audio-preview" src="${audioUrl}" controls style="flex:1;height:32px"></audio>
            <button class="cancel-recording" onclick="discardRecordedAudio()" title="Descartar">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
            <button class="send-recording" onclick="sendRecordedAudio()" title="Enviar audio">
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            </button>
        </div>
    `;
    previewContainer.style.display = 'flex';
    previewContainer.onclick = (e) => e.stopPropagation();
    
    if (_sendAfterRecord) {
        _sendAfterRecord = false;
        setTimeout(() => sendRecordedAudio(), 100);
    }
}

function discardRecordedAudio() {
    _recordedAudioBlob = null;
    hideRecordingPanel();
}

function stopAndSendRecording() {
    if (!_isRecording) {
        sendRecordedAudio();
        return;
    }
    _sendAfterRecord = true;
    stopAudioRecording(true);
}

async function sendRecordedAudio() {
    if (!_recordedAudioBlob || !currentConvId) {
        toast('Nenhum audio para enviar', 'error');
        return;
    }
    
    const conv = conversations.find(c => c.id === currentConvId);
    if (!conv) return;
    
    const audioBlob = _recordedAudioBlob;
    
    const btn = document.getElementById('chat-send');
    setBtnLoading(btn, true, 'Enviando...');
    
    try {
        const tempId = 'temp-audio-' + Date.now();
        appendMessage({
            id: tempId,
            direction: 'out',
            sender: 'Atendente',
            body: '[Audio]',
            status: 'sending',
            msg_type: 'audio',
            created_at: new Date().toISOString(),
            uazapi_id: '',
        });
        
        _recordedAudioBlob = null;
        hideRecordingPanel();
        
        const formData = new FormData();
        const ext = audioBlob.type.includes('ogg') ? 'ogg' : 'webm';
        const audioFile = new File([audioBlob], `audio.${ext}`, { type: audioBlob.type });
        formData.append('media', audioFile);
        formData.append('phone', conv.contact_phone);
        formData.append('type', 'audio');
        
        const res = await fetch('/api/messages/send-media', {
            method: 'POST',
            body: formData
        });
        
        const data = await res.json();
        
        if (!res.ok || data.error) {
            markTempMsgError(tempId);
            toast(data?.error || 'Erro ao enviar audio', 'error');
            return;
        }
        
        toast('Audio enviado', 'success');
        setTimeout(() => markTempMsgSent(tempId), 1500);
        
        if (data.db_msg_id) {
            const tempEl = document.querySelector(`#chat-messages .msg[data-msg-id="${tempId}"]`);
            if (tempEl) {
                tempEl.setAttribute('data-msg-id', String(data.db_msg_id));
                const mediaBox = tempEl.querySelector('.msg-media-lazy');
                if (mediaBox) {
                    mediaBox.setAttribute('data-media-dbid', String(data.db_msg_id));
                    mediaBox.dataset.state = '';
                    bindMsgMedia(tempEl);
                }
            }
        }
        
    } catch (e) {
        toast('Erro ao enviar audio', 'error');
    } finally {
        setBtnLoading(btn, false);
    }
}

function formatRecordingDuration(blob) {
    return 'gravando...';
}
