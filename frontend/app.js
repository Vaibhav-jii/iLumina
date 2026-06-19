/**
 * iLumina Chat — Frontend Application Logic
 *
 * Handles chat messaging, image uploads, markdown rendering,
 * screenshot display, and communication with the FastAPI backend.
 */

// --- State ---
let sessionId = crypto.randomUUID();
let isProcessing = false;
let pendingImage = null; // { file: File, preview: dataURL }
let currentMode = 'chat'; // 'chat', 'web', 'documents'

// Voice state
let isRecording = false;
let recognition = null;
let ttsEnabled = false;
let currentUtterance = null;

// --- DOM References ---
const messagesEl = document.getElementById('messages');
const chatContainer = document.getElementById('chat-container');
const inputEl = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const welcomeScreen = document.getElementById('welcome-screen');
const toolsList = document.getElementById('tools-list');
const lightbox = document.getElementById('lightbox');
const lightboxImg = document.getElementById('lightbox-img');
const imageInput = document.getElementById('image-input');
const imagePreview = document.getElementById('image-preview');
const previewImg = document.getElementById('preview-img');
const removeImageBtn = document.getElementById('remove-image');

// --- Initialize ---
document.addEventListener('DOMContentLoaded', () => {
    checkHealth();
    loadTools();
    loadChats();
    inputEl.addEventListener('input', updateSendButton);

    // Drag & drop support
    const inputArea = document.querySelector('.input-area');
    inputArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        inputArea.classList.add('drag-over');
    });
    inputArea.addEventListener('dragleave', () => {
        inputArea.classList.remove('drag-over');
    });
    inputArea.addEventListener('drop', (e) => {
        e.preventDefault();
        inputArea.classList.remove('drag-over');
        const file = e.dataTransfer.files[0];
        if (file && file.type.startsWith('image/')) {
            setImage(file);
        }
    });

    // Paste image support
    document.addEventListener('paste', (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                if (file) setImage(file);
                break;
            }
        }
    });
});

// --- Mode Switching ---
function switchMode(mode) {
    currentMode = mode;
    
    // Update active state on primary sidebar buttons
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.getElementById(`mode-${mode}-btn`).classList.add('active');
    
    // Update active section in secondary sidebar
    document.querySelectorAll('.mode-section').forEach(sec => {
        sec.classList.remove('active');
        sec.style.display = 'none';
    });
    const activeSection = document.getElementById(`section-${mode}`);
    if (activeSection) {
        activeSection.classList.add('active');
        activeSection.style.display = 'flex';
    }
    
    // Update sidebar title
    const titles = {
        'chat': 'Chat History',
        'web': 'Web Engine',
        'documents': 'Knowledge Base'
    };
    document.getElementById('sidebar-title').innerText = titles[mode];
    
    // Auto-focus input
    inputEl.focus();
    
    // Reload chat history for the new mode
    loadChats();
    
    // If documents mode, load the tree
    if (mode === 'documents') {
        fetchDocumentTree();
    }
}

// --- Image Handling ---
function triggerImageUpload() {
    imageInput.click();
}

function handleImageSelect(input) {
    const file = input.files[0];
    if (file && file.type.startsWith('image/')) {
        setImage(file);
    }
    input.value = ''; // Reset so same file can be selected again
}

function setImage(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        pendingImage = { file, preview: e.target.result };
        previewImg.src = e.target.result;
        imagePreview.classList.add('active');
        updateSendButton();
    };
    reader.readAsDataURL(file);
}

function removeImage() {
    pendingImage = null;
    imagePreview.classList.remove('active');
    previewImg.src = '';
    updateSendButton();
}

function updateSendButton() {
    sendBtn.disabled = (inputEl.value.trim() === '' && !pendingImage) || isProcessing;
}

// --- Health Check ---
async function checkHealth() {
    try {
        const res = await fetch('/api/health');
        const data = await res.json();

        const mcpDot = document.getElementById('mcp-dot');
        const groqDot = document.getElementById('groq-dot');
        const playwrightDot = document.getElementById('playwright-dot');

        mcpDot.className = 'status-dot ' + (data.mcp_server === 'connected' ? 'connected' : 'disconnected');
        groqDot.className = 'status-dot ' + (data.groq_configured ? 'connected' : 'disconnected');
        playwrightDot.className = 'status-dot ' + (data.mcp_server === 'connected' ? 'connected' : 'disconnected');
    } catch (e) {
        console.error('Health check failed:', e);
        document.querySelectorAll('.status-dot').forEach(dot => {
            dot.className = 'status-dot disconnected';
        });
    }
}

