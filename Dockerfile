# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (Node.js for MCP tools, and dependencies for Playwright browsers)
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser binaries (Chromium only to save space)
RUN playwright install --with-deps chromium

# Copy the rest of the application code
COPY . .

# Create data directory for persistent storage (SQLite and ChromaDB)
RUN mkdir -p /app/data

# Expose the FastAPI port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FASTMCP_URL="http://localhost:8001/mcp"

# Create a startup script to run both servers
RUN echo '#!/bin/bash\n\
python mcp_server.py &\n\
sleep 3\n\
python main.py\n\
' > /app/start_docker.sh && chmod +x /app/start_docker.sh

# Run the startup script
CMD ["/app/start_docker.sh"]
