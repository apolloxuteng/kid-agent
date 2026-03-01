"""
Routing: tool registry (in-process + MCP), context, result, and Ollama tool definitions.
"""

from .context import RoutingContext
from .protocol import InProcessTool, ollama_tool_definition
from .result import ToolResult

__all__ = [
    "RoutingContext",
    "ToolResult",
    "InProcessTool",
    "ollama_tool_definition",
]
