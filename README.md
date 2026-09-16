# iLumina — Multi-Agent Document Intelligence System

FastAPI and LangGraph assistant with MCP tool integration, document sync, ChromaDB retrieval, and SSE chat streaming.

---

## Overview

iLumina is a multi-agent AI assistant built on **FastAPI** and **LangGraph**. It orchestrates multiple LLM providers (Groq, Google Gemini) and uses the **Model Context Protocol (MCP)** to interact with local filesystems, web browsers, and cloud storage (Microsoft 365, Google Drive).

The backend follows a modular **route → service → database** architecture with SQLite for session history, in-memory caching for active chat state, and ChromaDB for vector-embedding storage enabling RAG-based semantic search.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Frontend (HTML/CSS/JS)                                          │
│  SSE chat streaming · dynamic DOM rendering · session management │
└──────────────────┬───────────────────────────────────────────────┘
                   │ HTTP / SSE
┌──────────────────▼───────────────────────────────────────────────┐
│  FastAPI Backend                                                  │
│                                                                   │
│  ┌─────────┐  ┌────────────┐  ┌──────────────┐                  │
│  │ Routes  │→ │  Services  │→ │  DB Layer    │                  │
│  │ (9 modules)│ │ (sync,     │  │ (SQLite +   │                  │
│  │         │  │  extract,  │  │  RAM cache)  │                  │
│  │         │  │  calendar) │  │              │                  │
│  └─────────┘  └────────────┘  └──────────────┘                  │
│       │                                                           │
│  ┌────▼─────────────────────────────────┐                        │
│  │  LangGraph Orchestrator              │                        │
│  │  Research Agent ←→ Writer Agent      │                        │
│  │  10-step sequential reasoning loop   │                        │
│  └────┬─────────────────────────────────┘                        │
│       │                                                           │
│  ┌────▼─────────────────────────────────┐                        │
│  │  LLM Router                          │                        │
│  │  Groq (Llama-3/Vision) ↔ Gemini     │                        │
│  │  Dynamic routing by task complexity   │                        │
│  └──────────────────────────────────────┘                        │
└──────────────────────────────────────────────────────────────────┘
         │                              │
┌────────▼────────────┐    ┌────────────▼──────────────────────────┐
│  MCP Servers         │    │  Persistent Storage                   │
│                      │    │                                       │
│  Playwright (web)    │    │  ChromaDB (vector embeddings / RAG)   │
│  Filesystem (local)  │    │  SQLite  (chat history / sessions)    │
│  Microsoft 365       │    │                                       │
│  Memory (user facts) │    │  Cloud Sync Engine                    │
│  Documents (custom)  │    │  Google Drive + OneDrive → ChromaDB   │
│                      │    │  5-minute scheduled refresh cycle     │
│  → 16+ tools exposed │    │                                       │
│    via FastMCP proxy  │    │                                       │
└──────────────────────┘    └───────────────────────────────────────┘
```

---

## Features

- **Modular FastAPI Backend** — Separate route, service, and database layers with 9 API route modules covering chat, history, spaces, actions, calendar, and integrations.
- **LangGraph Dual-Agent Workflow** — Research Agent and Writer Agent operate on a 10-step reasoning loop to decompose queries, retrieve data, and generate reports.
- **Dynamic LLM Routing** — Switches between Groq and Gemini based on task complexity, with native tool-calling and multimodal vision support.
- **MCP Tool Integration** — Playwright browser automation, filesystem access, Microsoft 365, and persistent memory exposed as 16+ tools behind a FastMCP proxy.
- **RAG & Vector Search** — Scheduled cloud sync worker ingests documents from Google Drive and OneDrive, chunks and embeds them into ChromaDB for semantic retrieval.
- **SSE Chat Streaming** — Server-Sent Events for real-time response streaming with persisted session history.
- **88 Pytest Tests** — Unit and integration tests covering DB operations, API routes, MCP client helpers, and sync modules (80% line coverage).
- **Docker Support** — Containerized with automated Playwright browser installation and multi-process startup.

---

## Tech Stack

| Layer | Technologies |
|:------|:-------------|
| **Backend** | Python, FastAPI, LangGraph, Pydantic |
| **Frontend** | HTML, CSS, JavaScript (vanilla) |
| **AI / LLM** | Groq (Llama-3), Google Gemini, ChromaDB |
| **Integrations** | Model Context Protocol (MCP), Playwright, Google Drive API, Microsoft Graph API |
| **Storage** | SQLite (sessions/history), ChromaDB (vector embeddings) |
| **Testing** | Pytest (88 tests, 80% coverage) |
| **DevOps** | Docker, Git |

---

## Project Structure

```
iLumina/
├── backend/
│   ├── app.py                  # FastAPI application factory
│   ├── config.py               # Environment and settings
│   ├── models.py               # Pydantic models
│   ├── routes/                 # 9 API route modules
│   │   ├── chat.py             # Chat endpoints + SSE streaming
│   │   ├── history.py          # Session history CRUD
│   │   ├── spaces.py           # Workspace management
│   │   ├── actions.py          # User action tracking
│   │   ├── calendar.py         # Calendar integration
│   │   ├── context.py          # Context extraction
│   │   ├── integrations.py     # Cloud service integrations
│   │   ├── memory.py           # Persistent memory endpoints
│   │   └── system.py           # Health checks and system info
│   ├── services/
│   │   ├── sync_service.py     # Google Drive + OneDrive sync worker
│   │   ├── extraction_service.py # Document text extraction
│   │   └── calendar_service.py # Calendar event processing
│   ├── core/
│   │   ├── agent.py            # LangGraph agent orchestration
│   │   └── llm.py              # LLM router (Groq / Gemini)
│   ├── db/                     # SQLite store + context store
│   ├── mcp/
│   │   ├── client.py           # MCP tool discovery and execution
│   │   └── document_server.py  # Custom document MCP server
│   └── schemas/                # Request/response schemas
├── frontend/
│   ├── index.html              # Single-page application
│   ├── css/                    # Stylesheets
│   └── js/                     # Client-side logic (api.js, ui.js)
├── tests/
│   ├── conftest.py             # Pytest fixtures
│   └── test_backend.py         # 88 test cases
├── mcp_registry/               # MCP server configurations
├── docs/
│   └── API_CONTRACT.md         # API endpoint documentation
├── Dockerfile                  # Container configuration
├── requirements.txt            # Python dependencies
├── start.sh                    # Multi-service startup script
└── .env.example                # Environment variable template
```

---

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 20.x (required for MCP servers)

### Installation

```bash
# Clone the repository
git clone https://github.com/Vaibhav-jii/iLumina.git
cd iLumina

# Set up virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env with your GROQ_API_KEY and GOOGLE_API_KEY
```

### Running

```bash
# Start all services (FastAPI + MCP servers)
./start.sh
```

Or with Docker:

```bash
docker build -t ilumina .
docker run -p 8000:8000 --env-file .env ilumina
```

### Running Tests

```bash
pytest tests/ -v --cov=backend --cov-report=term-missing
```

---

## Author

**Vaibhav Bansal** — [GitHub](https://github.com/Vaibhav-jii) · [LinkedIn](https://linkedin.com/in/vaibhav-bansal-512604331)
