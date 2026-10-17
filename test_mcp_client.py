import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


BASE_DIR = Path(__file__).resolve().parent.parent


def _decode_json_string(value):
    """Decode a JSON string when possible; otherwise return it unchanged."""
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _normalize_mcp_value(value):
    """Normalize common MCP wrapper shapes without changing ordinary lists."""
    value = _decode_json_string(value)

    # Some MCP servers wrap a JSON response string in a one-item list.
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        decoded_item = _decode_json_string(value[0])
        if decoded_item is not value[0]:
            return _normalize_mcp_value(decoded_item)

    return value


def parse_tool_response(response):
    """Parse an MCP CallToolResult into a Python value."""
    if response.isError:
        messages = [
            item.text
            for item in (response.content or [])
            if hasattr(item, "text")
        ]
        raise RuntimeError(
            "\n".join(messages) or "MCP tool execution failed."
        )

    structured = getattr(response, "structuredContent", None)
    if structured is not None:
        return _normalize_mcp_value(structured)

    for item in (response.content or []):
        if not hasattr(item, "text"):
            continue

        text = item.text.strip()
        if not text:
            continue

        try:
            return _normalize_mcp_value(json.loads(text))
        except json.JSONDecodeError:
            continue

    raise RuntimeError("MCP returned no parseable response.")


async def execute_mcp_tool(tool_name, arguments):
    """Start the local MCP server, call one tool, and return its response."""
    server_parameters = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-m", "tools.mcp_server"],
        cwd=str(BASE_DIR),
    )

    async with stdio_client(server_parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            response = await session.call_tool(
                tool_name,
                arguments=arguments,
            )
            return parse_tool_response(response)


def call_mcp_tool(tool_name, arguments):
    """Synchronous wrapper used by the Streamlit executor."""
    return asyncio.run(execute_mcp_tool(tool_name, arguments))


def search_internships_mcp(
    field="AI/ML",
    location="Bengaluru",
    limit=5,
):
    result = call_mcp_tool(
        "search_internships",
        {
            "field": field,
            "location": location,
            "limit": limit,
        },
    )

    result = _normalize_mcp_value(result)

    if isinstance(result, dict):
        result = result.get("results", result.get("content"))

    if not isinstance(result, list):
        raise RuntimeError(
            f"Unexpected MCP research response: {result!r}"
        )

    # If the server wrapped each result as a JSON string, decode those strings.
    normalized_results = []
    for item in result:
        decoded_item = _decode_json_string(item)
        if isinstance(decoded_item, dict):
            normalized_results.append(decoded_item)
        else:
            normalized_results.append(item)

    return normalized_results


def save_internships_mcp(internships):
    result = call_mcp_tool(
        "save_internship_results",
        {"internships": internships},
    )
    result = _normalize_mcp_value(result)

    print("DEBUG MCP SAVE RESPONSE:", repr(result), flush=True)
    print("DEBUG MCP SAVE TYPE:", type(result), flush=True)

    # Accommodate a list that contains a dictionary or JSON-encoded response.
    if isinstance(result, list):
        save_result = None

        for item in result:
            item = _normalize_mcp_value(item)
            if isinstance(item, dict):
                save_result = item
                break

        if save_result is None:
            raise RuntimeError(
                f"Unexpected MCP save response: {result!r}"
            )
    elif isinstance(result, dict):
        save_result = result
    else:
        raise RuntimeError(
            f"Unexpected MCP save response: {result!r}"
        )

    if save_result.get("success") is not True:
        raise RuntimeError(
            save_result.get(
                "message",
                f"MCP saving did not confirm success: {save_result!r}",
            )
        )

    return save_result
