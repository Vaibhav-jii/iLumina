# iLumina — Agentic AI Assistant with MCP Integration

iLumina is a highly capable, multi-agent AI assistant powered by **FastAPI** and **LangGraph**. It orchestrates multiple LLM providers (Groq, Google Gemini) and utilizes the **Model Context Protocol (MCP)** to seamlessly interact with local filesystems, web browsers, and cloud storage (Microsoft 365, Google Drive).

![iLumina Demo (Placeholder)](./frontend/screenshots/demo.gif)

---

## 🌟 Key Features & Achievements

- **Multi-Agent Architecture (LangGraph):** Employs a dual-agent workflow with a Research Agent and an Expert Writer Agent. Operates on a 10-step sequential reasoning loop to break down complex user intents, retrieve data, and delegate final report generation.
- **Comprehensive Model Context Protocol (MCP) Integration:** Exposes diverse capabilities through a unified protocol via HTTP proxies and Stdio servers:
  - 🌐 **Web Automation:** Uses a headless Playwright server to navigate, scrape, type, click, and capture full-page DOM/accessibility and Base64 image snapshots. Also integrates DuckDuckGo search.
  - 📁 **Filesystem Access:** Integrates `@modelcontextprotocol/server-filesystem` to safely read and list local workspace directories.
  - 🧠 **Persistent Memory:** Utilizes `@modelcontextprotocol/server-memory` to maintain a memory graph of user facts and observations.
- **Multi-Cloud Sync Engine:** A persistent asynchronous background worker (`sync_engine.py`) automatically crawls **Google Drive** and **Microsoft 365 / OneDrive** every 5 minutes. It extracts text from PDFs (`PyPDF2`) and Word Documents (`python-docx`).
- **RAG & Vector Search:** The sync engine chunks cloud documents and embeds them into a persistent **ChromaDB** vector database, allowing the LLM to perform context-aware Retrieval-Augmented Generation across hundreds of enterprise files.
- **Dynamic LLM Routing & Vision Support:** Intelligently routes inference to Groq or Gemini based on task requirements, with native tool calling support on both providers. Seamlessly handles Base64 image uploads by delegating to specialized Vision models (e.g., Llama-4 Scout Vision or Gemini Vision).
- **High-Performance FastAPI Backend:** Built on FastAPI with atomic in-memory caching and a persistent SQLite database for lightning-fast chat history and session management.
- **Expert PDF Generation:** Automatically compiles research and insights into formatted PDF reports using `fpdf2`, featuring custom typography, tables, and colors natively mapped from markdown without external CSS dependencies.

---

## 🏗️ System Architecture

```mermaid
graph TD
    User([User]) -->|HTTP / API| FastAPI[FastAPI Backend]
    
    subgraph Core Logic
        FastAPI --> LG[LangGraph Orchestrator]
        LG --> RA[Research Agent]
        LG --> WA[Writer Agent]
        WA --> PDF[PDF Generator (fpdf2)]
    end
    
    subgraph LLM Router
        RA --> Router{LLM Router}
        Router --> Groq[Groq Llama-3 / Vision]
        Router --> Gemini[Google Gemini]

    end
    
    subgraph Model Context Protocol Servers
        RA --> FastMCP[FastMCP Proxy]
        FastMCP -->|MCP| PW[Playwright Server]
        RA --> StdioMCP[Stdio MCP Clients]
        StdioMCP -->|MCP| FS[Filesystem Server]
        StdioMCP -->|MCP| MS[MS365 Server]
        StdioMCP -->|MCP| Mem[Memory Server]
    end
    
    subgraph Persistent Storage
        SyncEngine[Cloud Sync Engine (GDrive/OneDrive)] -->|Ingests Docs| ChromaDB[(ChromaDB Vector Store)]
        RA -->|Semantic Search| ChromaDB
        FastAPI --> SQLite[(SQLite Chat History + RAM Cache)]
    end
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.11+
- Node.js 20.x (required for MCP servers)
- Playwright browsers installed

### 2. Installation
Clone the repository and install the Python dependencies:

```bash
# Set up virtual environment
python -m venv .venv
source .venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Install Playwright dependencies
playwright install chromium
```

### 3. Environment Variables
Copy the example environment file and fill in your API keys:

```bash
cp .env.example .env
```
Ensure you provide your `GROQ_API_KEY` and `GOOGLE_API_KEY` at a minimum. For cloud sync, you will also need a valid `token.json` for Google Drive and Microsoft 365 credentials.

### 4. Running the Application
iLumina consists of multiple background services (FastMCP proxy, sync engine, etc.) orchestrated via a single startup script:

```bash
./start.sh
```

Alternatively, you can run the application via Docker:
```bash
docker build -t ilumina .
docker run -p 8000:8000 --env-file .env ilumina
```

---

## 🛠️ Tech Stack
- **Backend:** Python, FastAPI, LangGraph
- **Frontend:** Vanilla HTML/CSS/JS (Lightweight)
- **AI / ML:** Groq, Google GenAI, ChromaDB
- **Automation & Integrations:** Model Context Protocol (MCP), Playwright, Google Drive API, MS Graph API
- **Utilities:** SQLite (caching/history), `fpdf2` (PDF styling), `PyPDF2` & `python-docx` (document parsing)
