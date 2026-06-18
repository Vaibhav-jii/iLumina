import asyncio
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

async def main():
    params = StdioServerParameters(command="npx", args=["-y", "@softeria/ms-365-mcp-server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            for t in tools.tools:
                print(f"Tool: {t.name}")
                print(f"Desc: {t.description}")
                print("---")

asyncio.run(main())