function updateProviderStatus() {
    const selector = document.getElementById('model-selector');
    if (!selector) return;
    const value = selector.value;
    const provider = value.split('|')[0];
    
    // Update labels in sidebar to match selected provider
    const groqStatusItem = document.getElementById('status-groq');
    if (groqStatusItem) {
        const span = groqStatusItem.querySelector('span');
        if (span) {
            span.textContent = provider === 'gemini' ? 'Google Gemini' : 'Groq LLM';
        }
    }
}

// --- Load Tools ---
async function loadTools() {
    try {
        const res = await fetch('/api/tools', { cache: 'no-store' });
        const tools = await res.json();

        if (Array.isArray(tools) && tools.length > 0) {
            toolsList.innerHTML = tools.map(t => `
                <div class="tool-item">
                    <div class="tool-name">${escapeHtml(t.name)}</div>
                    <div class="tool-desc">${escapeHtml(t.description).substring(0, 60)}${t.description.length > 60 ? '...' : ''}</div>
                </div>
            `).join('');
        } else {
            toolsList.innerHTML = '<div class="tool-item loading">No tools available</div>';
        }
    } catch (e) {
        toolsList.innerHTML = '<div class="tool-item loading">Server offline</div>';
    }
}

// --- Sidebar Loaders ---
async function loadChats() {
    try {
        const res = await fetch(`/api/chats?mode=${currentMode}`, { cache: 'no-store' });
        const chats = await res.json();
        const chatsList = document.getElementById('chats-list');
        
        if (Array.isArray(chats) && chats.length > 0) {
            chatsList.innerHTML = chats.map(c => `
                <div class="tool-item" style="cursor: pointer; display: flex; justify-content: space-between; align-items: center;" onclick="loadSession('${c.id}')">
                    <div style="overflow: hidden; width: 70%;">
                        <div class="tool-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml(c.preview)}">${escapeHtml(c.preview) || "New Chat"}</div>
                        <div class="tool-desc">Click to resume</div>
                    </div>
                    <div style="display: flex; gap: 5px;">
                        <button onclick="editSessionName('${c.id}', '${escapeHtml(c.preview).replace(/'/g, "\\'")}', event)" style="background: rgba(50,150,255,0.1); border: 1px solid rgba(50,150,255,0.2); color: #3296ff; padding: 4px; border-radius: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center;" title="Edit Chat Name">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
                        </button>
                        <button onclick="deleteSession('${c.id}', event)" style="background: rgba(255,50,50,0.1); border: 1px solid rgba(255,50,50,0.2); color: #ff5555; padding: 4px; border-radius: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center;" title="Delete Chat">
                            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                                <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                            </svg>
                        </button>
                    </div>
                </div>
            `).join('');
        } else {
            chatsList.innerHTML = '<div class="tool-item loading">No previous chats</div>';
        }
    } catch (e) {
        document.getElementById('chats-list').innerHTML = '<div class="tool-item loading">Error loading</div>';
    }
}

async function fetchDocumentTree() {
    const containers = {
        onedrive: document.getElementById('onedrive-tree-container'),
        gdrive: document.getElementById('gdrive-tree-container'),
        local: document.getElementById('local-tree-container')
    };
    
    try {
        const res = await fetch('/api/documents/tree');
        const data = await res.json(); // returns { onedrive: {}, gdrive: {}, local: {} }
        
        for (const [source, tree] of Object.entries(data)) {
            const container = containers[source];
            if (!container) continue;

            if (Object.keys(tree).length > 0) {
                container.innerHTML = renderTreeHtml(tree);
                
                // Add click handlers for folders
                container.querySelectorAll('.tree-folder-header').forEach(header => {
                    header.addEventListener('click', (e) => {
                        const childrenContainer = e.currentTarget.nextElementSibling;
                        const icon = e.currentTarget.querySelector('.folder-icon');
                        if (childrenContainer.style.display === 'none') {
                            childrenContainer.style.display = 'block';
                            icon.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><polyline points="12 11 12 17"></polyline><polyline points="9 14 15 14"></polyline></svg>';
                        } else {
                            childrenContainer.style.display = 'none';
                            icon.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>';
                        }
                    });
                });
            } else {
                container.innerHTML = '<div class="tree-loading" style="color: #666;">No documents synced yet.</div>';
            }
        }
    } catch (e) {
        Object.values(containers).forEach(container => {
            if(container) container.innerHTML = '<div class="tree-loading" style="color: #ff5555;">Error loading tree</div>';
        });
        console.error(e);
    }
}

