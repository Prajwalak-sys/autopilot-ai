import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE_DIR = Path(__file__).resolve().parent.parent


async def execute_mcp_tool(tool_name, arguments):
    server_parameters = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-m", "tools.mcp_server"],
        cwd=str(BASE_DIR),
    )

    async with stdio_client(server_parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                tool_name,
                arguments=arguments,
            )

            if result.isError:
                errors = [
                    item.text
                    for item in result.content
                    if hasattr(item, "text")
                ]
                raise RuntimeError(
                    "\n".join(errors) or "MCP tool execution failed"
                )

            return [
                item.text if hasattr(item, "text") else str(item)
                for item in result.content
            ]


def call_mcp_tool(tool_name, arguments):
    return asyncio.run(execute_mcp_tool(tool_name, arguments))


def search_internships_mcp(field="AI/ML", location="Bengaluru", limit=5):
    return call_mcp_tool(
        "search_internships",
        {
            "field": field,
            "location": location,
            "limit": limit,
        },
    )


def save_internships_mcp(internships):
    return call_mcp_tool(
        "save_internship_results",
        {"internships": internships},
    )