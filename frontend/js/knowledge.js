/**
 * Knowledge Base & Document Selection Controller
 */

export const Knowledge = {
    selectedDocIds: new Set(),
    activeSpaceId: null,
    activeSpaceName: null,
    allDocs: [],

    init(api) {
        this.api = api;
        this.modal = document.getElementById('choose-docs-modal');
        this.modalList = document.getElementById('docs-modal-list');
        this.searchInput = document.getElementById('doc-modal-search');
        this.sourceFilter = document.getElementById('doc-source-filter');
        this.sortFilter = document.getElementById('doc-sort-filter');
        this.applyBtn = document.getElementById('apply-selected-docs-btn');
        this.resetBtn = document.getElementById('clear-all-docs-btn');
        this.statusText = document.getElementById('selection-status-text');

        // Sidebar button
        this.sidebarChooseBtn = document.getElementById('sidebar-choose-docs-btn');
        this.sidebarBadge = document.getElementById('sidebar-docs-count-badge');

        // Chat Context Banner
        this.contextBanner = document.getElementById('active-context-banner');
        this.contextLabel = document.getElementById('active-context-label');
        this.changeDocsBtn = document.getElementById('banner-change-docs-btn');
        this.clearContextBtn = document.getElementById('banner-clear-context-btn');

        this.setupEvents();
    },

    setupEvents() {
        // Open Modal from sidebar or banner
        if (this.sidebarChooseBtn) {
            this.sidebarChooseBtn.addEventListener('click', () => this.openModal());
        }
        if (this.changeDocsBtn) {
            this.changeDocsBtn.addEventListener('click', () => this.openModal());
        }

        // Clear Context from banner
        if (this.clearContextBtn) {
            this.clearContextBtn.addEventListener('click', () => this.clearSelectionAndContext());
        }

        // Search & Filters
        if (this.searchInput) {
            this.searchInput.addEventListener('input', () => this.filterAndRenderDocs());
        }
        if (this.sourceFilter) {
            this.sourceFilter.addEventListener('change', () => this.filterAndRenderDocs());
        }
        if (this.sortFilter) {
            this.sortFilter.addEventListener('change', () => this.filterAndRenderDocs());
        }

        // Modal Action: Reset to All
        if (this.resetBtn) {
            this.resetBtn.addEventListener('click', () => {
                this.clearSelectionAndContext();
                this.closeModal();
            });
        }

        // Modal Action: Apply Selected Docs
        if (this.applyBtn) {
            this.applyBtn.addEventListener('click', async () => {
                await this.applyContext();
                this.closeModal();
            });
        }
    },

    openModal() {
        if (this.modal) {
            this.modal.classList.remove('hidden');
            this.filterAndRenderDocs();
        }
    },

    closeModal() {
        if (this.modal) {
            this.modal.classList.add('hidden');
        }
    },

    async loadDocuments() {
        if (this.modalList) {
            this.modalList.innerHTML = '<div class="loader-spinner"></div>';
        }
        try {
            this.allDocs = await this.api.getDocuments();
            this.filterAndRenderDocs();
        } catch (e) {
            if (this.modalList) {
                this.modalList.innerHTML = '<p class="empty-state">Failed to load documents.</p>';
            }
        }
    },

    filterAndRenderDocs() {
        if (!this.modalList) return;

        let filtered = [...(this.allDocs || [])];

        // Search query
        const query = this.searchInput ? this.searchInput.value.toLowerCase().trim() : '';
        if (query) {
            filtered = filtered.filter(d => d.name.toLowerCase().includes(query));
        }

        // Source filter
        const source = this.sourceFilter ? this.sourceFilter.value : 'all';
        if (source !== 'all') {
            filtered = filtered.filter(d => (d.source || '').toLowerCase() === source);
        }

        // Sort filter
        const sortBy = this.sortFilter ? this.sortFilter.value : 'name';
        if (sortBy === 'name') {
            filtered.sort((a, b) => a.name.localeCompare(b.name));
        } else if (sortBy === 'date') {
            filtered.sort((a, b) => new Date(b.last_modified || 0) - new Date(a.last_modified || 0));
        }

        this.renderDocs(filtered);
    },

    renderDocs(docs) {
        this.modalList.innerHTML = '';

        if (!docs || docs.length === 0) {
            this.modalList.innerHTML = '<p class="empty-state">No matching documents found.</p>';
            this.updateSelectionStatus();
            return;
        }

        const iconMap = {
            'pdf': 'ph-file-pdf',
            'docx': 'ph-file-doc',
            'doc': 'ph-file-doc',
            'txt': 'ph-file-text',
            'md': 'ph-file-code'
        };

        docs.forEach(doc => {
            const ext = doc.name.split('.').pop().toLowerCase();
            const icon = iconMap[ext] || 'ph-file';
            const isSelected = this.selectedDocIds.has(doc.id);

            const card = document.createElement('div');
            card.className = `doc-select-card ${isSelected ? 'selected' : ''}`;
            card.innerHTML = `
                <div class="doc-card-top">
                    <i class="ph ${icon} doc-icon"></i>
                    <div class="doc-checkbox-circle"><i class="ph ph-check"></i></div>
                </div>
                <div class="doc-name" title="${doc.name}">${doc.name}</div>
                <div class="doc-meta">
                    <span class="source-tag">${(doc.source || 'LOCAL').toUpperCase()}</span>
                    <span>${doc.last_modified ? doc.last_modified.substring(0, 10) : ''}</span>
                </div>
            `;

            card.addEventListener('click', () => {
                if (this.selectedDocIds.has(doc.id)) {
                    this.selectedDocIds.delete(doc.id);
                    card.classList.remove('selected');
                } else {
                    this.selectedDocIds.add(doc.id);
                    card.classList.add('selected');
                }
                this.updateSelectionStatus();
            });

            this.modalList.appendChild(card);
        });

        this.updateSelectionStatus();
    },

    updateSelectionStatus() {
        const count = this.selectedDocIds.size;

        if (this.statusText) {
            if (count === 0) {
                this.statusText.innerText = "0 documents selected (Global embeddings active)";
            } else {
                this.statusText.innerText = `${count} document${count > 1 ? 's' : ''} selected for context`;
            }
        }

        if (this.sidebarBadge) {
            if (count > 0) {
                this.sidebarBadge.innerText = count;
                this.sidebarBadge.classList.remove('hidden');
            } else {
                this.sidebarBadge.classList.add('hidden');
            }
        }
    },

    async applyContext() {
        const count = this.selectedDocIds.size;

        if (count === 0) {
            this.clearSelectionAndContext();
            return;
        }

        try {
            const spaceName = `Context (${count} docs)`;
            const space = await this.api.createSpace(spaceName, Array.from(this.selectedDocIds));
            this.activeSpaceId = space.id;
            this.activeSpaceName = spaceName;

            // Show banner in chat
            if (this.contextBanner && this.contextLabel) {
                this.contextLabel.innerText = `Restricted to ${count} chosen document${count > 1 ? 's' : ''}`;
                this.contextBanner.classList.remove('hidden');
            }

            document.dispatchEvent(new CustomEvent('knowledge:space-updated', {
                detail: { spaceId: this.activeSpaceId, count }
            }));
        } catch (e) {
            console.error("Failed to set space context", e);
        }
    },

    clearSelectionAndContext() {
        this.selectedDocIds.clear();
        this.activeSpaceId = null;
        this.activeSpaceName = null;
        this.updateSelectionStatus();

        if (this.contextBanner) {
            this.contextBanner.classList.add('hidden');
        }

        // Re-render cards to remove selection highlights
        this.filterAndRenderDocs();

        document.dispatchEvent(new CustomEvent('knowledge:space-updated', {
            detail: { spaceId: null, count: 0 }
        }));
    },

    /**
     * Restore document context from a persisted space_id (e.g. on page reload or chat switch).
     * Does not require the full doc IDs — just shows the banner with the count.
     */
    restoreFromSpace(spaceId, docCount, selectedDocs = []) {
        if (!spaceId || docCount === 0) {
            this.clearSelectionAndContext();
            return;
        }

        this.activeSpaceId = spaceId;
        this.activeSpaceName = `Context (${docCount} docs)`;

        // Restore selectedDocIds if we have them
        this.selectedDocIds.clear();
        if (selectedDocs && selectedDocs.length > 0) {
            selectedDocs.forEach(d => this.selectedDocIds.add(d.document_id));
        }

        this.updateSelectionStatus();

        if (this.contextBanner && this.contextLabel) {
            this.contextLabel.innerText = `Restricted to ${docCount} chosen document${docCount > 1 ? 's' : ''}`;
            this.contextBanner.classList.remove('hidden');
        }

        document.dispatchEvent(new CustomEvent('knowledge:space-updated', {
            detail: { spaceId: this.activeSpaceId, count: docCount }
        }));
    }
};
