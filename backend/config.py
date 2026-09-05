"""
Centralized configuration for iLumina backend.
All environment variables and constants are loaded here.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")

# --- Model Defaults ---
DEFAULT_GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b")
DEFAULT_GROQ_VISION = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")

# --- Server URLs ---
FASTMCP_URL = os.getenv("FASTMCP_URL", "http://localhost:8001/mcp")
FASTAPI_PORT = int(os.getenv("FASTAPI_PORT", "8000"))

# --- Workspace ---
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- Agent ---
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "10"))

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "ilumina_chat.db")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma_db")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
SCREENSHOTS_DIR = os.path.join(FRONTEND_DIR, "screenshots")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CHROMA_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
