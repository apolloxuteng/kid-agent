"""
In-process tool protocol: name, description, parameters schema, run(ctx, arguments).
"""

from typing import Any, Protocol

from .context import RoutingContext
from .result import ToolResult


def ollama_tool_definition(name: str, description: str, parameters: dict[str, Any] | None = None) -> dict:
    """Build one tool definition in Ollama /api/chat format."""
    fn: dict[str, Any] = {"name": name, "description": description}
    if parameters:
        fn["parameters"] = parameters
    return {"type": "function", "function": fn}


class InProcessTool(Protocol):
    """Protocol for in-process tools. No matches() — the model decides via tool_calls."""

    @property
    def name(self) -> str:
        """Tool name (e.g. get_joke). Must be unique across in-process and MCP."""
        ...

    @property
    def description(self) -> str:
        """Short description for the model so it knows when to call this tool."""
        ...

    @property
    def parameters_schema(self) -> dict | None:
        """JSON schema for parameters, or None if no parameters. Used for Ollama tool definition."""
        ...

    async def run(self, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult:
        """Execute the tool. arguments come from the model's tool_call."""
        ...
