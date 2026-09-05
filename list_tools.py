import asyncio
from fastmcp import Client
import json

async def main():
    async with Client("http://localhost:9222/sse") as client:
        tools = await client.list_tools()
        for t in tools:
            print(t.name)
            print(json.dumps(t.inputSchema, indent=2))

asyncio.run(main())
