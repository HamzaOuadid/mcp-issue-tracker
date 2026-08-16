"""Structured error contract.

Every rejection the server can produce (auth failure, disallowed write,
rate limit, unknown tool, missing/invisible issue, bad arguments) is
expressed as an :class:`MCPError` so callers get a machine-readable
``code`` instead of a stack trace or a silent no-op. Ported unchanged
from the sibling `mcp-starter-template` project's error contract so both
servers fail in the same shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class ErrorCode:
    """Canonical error codes returned to MCP clients."""

    UNAUTHENTICATED = "UNAUTHENTICATED"
    WRITE_NOT_ALLOWED = "WRITE_NOT_ALLOWED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    NOT_FOUND = "NOT_FOUND"


@dataclass
class MCPError(Exception):
    """A structured, denial-not-crash error.

    Every field on this object is what gets written to the audit trail
    and (when returned over the wire, via FastMCP's error surfacing) is
    what the calling MCP client sees -- a reviewer reading a log line or
    an error response can tell exactly why a call was denied without
    re-deriving it from a traceback.
    """

    code: str
    message: str
    retry_after: Optional[float] = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, f"[{self.code}] {self.message}")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.retry_after is not None:
            payload["retry_after"] = self.retry_after
        if self.details:
            payload["details"] = self.details
        return payload
