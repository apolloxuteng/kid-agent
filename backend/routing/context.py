"""
Routing context: single input type passed into tool execution.
"""

from dataclasses import dataclass


@dataclass
class RoutingContext:
    """Input passed to every tool (in-process or MCP)."""

    user_message: str
    last_assistant_message: str | None
    profile_id: str
    conversation_history: list[dict] | None = None
