# iLumina Frontend Development Prompt & API Contract

You are an expert Frontend Developer and UI/UX Designer. Your task is to build a complete, multi-page frontend for **iLumina**, a context-aware AI workspace.

## 🎨 UI/UX Design Constraints (CRITICAL)

- **NOT AI-MADE**: The frontend must NOT look like a generic "AI chat wrapper". It should look like a premium, enterprise-grade workspace (e.g., Linear, Notion, or Superhuman).
- **Minimalistic & Professional**: Use a clean, dark-mode-first aesthetic with high-contrast typography, subtle borders, and intentional whitespace. Avoid excessive glassmorphism, glowing neon borders, or overwhelming gradients.
- **Multi-Page Architecture**: This is NOT a single-page chat document. It is a multi-page application. You must implement distinct views/pages with proper routing (e.g., `/chat`, `/knowledge`, `/actions`, `/calendar`, `/settings`).
- **Responsive & fluid**: Use micro-interactions for buttons, smooth transitions for opening sidebars, and skeleton loaders for async data.

---

## 📡 API Contract (Source of Truth)

Assume the backend is fully complete and all of the following endpoints are available and fully functional. This is the exact contract you must integrate against.

### TypeScript Interfaces

```typescript
// --- Core Chat & Execution ---
export interface ChatSessionPreview {
  id: string;
  preview: string;
  timestamp: string;
  title: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system" | "tool";
  content: string | any[];
}

export interface ChatHistoryResponse {
  session_id: string;
  messages: ChatMessage[];
}

export interface SSEEvent {
  type: "response" | "tool_start" | "tool_end" | "error" | "done" | "action_proposed";
  text?: string;
  tool?: string;
  status?: "ok" | "error";
  duration_ms?: number;
  screenshots?: string[];
  tool_calls_made?: string[];
  trace?: any[];
  action?: ProposedAction; 
}

// --- Knowledge Spaces ---
export interface KnowledgeSpace {
  id: string;
  name: string;
  created_at: string;
  doc_count: number;
}

export interface SpaceDocument {
  document_id: string;
  filepath: string;
  source: "gdrive" | "onedrive" | "local";
}

export interface DocumentNode {
  _type: "file" | "directory";
  path?: string;
  details?: {
    document_id: string;
    name: string;
    last_modified: string;
    source: string;
  };
  children?: Record<string, DocumentNode>;
}

// --- Context & Intelligence ---
export interface ExtractedEvent {
  id: string;
  document_id: string;
  title: string;
  event_type: string;
  start_date: string | null;
  end_date: string | null;
  location: string | null;
  description: string | null;
  confidence: number;
  evidence: string;
}

export interface ExtractedEntity {
  id: string;
  document_id: string;
  entity_type: string;
  value: string;
  confidence: number;
  evidence: string;
}

// --- Memory ---
export interface Memory {
  id: string;
  content: string;
  category: "preference" | "fact" | "project" | "general";
  created_at: string;
}

// --- Action & Approval Framework ---
export interface ProposedAction {
  id: string;
  action_type: string; 
  provider: "google_calendar" | "github" | "mcp";
  title: string;
  description: string;
  payload: any;
  reason: string;
  status: "pending" | "approved" | "rejected" | "executed" | "failed";
  created_at: string;
}

// --- Integrations ---
export interface IntegrationStatus {
  provider: string;
  status: "connected" | "disconnected" | "error";
  last_synced?: string;
}
```

---

## 🛠️ API Endpoints

### 1. Chat & Orchestration (Page: `/chat`)

**`POST /api/chat/stream`**
- **Purpose**: Main streaming endpoint for chat. Returns SSE trace events.
- **Format**: `multipart/form-data`
- **Body**: `message` (string), `session_id` (string), `provider` (string), `model_name` (string), `mode` (string), `image` (file, optional).
- **Response**: `text/event-stream` yielding `SSEEvent` objects.

**`GET /api/chats`**
- **Purpose**: List recent chat sessions.
- **Query Params**: `mode`
- **Response**: `ChatSessionPreview[]`

**`GET /api/chats/{session_id}`**
- **Purpose**: Load full chat history.
- **Response**: `ChatHistoryResponse`

**`PUT /api/chats/{session_id}/title`**
- **Body**: `{ "title": "New Title" }`

**`DELETE /api/chats/{session_id}`**

### 2. Knowledge Spaces (Page: `/knowledge`)

**`GET /api/spaces`**
- **Response**: `KnowledgeSpace[]`

**`POST /api/spaces`**
- **Body**: `{ "name": "Space Name" }`
- **Response**: `{ "id": "uuid", "name": "Space Name" }`

**`DELETE /api/spaces/{space_id}`**

**`GET /api/spaces/{space_id}/documents`**
- **Response**: `SpaceDocument[]`

**`POST /api/spaces/{space_id}/documents`**
- **Body**: `{ "document_id": "doc123", "filepath": "path.pdf", "source": "gdrive" }`

**`DELETE /api/spaces/{space_id}/documents/{document_id}`**

**`GET /api/documents/tree`**
- **Purpose**: Full folder tree of synced documents (Google Drive, OneDrive, Local).
- **Response**: Tree of `DocumentNode`

### 3. Context & Intelligence (Page: `/knowledge/insights`)

**`POST /api/context/extract/{document_id}`**
- **Purpose**: Trigger AI extraction of entities and events from a document.

**`GET /api/context/events`**
- **Query Params**: `space_id` (optional), `date_range`
- **Response**: `ExtractedEvent[]`

**`GET /api/context/entities`**
- **Query Params**: `space_id` (optional), `type`
- **Response**: `ExtractedEntity[]`

### 4. Human-in-the-Loop Actions (Page: `/actions`)

**`GET /api/actions/pending`**
- **Purpose**: List all AI-proposed actions requiring human approval.
- **Response**: `ProposedAction[]` (Filtered by status = 'pending')

**`POST /api/actions/{id}/approve`**
- **Purpose**: Approve and execute an action.

**`POST /api/actions/{id}/reject`**
- **Purpose**: Reject an action.

### 5. Memory System (Page: `/settings/memory`)

**`GET /api/memory`**
- **Response**: `Memory[]`

**`POST /api/memory`**
- **Body**: `{ "content": "Prefers concise answers", "category": "preference" }`

**`DELETE /api/memory/{id}`**

### 6. Integrations & Calendar (Page: `/settings/integrations`)

**`GET /api/integrations`**
- **Response**: `IntegrationStatus[]` (GitHub, Google Calendar, Google Drive, OneDrive).

**`GET /api/calendar/events`**
- **Query Params**: `days_ahead`, `days_behind`
- **Response**: Standardized event array.

**`GET /api/integrations/github/repos`**
- **Response**: Array of GitHub repositories for the authenticated user.

---

## 🚀 Execution Instructions for Frontend Agent

1. **Routing**: Set up a robust router (e.g., React Router, Next.js App Router).
2. **State Management**: Use Zustand or Context API to manage the active `session_id`, active `space_id`, and global integration statuses.
3. **SSE Parsing**: Implement a robust EventSource or `fetch` stream reader to parse `SSEEvent` chunks from `/api/chat/stream` and render the agent's thought process (tool execution traces) beautifully in the UI.
4. **Action Approvals**: Build a dedicated "Inbox" or "Action Center" view where users can review `ProposedAction` cards and approve/reject them.
5. **Aesthetics**: Stick to the minimalistic, professional, dark-mode design constraints. Make it feel like a high-end productivity tool.
