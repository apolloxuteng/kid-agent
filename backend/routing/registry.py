"""
Tool registry: aggregates in-process tools and MCP tools. Exposes Ollama tool definitions
and runs tools by name (in-process or MCP).
"""

import logging
from typing import Any

from .context import RoutingContext
from .local_tools import ALL_IN_PROCESS_TOOLS
from .mcp_client import call_mcp_tool, get_mcp_ollama_tool_definitions, parse_mcp_tool_name
from .protocol import InProcessTool, ollama_tool_definition
from .result import ToolResult

logger = logging.getLogger(__name__)

# Map tool name -> in-process tool. MCP tools are not stored here; we detect them by namespaced name.
_tools_by_name: dict[str, InProcessTool] = {}

# One-time init: register all in-process tools
for _t in ALL_IN_PROCESS_TOOLS:
    _tools_by_name[_t.name] = _t


async def get_ollama_tool_definitions() -> list[dict]:
    """Return tool definitions in Ollama /api/chat format (merge in-process + MCP)."""
    out: list[dict] = []
    for tool in _tools_by_name.values():
        out.append(ollama_tool_definition(tool.name, tool.description, tool.parameters_schema))
    mcp_defs = await get_mcp_ollama_tool_definitions()
    out.extend(mcp_defs)
    return out


def register_in_process_tool(tool: InProcessTool) -> None:
    """Register an in-process tool. Used at startup; MCP tools are added dynamically."""
    _tools_by_name[tool.name] = tool
    logger.info("Registered in-process tool: %s", tool.name)


async def run_tool(name: str, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult | None:
    """
    Run a tool by name. Returns ToolResult or None if tool not found.
    In-process tools are run directly; MCP tools (namespaced id/name) are dispatched via MCP client.
    """
    server_id, mcp_tool_name = parse_mcp_tool_name(name)
    if server_id is not None and mcp_tool_name is not None:
        return await call_mcp_tool(server_id, mcp_tool_name, arguments or {})
    tool = _tools_by_name.get(name)
    if tool is None:
        logger.warning("Unknown tool requested: %s", name)
        return None
    try:
        return await tool.run(ctx, arguments or {})
    except Exception as e:
        logger.exception("Tool %s failed: %s", name, e)
        return ToolResult(text=f"I couldn't complete that right now ({name}). Want to try again?")


def is_tool_registered(name: str) -> bool:
    """Return True if a tool with this name is registered (in-process or MCP namespaced)."""
    if name in _tools_by_name:
        return True
    server_id, mcp_name = parse_mcp_tool_name(name)
    return server_id is not None and mcp_name is not None
