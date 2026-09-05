/**
 * iLumina Application Entry Point (ChatGPT Architecture)
 */

import { API } from './api.js';
import { UI } from './ui.js';
import { ChatController } from './chat.js';
import { Knowledge } from './knowledge.js';

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Initialize UI & Modals
    UI.init();

    // 2. Initialize Knowledge Base & Preload Documents
    Knowledge.init(API);
    Knowledge.loadDocuments();

    // 3. Initialize Central Chat Controller
    let currentMode = 'chat';
    let currentSessionId = `sess_chat_${Date.now()}`;

    const chatController = new ChatController(
        API,
        'chatgpt-prompt-form',
        'prompt-textarea',
        'chat-messages-list',
        'greeting-container',
        'messages-viewport',
        currentMode,
        currentSessionId
    );

    // Sync Knowledge Space Updates with Chat Controller
    document.addEventListener('knowledge:space-updated', (e) => {
        chatController.setSpaceId(e.detail.spaceId);
    });

    // 4. Mode-Filtered Sidebar History Management
    const sessionList = document.getElementById('session-list');
    const newChatBtn = document.getElementById('new-chat-btn');
    const topNewChatBtn = document.getElementById('top-new-chat-btn');
    const reloadSessionBtn = document.getElementById('reload-session-btn');
    const searchHistoryBtn = document.getElementById('search-history-btn');
    const chatSearchContainer = document.getElementById('chat-search-container');
    const chatSearchInput = document.getElementById('chat-search-input');

    let allModeChats = [];

    const renderHistoryList = async (mode) => {
        currentMode = mode;
        chatController.setMode(mode);

        try {
            allModeChats = await API.getChats(mode);
        } catch (e) {
            allModeChats = [];
        }

        filterAndRenderHistory(chatSearchInput ? chatSearchInput.value : '');
    };

    const filterAndRenderHistory = (filterQuery = '') => {
        if (!sessionList) return;
        sessionList.innerHTML = '';

        let chats = allModeChats;
        if (filterQuery.trim()) {
            const q = filterQuery.toLowerCase().trim();
            chats = chats.filter(c => (c.title || 'New Conversation').toLowerCase().includes(q));
        }

        if (!chats || chats.length === 0) {
            sessionList.innerHTML = '<li style="color:var(--text-muted); font-size:12px; text-align:center; padding: 20px 0;">No recents in this mode</li>';
            return;
        }

        chats.forEach(chat => {
            const li = document.createElement('li');
            li.className = `session-item ${chat.id === chatController.sessionId ? 'active' : ''}`;

            const titleSpan = document.createElement('span');
            titleSpan.className = 'session-item-title';
            titleSpan.innerText = chat.title || 'New Conversation';
            titleSpan.title = chat.title || 'New Conversation';

            const renameBtn = document.createElement('button');
            renameBtn.className = 'hover-action-btn';
            renameBtn.title = 'Rename chat';
            renameBtn.innerHTML = '<i class="ph ph-dots-three"></i>';
            renameBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                titleSpan.contentEditable = true;
                titleSpan.focus();
                
                const range = document.createRange();
                range.selectNodeContents(titleSpan);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
                
                const saveTitle = async () => {
                    titleSpan.contentEditable = false;
                    const newTitle = titleSpan.innerText.trim();
                    if (newTitle && newTitle !== chat.title) {
                        chat.title = newTitle;
                        await API.updateChatTitle(chat.id, newTitle);
                    } else {
                        titleSpan.innerText = chat.title || 'New Conversation';
                    }
                };
                
                titleSpan.onblur = saveTitle;
                titleSpan.onkeydown = (ev) => {
                    if (ev.key === 'Enter') {
                        ev.preventDefault();
                        titleSpan.blur();
                    }
                };
            });

            const delBtn = document.createElement('button');
            delBtn.className = 'hover-action-btn delete-action-btn';
            delBtn.title = 'Delete chat';
            delBtn.innerHTML = '<i class="ph ph-trash"></i>';
            delBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                await API.deleteChat(chat.id);
                if (chat.id === chatController.sessionId) {
                    startNewChat(currentMode);
                } else {
                    renderHistoryList(currentMode);
                }
            });

            li.appendChild(titleSpan);
            li.appendChild(renameBtn);
            li.appendChild(delBtn);

            li.addEventListener('click', async () => {
                await chatController.setSessionId(chat.id);

                if (mode === 'documents') {
                    // Fetch detailed history to get selected docs info
                    const historyData = await API.getChatHistory(chat.id);
                    if (historyData && historyData.space_id && historyData.selected_doc_count > 0) {
                        Knowledge.restoreFromSpace(
                            historyData.space_id,
                            historyData.selected_doc_count,
                            historyData.selected_documents || []
                        );
                        chatController.setSpaceId(historyData.space_id);
                    } else {
                        Knowledge.clearSelectionAndContext();
                        chatController.setSpaceId(null);
                    }
                }

                // Highlight active in list
                document.querySelectorAll('.session-item').forEach(item => item.classList.remove('active'));
                li.classList.add('active');
            });

            sessionList.appendChild(li);
        });
    };

    // Toggle history search bar
    if (searchHistoryBtn && chatSearchContainer && chatSearchInput) {
        searchHistoryBtn.addEventListener('click', () => {
            chatSearchContainer.classList.toggle('hidden');
            if (!chatSearchContainer.classList.contains('hidden')) {
                chatSearchInput.focus();
            } else {
                chatSearchInput.value = '';
                filterAndRenderHistory('');
            }
        });

        chatSearchInput.addEventListener('input', (e) => {
            filterAndRenderHistory(e.target.value);
        });
    }

    // Start New Chat (Universal)
    const startNewChat = (mode) => {
        const newId = `sess_${mode}_${Date.now()}`;
        chatController.setSessionId(newId);
        chatController.showGreeting();

        if (mode === 'documents') {
            // In Knowledge Base, if user hasn't chosen docs, answers from all embeddings
            Knowledge.clearSelectionAndContext();
        }

        renderHistoryList(mode);
    };

    if (newChatBtn) {
        newChatBtn.addEventListener('click', () => startNewChat(currentMode));
    }
    if (topNewChatBtn) {
        topNewChatBtn.addEventListener('click', () => startNewChat(currentMode));
    }
    if (reloadSessionBtn) {
        reloadSessionBtn.addEventListener('click', () => {
            chatController.loadHistory();
        });
    }

    // Top Segmented Pill Switching: [ Chat | + Work ]
    const segmentChat = document.getElementById('segment-chat');
    const segmentWork = document.getElementById('segment-work');

    if (segmentChat && segmentWork) {
        segmentChat.addEventListener('click', () => {
            segmentChat.classList.add('active');
            segmentWork.classList.remove('active');
            UI.navItems.forEach(n => n.classList.remove('active'));
            document.getElementById('nav-general-chat')?.classList.add('active');
            UI.setMode('chat');
        });

        segmentWork.addEventListener('click', () => {
            segmentWork.classList.add('active');
            segmentChat.classList.remove('active');
            UI.navItems.forEach(n => n.classList.remove('active'));
            document.getElementById('nav-web-mcp')?.classList.add('active');
            UI.setMode('mcp');
        });
    }

    // Listen for Mode Changes from Navigation
    document.addEventListener('app:mode-changed', (e) => {
        const mode = e.detail.mode;
        currentMode = mode;

        // Sync segmented pill button
        if (segmentChat && segmentWork) {
            if (mode === 'chat') {
                segmentChat.classList.add('active');
                segmentWork.classList.remove('active');
            } else if (mode === 'mcp') {
                segmentWork.classList.add('active');
                segmentChat.classList.remove('active');
            } else {
                segmentChat.classList.remove('active');
                segmentWork.classList.remove('active');
            }
        }

        // Start or continue a session for this mode
        startNewChat(mode);
    });

    // Refresh history list when a message has been sent
    document.addEventListener('app:chat-updated', (e) => {
        renderHistoryList(e.detail.mode);
    });

    // Initial render for default 'chat' mode
    renderHistoryList('chat');

    // 5. Load Pending Actions
    const loadActions = async () => {
        try {
            const actions = await API.getPendingActions();
            UI.renderActions(
                actions,
                async (id) => {
                    await API.approveAction(id);
                    loadActions();
                },
                async (id) => {
                    await API.rejectAction(id);
                    loadActions();
                }
            );
        } catch (e) {
            console.error("Error loading pending actions", e);
        }
    };
    loadActions();
    setInterval(loadActions, 10000);

    // 6. Load Integrations
    const loadIntegrations = async () => {
        try {
            const ints = await API.getIntegrations();
            UI.renderIntegrations(ints);
        } catch (e) {
            console.error("Error loading integrations", e);
        }
    };
    loadIntegrations();

    // 7. Load Calendar
    const loadCalendar = async () => {
        try {
            const evts = await API.getCalendarEvents();
            UI.renderCalendarEvents(evts);
        } catch (e) {
            console.error("Error loading calendar events", e);
        }
    };
    loadCalendar();
});
