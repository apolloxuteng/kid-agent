"""
Tool result: what a tool returns. Text is sent to the model; image is for client attachments.
"""

from dataclasses import dataclass


@dataclass
class ToolResult:
    """
    Result from a tool (in-process or MCP).
    - text: sent to the model as the tool result content (required; use summary or error message).
    - image: optional (bytes, media_type); collected into response attachments for the client.
    """

    text: str
    image: tuple[bytes, str] | None = None  # (image_bytes, media_type)
