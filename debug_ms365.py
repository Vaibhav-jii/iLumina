import asyncio
import json
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

async def main():
    params = StdioServerParameters(command="npx", args=["-y", "@softeria/ms-365-mcp-server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("graph-batch", {
                "body": {
                    "requests": [
                        {
                            "id": "1",
                            "method": "GET",
                            "url": "/me/drive"
                        }
                    ]
                }
            })
            print(f"Result type: {type(result.content)}")
            if hasattr(result, 'content'):
                for idx, c in enumerate(result.content):
                    print(f"Item {idx}: type={type(c)}")
                    if hasattr(c, 'text'):
                        print(f"Text preview: {c.text[:1000]}")
                    else:
                        print(c)

asyncio.run(main())