function renderTreeHtml(treeNode) {
    let html = '<ul class="tree-list">';
    
    // Sort keys: directories first, then files
    const keys = Object.keys(treeNode).sort((a, b) => {
        const nodeA = treeNode[a];
        const nodeB = treeNode[b];
        if (nodeA._type === 'directory' && nodeB._type !== 'directory') return -1;
        if (nodeA._type !== 'directory' && nodeB._type === 'directory') return 1;
        return a.localeCompare(b);
    });
    
    for (const key of keys) {
        const node = treeNode[key];
        
        if (node._type === 'directory') {
            html += `
                <li class="tree-item tree-folder">
                    <div class="tree-folder-header">
                        <span class="folder-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                        </span>
                        <span class="tree-label">${escapeHtml(key)}</span>
                    </div>
                    <div class="tree-children" style="display: block;">
                        ${renderTreeHtml(node.children)}
                    </div>
                </li>
            `;
        } else if (node._type === 'file') {
            const ext = key.split('.').pop().toLowerCase();
            let icon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>';
            
            if (ext === 'pdf') {
                icon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ff5555" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M16 13H8"></path><path d="M16 17H8"></path><path d="M10 9H8"></path></svg>';
            } else if (ext === 'doc' || ext === 'docx') {
                icon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3296ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M16 13H8"></path><path d="M16 17H8"></path><path d="M10 9H8"></path></svg>';
            }
            
            html += `
                <li class="tree-item tree-file" title="Path: ${escapeHtml(node.path)}\nLast Modified: ${node.details.last_modified}">
                    <span class="file-icon">${icon}</span>
                    <span class="tree-label">${escapeHtml(node.details.name)}</span>
                </li>
            `;
        }
    }
    
    html += '</ul>';
    return html;
}

async function editSessionName(id, currentName, event) {
    event.stopPropagation();
    // decode the escaped HTML back to normal text for the prompt
    const div = document.createElement('div');
    div.innerHTML = currentName;
    const decodedName = div.textContent || div.innerText || "";
    
    const newName = prompt("Enter new chat name:", decodedName);
    if (newName === null || newName.trim() === "") return;
    
    try {
        const res = await fetch(`/api/chats/${id}/title`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newName.trim() })
        });
        if (res.ok) {
            loadChats(); // Refresh the sidebar
        } else {
            console.error("Failed to update chat name");
        }
    } catch (e) {
        console.error("Failed to update chat name", e);
    }
}

async function deleteSession(id, event) {
    event.stopPropagation();
    if (!confirm("Are you sure you want to delete this chat permanently?")) return;
    try {
        const res = await fetch(`/api/chats/${id}`, { method: 'DELETE' });
        if (res.ok) {
            if (sessionId === id) {
                newSession();
            }
            loadChats(); // Always refresh the list then and there
        }
    } catch (e) {
        console.error("Failed to delete chat", e);
    }
}



async function loadSession(sid) {
    try {
        const res = await fetch(`/api/chats/${sid}`);
        const data = await res.json();
        const history = data.messages || [];
        
        if (history && history.length > 0) {
            sessionId = sid;
            messagesEl.innerHTML = '';
            
            history.forEach(msg => {
                if (msg.role === 'user') {
                    addMessage('user', msg.content);
                } else if (msg.role === 'assistant') {
                    addMessage('assistant', msg.content);
                }
            });
            scrollToBottom();
            
            // On mobile, close sidebar after selecting
            if (window.innerWidth <= 768) toggleSidebar();
        }
    } catch (e) {
        console.error('Failed to load session', e);
    }
}

// --- Chat Functions ---
function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

