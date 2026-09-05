/**
 * Chat Controller (ChatGPT UI Streaming & Message Handler)
 */

export class ChatController {
    constructor(api, formId, inputId, messagesListId, greetingId, viewportId, mode, sessionId) {
        this.api = api;
        this.form = document.getElementById(formId);
        this.input = document.getElementById(inputId);
        this.messagesList = document.getElementById(messagesListId);
        this.greeting = document.getElementById(greetingId);
        this.viewport = document.getElementById(viewportId);

        this.mode = mode; // 'chat', 'mcp', or 'documents'
        this.sessionId = sessionId;
        this.spaceId = null;
        this.attachedImageBase64 = null;
        this.attachedFile = null;

        this.setupEvents();
    }

    setMode(mode) {
        this.mode = mode;
    }

    setSpaceId(spaceId) {
        this.spaceId = spaceId;
    }

    async setSessionId(sessionId) {
        this.sessionId = sessionId;
        await this.loadHistory();
    }

    setupEvents() {
        if (!this.form) return;

        this.form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.submitMessage();
        });

        // File Attachment
        const attachBtn = document.getElementById('prompt-attach-btn');
        const fileInput = document.getElementById('prompt-file-input');

        if (attachBtn && fileInput) {
            attachBtn.addEventListener('click', () => {
                fileInput.click();
            });

            fileInput.addEventListener('change', (e) => {
                if (e.target.files && e.target.files[0]) {
                    this.attachedFile = e.target.files[0];
                    attachBtn.style.color = 'var(--accent-blue)';
                    attachBtn.title = `Attached: ${this.attachedFile.name}`;
                }
            });
        }
    }

    async loadHistory() {
        if (!this.messagesList) return;
        this.messagesList.innerHTML = '';

        const data = await this.api.getChatHistory(this.sessionId);
        
        if (data && data.messages && data.messages.length > 0) {
            this.hideGreeting();
            data.messages.forEach(msg => {
                this.renderMessage(msg.role, msg.content);
            });
        } else {
            this.showGreeting();
        }
    }

    showGreeting() {
        if (this.greeting) this.greeting.classList.remove('hidden');
        if (this.viewport) this.viewport.classList.add('hidden');
    }

    hideGreeting() {
        if (this.greeting) this.greeting.classList.add('hidden');
        if (this.viewport) this.viewport.classList.remove('hidden');
    }

    async submitMessage() {
        const text = this.input.value.trim();
        if (!text && !this.attachedFile) return;

        this.hideGreeting();

        // Clear input and reset height
        this.input.value = '';
        this.input.style.height = '36px';

        // Trigger input event to update send button state
        this.input.dispatchEvent(new Event('input'));

        // Reset attachment button styling if file was attached
        const attachBtn = document.getElementById('prompt-attach-btn');
        if (attachBtn) {
            attachBtn.style.color = '';
            attachBtn.title = 'Add files or context';
        }

        // Render User Message
        this.renderMessage('user', text);

        // Prepare Assistant Stream Bubble
        const msgEl = this.createMessageBlock('assistant');
        const contentEl = msgEl.querySelector('.message-content-wrapper');

        const traceContainer = document.createElement('div');
        traceContainer.className = 'traces-wrapper';
        contentEl.appendChild(traceContainer);

        const textContainer = document.createElement('div');
        textContainer.className = 'response-text';
        contentEl.appendChild(textContainer);

        try {
            // Selected Model
            let llmProvider = null;
            const llmSelect = document.getElementById('llm-model-select');
            if (llmSelect) {
                llmProvider = llmSelect.value;
            }

            const response = await this.api.sendChat(
                text, 
                this.mode, 
                this.spaceId, 
                this.sessionId, 
                llmProvider, 
                this.attachedFile
            );

            this.attachedFile = null;

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let fullText = "";

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n\n');

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const dataStr = line.substring(6);
                        if (!dataStr.trim()) continue;

                        try {
                            const event = JSON.parse(dataStr);

                            if (event.type === 'response') {
                                fullText = event.text;
                                textContainer.innerHTML = marked.parse(fullText);
                            } else if (event.type === 'tool_start') {
                                const trace = this.createAgentTrace(event.tool, 'Running...');
                                traceContainer.appendChild(trace.el);
                            } else if (event.type === 'tool_end') {
                                const traces = traceContainer.querySelectorAll('.agent-trace');
                                const lastTrace = traces[traces.length - 1];
                                if (lastTrace) {
                                    lastTrace.querySelector('.trace-status').innerText = `${event.duration_ms || 100}ms`;
                                    if (event.status === 'error') {
                                        lastTrace.style.borderColor = 'var(--error, #ef4444)';
                                    }
                                }
                            } else if (event.type === 'error') {
                                textContainer.innerHTML += `<br><strong style="color:#ef4444;">Error: ${event.text}</strong>`;
                            }

                            this.scrollToBottom();
                        } catch (e) {
                            console.error("SSE parse error", e, dataStr);
                        }
                    }
                }
            }

            // Notify app that conversation was updated
            document.dispatchEvent(new CustomEvent('app:chat-updated', { detail: { mode: this.mode } }));

        } catch (e) {
            textContainer.innerText = "Connection failed. Please check backend service.";
        }
    }

    createMessageBlock(role) {
        const el = document.createElement('div');
        el.className = `message ${role}`;

        if (role === 'assistant') {
            const avatar = document.createElement('div');
            avatar.className = 'message-avatar';
            avatar.innerHTML = '<i class="ph ph-sparkle"></i>';
            el.appendChild(avatar);
        }

        const contentWrapper = document.createElement('div');
        contentWrapper.className = 'message-content-wrapper';
        el.appendChild(contentWrapper);

        this.messagesList.appendChild(el);
        this.scrollToBottom();

        return el;
    }

    renderMessage(role, text) {
        const el = this.createMessageBlock(role);
        const content = el.querySelector('.message-content-wrapper');

        if (role === 'user') {
            content.innerText = text;
        } else {
            content.innerHTML = marked.parse(text || '');
        }
    }

    createAgentTrace(toolName, status) {
        const el = document.createElement('div');
        el.className = 'agent-trace';

        const icon = toolName === 'propose_action' ? 'ph-paper-plane-tilt' : 
                     toolName === 'store_memory' ? 'ph-brain' : 'ph-wrench';

        el.innerHTML = `
            <div class="trace-header">
                <i class="ph ph-caret-right"></i>
                <i class="ph ${icon}"></i>
                <span>${toolName}</span>
                <span class="trace-status">${status}</span>
            </div>
            <div class="trace-body">Executing background task...</div>
        `;

        el.querySelector('.trace-header').addEventListener('click', () => {
            el.classList.toggle('open');
        });

        return { el };
    }

    scrollToBottom() {
        if (this.viewport) {
            this.viewport.scrollTop = this.viewport.scrollHeight;
        }
    }
}
