/**
 * API Wrapper for iLumina Backend
 */

const API_BASE = '/api';

export const API = {
    // === CHAT & STREAMING ===
    async sendChat(message, mode = 'chat', spaceId = null, sessionId = null, llmProvider = null, file = null) {
        const formData = new FormData();
        formData.append('message', message);
        formData.append('mode', mode);
        if (spaceId) formData.append('space_id', spaceId);
        if (sessionId) formData.append('session_id', sessionId);
        if (file) formData.append('image', file);
        
        if (llmProvider) {
            const parts = llmProvider.split(':');
            if (parts.length === 2) {
                formData.append('provider', parts[0]);
                formData.append('model_name', parts[1]);
            } else {
                formData.append('provider', llmProvider);
            }
        }

        // Returns the fetch response so the caller can process SSE
        return fetch(`${API_BASE}/chat/stream`, {
            method: 'POST',
            body: formData
        });
    },

    async getChats(mode = 'chat') {
        const res = await fetch(`${API_BASE}/chats?mode=${mode}`);
        if (!res.ok) return [];
        return res.json();
    },

    async getChatHistory(sessionId) {
        const res = await fetch(`${API_BASE}/chats/${sessionId}`);
        if (!res.ok) return null;
        return res.json();
    },

    async deleteChat(sessionId) {
        const res = await fetch(`${API_BASE}/chats/${sessionId}`, { method: 'DELETE' });
        return res.json();
    },

    async updateChatTitle(sessionId, title) {
        const res = await fetch(`${API_BASE}/chats/${sessionId}/title`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
        });
        return res.json();
    },

    // === KNOWLEDGE SPACES ===
    async getSpaces() {
        const res = await fetch(`${API_BASE}/spaces`);
        return res.json();
    },

    async createSpace(name, documentIds) {
        const res = await fetch(`${API_BASE}/spaces`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, document_ids: documentIds })
        });
        return res.json();
    },

    // === DOCUMENTS ===
    async getDocuments() {
        try {
            const res = await fetch(`${API_BASE}/documents/tree`);
            if (!res.ok) throw new Error("API not ready");
            const tree = await res.json();
            
            // Flatten the tree into an array
            const docs = [];
            const flatten = (node) => {
                if (!node) return;
                for (const key in node) {
                    const item = node[key];
                    if (item._type === 'file') {
                        docs.push({
                            id: item.details.document_id,
                            name: item.details.name,
                            source: item.details.source,
                            last_modified: item.details.last_modified
                        });
                    } else if (item._type === 'directory') {
                        flatten(item.children);
                    } else if (typeof item === 'object') {
                        // Root sources (gdrive, onedrive, local)
                        flatten(item);
                    }
                }
            };
            flatten(tree);
            
            if (docs.length > 0) return docs;
            
            console.warn("ChromaDB is empty, returning mock documents for UI demonstration");
            return this._getMockDocs();
        } catch(e) {
            console.warn("Docs API failed, returning mock documents", e);
            return this._getMockDocs();
        }
    },
    
    _getMockDocs() {
        return [
            { id: "doc-1", name: "Q3_Financial_Report.pdf", source: "gdrive", last_modified: "2026-09-01" },
            { id: "doc-2", name: "Product_Roadmap_2027.docx", source: "onedrive", last_modified: "2026-08-15" },
            { id: "doc-3", name: "Employee_Handbook.pdf", source: "local", last_modified: "2026-01-10" },
            { id: "doc-4", name: "Meeting_Notes_Aug.txt", source: "gdrive", last_modified: "2026-08-30" },
            { id: "doc-5", name: "System_Architecture.md", source: "github", last_modified: "2026-09-02" },
            { id: "doc-6", name: "Q4_Marketing_Plan.pdf", source: "onedrive", last_modified: "2026-09-03" }
        ];
    },

    // === ACTIONS (Approvals) ===
    async getPendingActions() {
        try {
            const res = await fetch(`${API_BASE}/actions`);
            return res.json();
        } catch (e) {
            return [];
        }
    },

    async approveAction(actionId) {
        const res = await fetch(`${API_BASE}/actions/${actionId}/approve`, { method: 'POST' });
        return res.json();
    },

    async rejectAction(actionId) {
        const res = await fetch(`${API_BASE}/actions/${actionId}/reject`, { method: 'POST' });
        return res.json();
    },

    // === INTEGRATIONS ===
    async getIntegrations() {
        try {
            const res = await fetch(`${API_BASE}/integrations`);
            if (!res.ok) return [];
            return res.json();
        } catch (e) {
            return [];
        }
    },

    // === CALENDAR ===
    async getCalendarEvents() {
        try {
            const res = await fetch(`${API_BASE}/calendar/events`);
            if (!res.ok) return [];
            return res.json();
        } catch (e) {
            return [];
        }
    }
};