function sendSuggestion(text) {
    inputEl.value = text;
    updateSendButton();
    sendMessage();
}

function newSession() {
    sessionId = crypto.randomUUID();
    messagesEl.innerHTML = '';
    messagesEl.appendChild(createWelcomeScreen());
    removeImage();
    
    // On mobile, close sidebar after clicking new chat
    if (window.innerWidth <= 768) toggleSidebar();
}

async function sendMessage() {
    const text = inputEl.value.trim();
    if ((!text && !pendingImage) || isProcessing) return;

    // Remove welcome screen
    const welcome = document.getElementById('welcome-screen');
    if (welcome) welcome.remove();

    // Add user message (with image preview if present)
    addMessage('user', text || '📷 [Image uploaded]', [], pendingImage?.preview);

    // Build FormData
    const formData = new FormData();
    formData.append('message', text || 'Analyze this image');
    formData.append('session_id', sessionId);
    formData.append('mode', currentMode);
    
    const selector = document.getElementById('model-selector');
    if (selector) {
        const parts = selector.value.split('|');
        if (parts.length === 2) {
            formData.append('provider', parts[0]);
            formData.append('model_name', parts[1]);
        }
    }

    if (pendingImage) {
        formData.append('image', pendingImage.file);
    }

    // Clear input
    inputEl.value = '';
    inputEl.style.height = 'auto';
    removeImage();
    sendBtn.disabled = true;
    isProcessing = true;

    // Show thinking indicator
    const thinkingEl = addThinking();

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            body: formData,
        });

        const data = await res.json();

        // Remove thinking indicator
        thinkingEl.remove();

        if (!res.ok) {
            addMessage('assistant', `⚠️ **Error:** ${data.detail || 'Something went wrong'}`);
            return;
        }

        // Add tool call indicators
        if (data.tool_calls_made && data.tool_calls_made.length > 0) {
            addToolIndicators(data.tool_calls_made);
        }

        // Add assistant response
        addMessage('assistant', data.response, data.screenshots);

        // Refresh sidebar after successful message
        loadChats();
        if (currentMode === 'documents') {
            fetchDocumentTree();
        }

    } catch (e) {
        thinkingEl.remove();
        console.error("Chat Error:", e);
        addMessage('assistant', `⚠️ **Connection error:** Could not reach the server. Make sure all services are running.`);
    } finally {
        isProcessing = false;
        updateSendButton();
        checkHealth();
    }
}

// --- Message Rendering ---
function addMessage(role, content, screenshots = [], userImage = null) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'user' ? 'U' : '⚡';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    // Show user-uploaded image above the text bubble
    if (userImage) {
        const imgContainer = document.createElement('div');
        imgContainer.className = 'user-image-container';
        const img = document.createElement('img');
        img.src = userImage;
        img.alt = 'Uploaded image';
        img.onclick = () => openLightbox(userImage);
        imgContainer.appendChild(img);
        contentDiv.appendChild(imgContainer);
    }

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    if (role === 'assistant') {
        bubble.innerHTML = renderMarkdown(content);
    } else {
        bubble.textContent = content;
    }

    contentDiv.appendChild(bubble);

    // Attach lightbox to any markdown images
    const markdownImages = bubble.querySelectorAll('img');
    markdownImages.forEach(img => {
        // Add styling classes if needed or just the click handler
        img.style.maxWidth = '100%';
        img.style.borderRadius = '8px';
        img.style.marginTop = '8px';
        img.style.cursor = 'pointer';
        img.onclick = (e) => {
            e.stopPropagation();
            openLightbox(img.src);
        };
    });

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(contentDiv);
    messagesEl.appendChild(msgDiv);

    // Auto-speak assistant responses if TTS is enabled
    if (role === 'assistant' && ttsEnabled) {
        speakText(content, bubble);
    }

    scrollToBottom();
}

function addThinking() {
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant';
    msgDiv.id = 'thinking-msg';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = '⚡';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble thinking-indicator';
    bubble.innerHTML = `
        <div class="thinking-dot"></div>
        <div class="thinking-dot"></div>
        <div class="thinking-dot"></div>
    `;

    contentDiv.appendChild(bubble);
    msgDiv.appendChild(avatar);
    msgDiv.appendChild(contentDiv);
    messagesEl.appendChild(msgDiv);

    scrollToBottom();
    return msgDiv;
}

