"""
MCP client: connect to configured MCP servers, list tools (namespaced), call tools, map results to ToolResult.
Optional: if mcp package is not installed or no servers configured, no MCP tools are exposed.
"""

import json
import logging
import os
from typing import Any

from .result import ToolResult

logger = logging.getLogger(__name__)

# Namespace separator for MCP tool names (e.g. nasa/apod)
MCP_NAMESPACE_SEP = "/"

_mcp_server_params: dict[str, Any] = {}  # server_id -> StdioServerParameters
_mcp_tool_defs_cache: list[dict] = []  # cached Ollama-format tool defs from MCP (namespaced)
_initialized = False


def _load_mcp_config() -> list[dict]:
    """Load MCP server config from MCP_SERVERS env (JSON) or mcp_servers.json in backend dir."""
    raw = os.environ.get("MCP_SERVERS", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "servers" in data:
                return data["servers"]
            return []
        except json.JSONDecodeError as e:
            logger.warning("MCP_SERVERS JSON invalid: %s", e)
            return []
    # Try file
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "mcp_servers.json")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "servers" in data:
                return data["servers"]
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load mcp_servers.json: %s", e)
    return []


def _mcp_tool_to_ollama(server_id: str, name: str, description: str, input_schema: dict | None) -> dict:
    """Convert MCP tool to Ollama tool definition; use namespaced name."""
    full_name = f"{server_id}{MCP_NAMESPACE_SEP}{name}"
    params = None
    if input_schema and isinstance(input_schema, dict):
        params = input_schema.get("parameters") if input_schema.get("type") == "object" else input_schema
    return {
        "type": "function",
        "function": {
            "name": full_name,
            "description": description or f"MCP tool {name} from {server_id}",
            **({"parameters": params} if params else {}),
        },
    }


async def _init_mcp_sessions() -> None:
    """Connect to all configured MCP servers and cache tool definitions. Idempotent."""
    global _initialized, _mcp_tool_defs_cache, _mcp_server_params
    if _initialized:
        return
    try:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
    except ImportError:
        logger.info("MCP package not installed; skipping MCP servers. pip install mcp to enable.")
        _initialized = True
        return

    configs = _load_mcp_config()
    if not configs:
        _initialized = True
        return

    for entry in configs:
        if not isinstance(entry, dict):
            continue
        server_id = entry.get("id") or entry.get("name")
        if not server_id:
            continue
        command = entry.get("command")
        args = entry.get("args") or []
        env = entry.get("env")
        if not command:
            logger.warning("MCP server %s has no 'command'; skipping", server_id)
            continue
        try:
            params = StdioServerParameters(command=command, args=args, env=env)
            _mcp_server_params[server_id] = params
        except Exception as e:
            logger.warning("MCP server %s failed to setup: %s", server_id, e)

    _initialized = True


async def get_mcp_ollama_tool_definitions() -> list[dict]:
    """Return Ollama-format tool definitions for all MCP servers (namespaced). Cached after first successful load."""
    global _mcp_tool_defs_cache
    await _init_mcp_sessions()
    if _mcp_tool_defs_cache:
        return _mcp_tool_defs_cache
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client
    except ImportError:
        return []
    defs: list[dict] = []
    for server_id, params in list(_mcp_server_params.items()):
        try:
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools_resp = await session.list_tools()
                    for tool in getattr(tools_resp, "tools", []) or []:
                        name = getattr(tool, "name", None) or ""
                        desc = getattr(tool, "description", None) or ""
                        schema = getattr(tool, "inputSchema", None)
                        defs.append(_mcp_tool_to_ollama(server_id, name, desc, schema))
        except Exception as e:
            logger.warning("MCP server %s list_tools failed: %s", server_id, e)
    _mcp_tool_defs_cache = defs
    return defs


async def call_mcp_tool(server_id: str, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
    """Call a tool on an MCP server. Returns ToolResult (text + optional image from content)."""
    try:
        from mcp import ClientSession, types
        from mcp.client.stdio import stdio_client
    except ImportError:
        return ToolResult(text="MCP is not installed.")

    params = _mcp_server_params.get(server_id)
    if not params:
        return ToolResult(text=f"MCP server {server_id} not configured.")
    try:
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments or {})
                if getattr(result, "isError", False):
                    err_text = str(getattr(result, "content", "Unknown error"))
                    return ToolResult(text=f"Tool failed: {err_text}")
                text_parts: list[str] = []
                image_bytes: bytes | None = None
                media_type = "image/png"
                import base64
                for content in getattr(result, "content", []) or []:
                    ctype = getattr(content, "type", None) or type(content).__name__
                    if ctype == "text" or hasattr(content, "text"):
                        text_parts.append(getattr(content, "text", str(content)))
                    elif ctype == "image" or "image" in str(ctype).lower():
                        data = getattr(content, "data", None)
                        if isinstance(data, bytes):
                            image_bytes = data
                        elif isinstance(data, str):
                            try:
                                image_bytes = base64.b64decode(data)
                            except Exception:
                                pass
                        mime = getattr(content, "mimeType", None) or getattr(content, "media_type", None)
                        if mime:
                            media_type = mime
                text = " ".join(text_parts).strip() or "Done."
                if image_bytes:
                    return ToolResult(text=text, image=(image_bytes, media_type))
                return ToolResult(text=text)
    except Exception as e:
        logger.exception("MCP call_tool %s/%s failed: %s", server_id, tool_name, e)
        return ToolResult(text=f"I couldn't complete that right now ({server_id}). Want to try again?")


def parse_mcp_tool_name(full_name: str) -> tuple[str | None, str | None]:
    """If full_name is namespaced (id/name), return (server_id, tool_name). Else (None, None)."""
    if MCP_NAMESPACE_SEP not in full_name:
        return None, None
    a, _, b = full_name.partition(MCP_NAMESPACE_SEP)
    return (a.strip(), b.strip()) if a.strip() and b.strip() else (None, None)
