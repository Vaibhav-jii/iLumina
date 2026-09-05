/**
 * UI & Modal Controller for iLumina (ChatGPT Style)
 */

export const UI = {
    currentMode: 'chat',
    isThinkingEnabled: false,

    init() {
        this.sidebar = document.getElementById('sidebar');
        this.toggleSidebarBtn = document.getElementById('toggle-sidebar');
        this.topOpenSidebarBtn = document.getElementById('top-open-sidebar-btn');
        this.topNewChatBtn = document.getElementById('top-new-chat-btn');
        this.navItems = document.querySelectorAll('.nav-menu-item');

        // Modals
        this.chooseDocsModal = document.getElementById('choose-docs-modal');
        this.pendingTasksModal = document.getElementById('pending-tasks-modal');
        this.integrationsModal = document.getElementById('integrations-modal');
        this.calendarModal = document.getElementById('calendar-modal');

        // Close buttons
        document.getElementById('close-docs-modal-btn')?.addEventListener('click', () => this.closeModal(this.chooseDocsModal));
        document.getElementById('close-tasks-modal-btn')?.addEventListener('click', () => this.closeModal(this.pendingTasksModal));
        document.getElementById('close-integrations-modal-btn')?.addEventListener('click', () => this.closeModal(this.integrationsModal));
        document.getElementById('close-calendar-modal-btn')?.addEventListener('click', () => this.closeModal(this.calendarModal));

        // Close on backdrop click
        [this.chooseDocsModal, this.pendingTasksModal, this.integrationsModal, this.calendarModal].forEach(modal => {
            if (modal) {
                modal.addEventListener('click', (e) => {
                    if (e.target === modal) this.closeModal(modal);
                });
            }
        });

        // Think button toggle
        this.thinkBtn = document.getElementById('think-toggle-btn');
        if (this.thinkBtn) {
            this.thinkBtn.addEventListener('click', () => {
                this.isThinkingEnabled = !this.isThinkingEnabled;
                this.thinkBtn.classList.toggle('active', this.isThinkingEnabled);
            });
        }

        // Voice button click feedback
        const voiceBtn = document.getElementById('voice-mode-btn');
        if (voiceBtn) {
            voiceBtn.addEventListener('click', () => {
                alert("Voice Mode: Speech recognition & audio response enabled.");
            });
        }

        // Mic dictation button
        const micBtn = document.getElementById('speech-mic-btn');
        if (micBtn) {
            micBtn.addEventListener('click', () => {
                this.startDictation();
            });
        }

        this.setupSidebar();
        this.setupNavigation();
        this.setupInputAutoresize();
    },

    setupSidebar() {
        if (this.toggleSidebarBtn) {
            this.toggleSidebarBtn.addEventListener('click', () => {
                this.sidebar.classList.toggle('collapsed');
                const isCollapsed = this.sidebar.classList.contains('collapsed');
                if (this.topOpenSidebarBtn) {
                    this.topOpenSidebarBtn.classList.toggle('hidden', !isCollapsed);
                }
                if (this.topNewChatBtn) {
                    this.topNewChatBtn.classList.toggle('hidden', !isCollapsed);
                }
            });
        }

        if (this.topOpenSidebarBtn) {
            this.topOpenSidebarBtn.addEventListener('click', () => {
                this.sidebar.classList.remove('collapsed');
                this.topOpenSidebarBtn.classList.add('hidden');
                if (this.topNewChatBtn) {
                    this.topNewChatBtn.classList.add('hidden');
                }
            });
        }
    },

    setupNavigation() {
        this.navItems.forEach(item => {
            item.addEventListener('click', () => {
                const mode = item.getAttribute('data-mode');
                const action = item.getAttribute('data-action');

                if (mode) {
                    // Switch primary mode
                    this.navItems.forEach(n => {
                        if (n.hasAttribute('data-mode')) n.classList.remove('active');
                    });
                    item.classList.add('active');
                    this.setMode(mode);
                } else if (action) {
                    // Open secondary modal
                    if (action === 'pending-tasks') {
                        this.openModal(this.pendingTasksModal);
                    } else if (action === 'integrations') {
                        this.openModal(this.integrationsModal);
                    } else if (action === 'calendar') {
                        this.openModal(this.calendarModal);
                    }
                }
            });
        });
    },

    setMode(mode) {
        this.currentMode = mode;
        
        // Update tag in recents header
        const modeTag = document.getElementById('current-mode-tag');
        const modeNames = {
            'chat': 'Chat',
            'mcp': 'Web MCP',
            'documents': 'Knowledge Base'
        };
        if (modeTag) {
            modeTag.innerText = modeNames[mode] || mode;
        }

        // Knowledge Base specific sidebar action button visibility
        const kbDocAction = document.getElementById('kb-doc-action-container');
        if (kbDocAction) {
            if (mode === 'documents') {
                kbDocAction.classList.remove('hidden');
            } else {
                kbDocAction.classList.add('hidden');
            }
        }

        // Update placeholder in prompt bar
        const textarea = document.getElementById('prompt-textarea');
        if (textarea) {
            if (mode === 'mcp') {
                textarea.placeholder = "Command your Web MCP tools & browser...";
            } else if (mode === 'documents') {
                textarea.placeholder = "Ask anything across knowledge documents...";
            } else {
                textarea.placeholder = "Ask anything";
            }
        }

        // Notify app to switch history list and controller
        document.dispatchEvent(new CustomEvent('app:mode-changed', { detail: { mode } }));
    },

    setupInputAutoresize() {
        const textarea = document.getElementById('prompt-textarea');
        const sendBtn = document.getElementById('prompt-send-btn');
        const voiceBtn = document.getElementById('voice-mode-btn');

        if (!textarea) return;

        textarea.addEventListener('input', () => {
            textarea.style.height = 'auto';
            const newHeight = Math.min(textarea.scrollHeight, 200);
            textarea.style.height = `${newHeight}px`;

            // Toggle send button vs voice waveform button
            const hasText = textarea.value.trim().length > 0;
            if (sendBtn && voiceBtn) {
                if (hasText) {
                    sendBtn.classList.remove('hidden');
                    voiceBtn.classList.add('hidden');
                } else {
                    sendBtn.classList.add('hidden');
                    voiceBtn.classList.remove('hidden');
                }
            }
        });

        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const form = document.getElementById('chatgpt-prompt-form');
                if (form) form.dispatchEvent(new Event('submit'));
            }
        });
    },

    startDictation() {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
            alert("Speech recognition is not supported in this browser.");
            return;
        }

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        recognition.lang = 'en-US';
        recognition.interimResults = false;

        const micBtn = document.getElementById('speech-mic-btn');
        if (micBtn) micBtn.style.color = '#ef4444';

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            const textarea = document.getElementById('prompt-textarea');
            if (textarea) {
                textarea.value = (textarea.value + ' ' + transcript).trim();
                textarea.dispatchEvent(new Event('input'));
            }
        };

        recognition.onerror = () => {
            if (micBtn) micBtn.style.color = '';
        };

        recognition.onend = () => {
            if (micBtn) micBtn.style.color = '';
        };

        recognition.start();
    },

    openModal(modal) {
        if (modal) modal.classList.remove('hidden');
    },

    closeModal(modal) {
        if (modal) modal.classList.add('hidden');
    },

    renderActions(actions, onApprove, onReject) {
        const list = document.getElementById('pending-tasks-list');
        const badge = document.getElementById('pending-count-badge');
        if (!list) return;

        list.innerHTML = '';
        const count = actions ? actions.length : 0;

        if (badge) {
            if (count > 0) {
                badge.innerText = count;
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }

        if (count === 0) {
            list.innerHTML = '<p class="empty-state">No pending actions.</p>';
            return;
        }

        actions.forEach(action => {
            const el = document.createElement('div');
            el.className = 'action-card';
            el.innerHTML = `
                <h4>${action.title || 'Action Request'}</h4>
                <p>${action.description || 'Approval required for execution.'}</p>
                <div class="action-actions">
                    <button class="approve-btn"><i class="ph ph-check"></i> Approve</button>
                    <button class="reject-btn"><i class="ph ph-x"></i> Reject</button>
                </div>
            `;

            el.querySelector('.approve-btn').addEventListener('click', () => onApprove(action.id));
            el.querySelector('.reject-btn').addEventListener('click', () => onReject(action.id));
            list.appendChild(el);
        });
    },

    renderIntegrations(integrations) {
        const list = document.getElementById('integrations-modal-list');
        if (!list) return;

        list.innerHTML = '';
        if (!integrations || integrations.length === 0) {
            list.innerHTML = '<p class="empty-state">No integrations connected.</p>';
            return;
        }

        const iconMap = {
            'google_calendar': 'ph-calendar-check',
            'github': 'ph-github-logo',
            'filesystem': 'ph-folder',
            'ms365': 'ph-microsoft-logo',
            'google_drive': 'ph-google-drive-logo'
        };

        const nameMap = {
            'google_calendar': 'Google Calendar',
            'github': 'GitHub MCP',
            'filesystem': 'Local Filesystem',
            'ms365': 'Microsoft 365',
            'google_drive': 'Google Drive'
        };

        integrations.forEach(intg => {
            let statusText = (intg.status || 'CONNECTED').toUpperCase();
            if (intg.provider === 'github' && intg.status === 'error') {
                statusText = "MISSING TOKEN";
            }

            const el = document.createElement('div');
            el.className = 'integration-card';
            el.innerHTML = `
                <div class="integration-info">
                    <i class="ph ${iconMap[intg.provider] || 'ph-plugs-connected'} integration-icon"></i>
                    <div>
                        <h3>${nameMap[intg.provider] || intg.provider}</h3>
                    </div>
                </div>
                <div class="status-badge ${intg.status || 'connected'}">${statusText}</div>
            `;
            list.appendChild(el);
        });
    },

    renderCalendarEvents(events) {
        const list = document.getElementById('calendar-modal-list');
        if (!list) return;

        list.innerHTML = '';
        if (!events || events.length === 0) {
            list.innerHTML = '<p class="empty-state">No upcoming events scheduled.</p>';
            return;
        }

        events.forEach(evt => {
            const el = document.createElement('div');
            el.className = 'integration-card';

            let timeStr = "All Day";
            if (evt.start && evt.start.dateTime) {
                const date = new Date(evt.start.dateTime);
                timeStr = date.toLocaleString();
            } else if (evt.start && evt.start.date) {
                timeStr = evt.start.date;
            }

            el.innerHTML = `
                <div class="integration-info">
                    <i class="ph ph-calendar-star integration-icon"></i>
                    <div>
                        <h3>${evt.summary || 'Untitled Event'}</h3>
                        <p style="color:var(--text-muted); font-size:12px; margin-top:2px;">${timeStr}</p>
                    </div>
                </div>
            `;
            list.appendChild(el);
        });
    }
};