function addToolIndicators(tools) {
    const indicatorDiv = document.createElement('div');
    indicatorDiv.className = 'message assistant';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.style.visibility = 'hidden';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    tools.forEach(toolName => {
        const indicator = document.createElement('div');
        indicator.className = 'tool-indicator done';
        indicator.innerHTML = `
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2 6L5 9L10 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span>${escapeHtml(toolName)}</span>
        `;
        contentDiv.appendChild(indicator);
    });

    indicatorDiv.appendChild(avatar);
    indicatorDiv.appendChild(contentDiv);
    messagesEl.appendChild(indicatorDiv);
}

// --- Markdown Rendering ---
function renderMarkdown(text) {
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
        });
        return marked.parse(text);
    }
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
}

// --- Lightbox ---
function openLightbox(src) {
    lightboxImg.src = src;
    lightbox.classList.add('active');
}

function closeLightbox() {
    lightbox.classList.remove('active');
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeLightbox();
});

// --- Sidebar ---
function toggleSidebar() {
    const secondarySidebar = document.getElementById('secondary-sidebar');
    const primarySidebar = document.getElementById('primary-sidebar');
    
    // For desktop toggle
    secondarySidebar.classList.toggle('collapsed');
    primarySidebar.classList.toggle('collapsed');
    
    // For mobile toggle
    secondarySidebar.classList.toggle('visible');
    primarySidebar.classList.toggle('visible');
}

// --- Utilities ---
function scrollToBottom() {
    requestAnimationFrame(() => {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    });
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function createWelcomeScreen() {
    const div = document.createElement('div');
    div.className = 'welcome-screen';
    div.id = 'welcome-screen';
    div.innerHTML = `
        <div class="welcome-icon">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                <circle cx="24" cy="24" r="22" stroke="url(#welcomeGrad2)" stroke-width="2" opacity="0.3"/>
                <circle cx="24" cy="24" r="16" stroke="url(#welcomeGrad2)" stroke-width="2" opacity="0.6"/>
                <circle cx="24" cy="24" r="8" fill="url(#welcomeGrad2)"/>
                <defs>
                    <linearGradient id="welcomeGrad2" x1="2" y1="2" x2="46" y2="46">
                        <stop stop-color="#6C5CE7"/>
                        <stop offset="1" stop-color="#A29BFE"/>
                    </linearGradient>
                </defs>
            </svg>
        </div>
        <h2>Welcome to iLumina</h2>
        <p>I can browse the web, take screenshots, interact with pages, and analyze your uploaded images.</p>
        <div class="suggestions">
            <button class="suggestion-chip" onclick="sendSuggestion('Navigate to https://news.ycombinator.com and summarize what you see')">
                📰 Summarize Hacker News
            </button>
            <button class="suggestion-chip" onclick="sendSuggestion('Go to https://example.com and take a screenshot')">
                📸 Screenshot example.com
            </button>
            <button class="suggestion-chip" onclick="sendSuggestion('Navigate to https://github.com and tell me what\\'s trending')">
                🐙 GitHub Trending
            </button>
        </div>
    `;
    return div;
}

// ============================================
//  VOICE-TO-VOICE (Browser Web Speech API)
// ============================================

/**
 * Initialize the SpeechRecognition instance.
 * Only created once, reused for all voice interactions.
 */
function initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        alert('Your browser does not support Speech Recognition. Please use Chrome or Edge.');
        return null;
    }

    const rec = new SpeechRecognition();
    rec.continuous = false;       // Stop after one sentence
    rec.interimResults = true;    // Show partial results while speaking
    rec.lang = 'en-US';
    rec.maxAlternatives = 1;

    rec.onstart = () => {
        isRecording = true;
        document.getElementById('voice-btn').classList.add('recording');
        document.getElementById('voice-indicator').classList.add('active');
        document.getElementById('voice-status').textContent = 'Listening...';
    };

    rec.onresult = (event) => {
        let transcript = '';
        let isFinal = false;

        for (let i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
            if (event.results[i].isFinal) {
                isFinal = true;
            }
        }

        // Show partial transcript in the input box
        inputEl.value = transcript;
        autoResize(inputEl);
        updateSendButton();

        if (isFinal) {
            document.getElementById('voice-status').textContent = 'Got it!';
            // Auto-send after a short delay
            setTimeout(() => {
                if (inputEl.value.trim()) {
                    sendMessage();
                }
            }, 400);
        }
    };

    rec.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        if (event.error === 'not-allowed') {
            alert('Microphone access denied. Please allow microphone access in your browser settings.');
        }
        stopRecording();
    };

    rec.onend = () => {
        stopRecording();
    };

    return rec;
}

