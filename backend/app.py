"""
FastAPI application factory — creates and configures the iLumina backend.

Responsibilities:
- FastAPI app initialization with lifespan
- MCP stdio session startup (Filesystem, MS365)
- Route registration
- Static file serving
- Database initialization
"""

import os
from contextlib import asynccontextmanager, AsyncExitStack

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

from backend.config import WORKSPACE_DIR, FRONTEND_DIR
from backend.db.store import init_db
from backend.db.context_store import init_context_db
from backend.mcp.client import MCP_SESSIONS
from backend.routes import chat, history, system, spaces, actions, context, calendar, memory, integrations


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage MCP stdio session lifecycle."""
    async with AsyncExitStack() as stack:
        try:
            # Documents MCP server
            doc_params = StdioServerParameters(
                command="python3",
                args=["-m", "backend.mcp.document_server"]
            )
            doc_read, doc_write = await stack.enter_async_context(stdio_client(doc_params))
            doc_session = await stack.enter_async_context(ClientSession(doc_read, doc_write))
            await doc_session.initialize()
            MCP_SESSIONS["documents"] = {"session": doc_session}

            # Playwright MCP Server via SSE
            try:
                from fastmcp import Client as FastMCPClient
                from backend.config import FASTMCP_URL
                # Set a very long timeout (24 hours) to prevent HTTPX ReadTimeout on idle SSE connections
                playwright_client = FastMCPClient(FASTMCP_URL, timeout=86400.0)
                await stack.enter_async_context(playwright_client)
                MCP_SESSIONS["playwright"] = {"session": playwright_client}
                print("✅ Playwright MCP Session Initialized")
            except Exception as e:
                print(f"❌ Failed to initialize Playwright MCP: {e}")

            # Filesystem MCP server
            fs_params = StdioServerParameters(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", WORKSPACE_DIR]
            )
            fs_read, fs_write = await stack.enter_async_context(stdio_client(fs_params))
            fs_session = await stack.enter_async_context(ClientSession(fs_read, fs_write))
            await fs_session.initialize()
            MCP_SESSIONS["filesystem"] = {"session": fs_session}

            # MS365 MCP server
            ms_params = StdioServerParameters(
                command="npx",
                args=["-y", "@softeria/ms-365-mcp-server"]
            )
            ms_read, ms_write = await stack.enter_async_context(stdio_client(ms_params))
            ms_session = await stack.enter_async_context(ClientSession(ms_read, ms_write))
            await ms_session.initialize()
            MCP_SESSIONS["ms365"] = {"session": ms_session}

            # Start background sync loops
            import asyncio
            from backend.services.sync_service import sync_onedrive_loop, sync_gdrive_loop
            asyncio.create_task(sync_onedrive_loop(ms_session))
            asyncio.create_task(sync_gdrive_loop())

            # GitHub MCP server
            github_token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
            if github_token:
                gh_params = StdioServerParameters(
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-github"],
                    env={"GITHUB_PERSONAL_ACCESS_TOKEN": github_token, **os.environ}
                )
                gh_read, gh_write = await stack.enter_async_context(stdio_client(gh_params))
                gh_session = await stack.enter_async_context(ClientSession(gh_read, gh_write))
                await gh_session.initialize()
                MCP_SESSIONS["github"] = {"session": gh_session}
                print("✅ GitHub MCP Session Initialized")
            else:
                print("⚠️  Skipping GitHub MCP: GITHUB_PERSONAL_ACCESS_TOKEN not set in environment.")

            print("✅ MCP Background Sessions Initialized")
        except Exception as e:
            print(f"❌ Failed to initialize MCP Sessions: {e}")

        yield

        print("🛑 Shutting down MCP Background Sessions...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Initialize databases
    init_db()
    init_context_db()

    app = FastAPI(
        title="iLumina Chatbot",
        description="AI Chatbot with Playwright browser automation and Multi-MCP via stdio",
        version="2.0.0",
        lifespan=lifespan
    )

    # Register route modules
    app.include_router(chat.router)
    app.include_router(history.router)
    app.include_router(system.router)
    app.include_router(spaces.router)
    app.include_router(actions.router)
    app.include_router(context.router)
    app.include_router(calendar.router)
    app.include_router(memory.router)
    app.include_router(integrations.router)

    # Static files
    if os.path.exists(FRONTEND_DIR):
        app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
        
    # Serve Playwright MCP screenshots directory if it exists
    playwright_dir = os.path.join(WORKSPACE_DIR, ".playwright-mcp")
    os.makedirs(playwright_dir, exist_ok=True)
    app.mount("/.playwright-mcp", StaticFiles(directory=playwright_dir), name="playwright-mcp")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    @app.get("/")
    async def serve_frontend():
        """Serve the frontend."""
        index_path = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "Frontend not found."}

    return app