function stopRecording() {
    isRecording = false;
    document.getElementById('voice-btn').classList.remove('recording');
    document.getElementById('voice-indicator').classList.remove('active');
}

/**
 * Toggle voice recording on/off.
 */
function toggleVoiceInput() {
    if (isRecording) {
        // Stop
        if (recognition) recognition.stop();
        stopRecording();
        return;
    }

    // Stop any ongoing TTS
    if (window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
    }

    // Start recording
    if (!recognition) {
        recognition = initSpeechRecognition();
    }
    if (recognition) {
        try {
            recognition.start();
        } catch (e) {
            // Already started, stop and restart
            recognition.stop();
            setTimeout(() => recognition.start(), 200);
        }
    }
}

/**
 * Toggle TTS (text-to-speech) on/off for assistant responses.
 */
function toggleTTS() {
    ttsEnabled = !ttsEnabled;
    const btn = document.getElementById('tts-btn');
    btn.classList.toggle('active', ttsEnabled);
    btn.title = ttsEnabled ? 'Voice responses ON (click to mute)' : 'Voice responses OFF (click to enable)';

    // If turning off, stop any current speech
    if (!ttsEnabled && window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
    }
}

/**
 * Speak the given text using the browser's SpeechSynthesis API.
 * Strips markdown formatting before speaking.
 */
function speakText(text, bubbleEl = null) {
    if (!ttsEnabled || !text) return;

    // Cancel any ongoing speech
    window.speechSynthesis.cancel();

    const cleanText = stripMarkdown(text);
    
    // Split long text into chunks (browsers have a ~5000 char limit)
    const maxLen = 4000;
    const chunks = [];
    for (let i = 0; i < cleanText.length; i += maxLen) {
        chunks.push(cleanText.substring(i, i + maxLen));
    }

    // Highlight the bubble while speaking
    if (bubbleEl) bubbleEl.classList.add('speaking');

    chunks.forEach((chunk, idx) => {
        const utterance = new SpeechSynthesisUtterance(chunk);
        utterance.rate = 1.05;   // Slightly faster for natural feel
        utterance.pitch = 1.0;
        utterance.volume = 1.0;
        utterance.lang = 'en-US';

        // Pick a good voice if available
        const voices = window.speechSynthesis.getVoices();
        const preferred = voices.find(v => 
            v.name.includes('Google') || v.name.includes('Samantha') || v.name.includes('Daniel')
        );
        if (preferred) utterance.voice = preferred;

        if (idx === chunks.length - 1) {
            utterance.onend = () => {
                if (bubbleEl) bubbleEl.classList.remove('speaking');
            };
        }

        window.speechSynthesis.speak(utterance);
    });
}

/**
 * Strip markdown formatting to produce clean speakable text.
 */
function stripMarkdown(md) {
    return md
        .replace(/!\[.*?\]\(.*?\)/g, '')           // Remove images
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')   // Links → text
        .replace(/#{1,6}\s+/g, '')                   // Headings
        .replace(/(\*{1,3}|_{1,3})(.*?)\1/g, '$2') // Bold/Italic
        .replace(/`{1,3}[^`]*`{1,3}/g, '')          // Inline/block code
        .replace(/^\s*[-*+]\s+/gm, '')              // List markers
        .replace(/^\s*\d+\.\s+/gm, '')              // Numbered lists
        .replace(/^\s*>\s+/gm, '')                  // Blockquotes
        .replace(/---+/g, '')                        // Horizontal rules
        .replace(/\n{2,}/g, '. ')                    // Paragraph breaks → pause
        .replace(/\n/g, ' ')                         // Newlines → space
        .replace(/\s{2,}/g, ' ')                     // Collapse spaces
        .trim();
}

// Pre-load voices (some browsers need this)
if (window.speechSynthesis) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
}
