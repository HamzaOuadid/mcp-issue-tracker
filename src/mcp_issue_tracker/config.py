"""Loads and validates ``server.yaml``.

A single config file lists every tool's read/write classification:
:class:`ToolConfig` entries are cross-checked against each tool's own
code-declared ``read_only`` flag at registration time (see
``registry.py``), so config and code can never silently drift apart.
Same shape as the sibling `mcp-starter-template` project's ``config.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class ToolConfig(BaseModel):
    read_only: bool
    cost_units: int = 1
    description: str = ""


class RateLimitConfig(BaseModel):
    calls_per_min: int = Field(default=30, gt=0)
    cost_per_session: int = Field(default=100, gt=0)
    window_seconds: int = Field(default=60, gt=0)


class ServerConfig(BaseModel):
    dry_run: bool = True
    allowed_write_tools: list[str] = Field(default_factory=list)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    tools: dict[str, ToolConfig] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ServerConfig":
        path = Path(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

    @classmethod
    def load(cls, path: Optional[str | Path]) -> "ServerConfig":
        """Load from ``path`` if it exists, else fall back to :meth:`default`."""
        if path is not None and Path(path).exists():
            return cls.from_yaml(path)
        return cls.default()

    @classmethod
    def default(cls) -> "ServerConfig":
        """A safe-by-default config matching ``server.yaml`` exactly.

        No write tools allowlisted, dry-run on -- the fail-safe posture
        the server has even before any YAML file is read. Used by tests
        that want the real tool surface without touching the filesystem,
        and as the fallback if ``server.yaml`` can't be found at runtime.
        """
        return cls(
            dry_run=True,
            allowed_write_tools=[],
            rate_limit=RateLimitConfig(),
            tools={
                "search_issues": ToolConfig(read_only=True, cost_units=1, description="Full-text search over visible issues."),
                "get_issue": ToolConfig(read_only=True, cost_units=1, description="Fetch one issue's full detail."),
                "list_labels": ToolConfig(read_only=True, cost_units=1, description="List every known label."),
                "summarize_issue": ToolConfig(read_only=True, cost_units=1, description="Deterministic extractive issue summary."),
                "get_rate_status": ToolConfig(read_only=True, cost_units=0, description="Report the caller's remaining budget."),
                "create_issue": ToolConfig(read_only=False, cost_units=5, description="Create a new issue."),
                "add_comment": ToolConfig(read_only=False, cost_units=3, description="Add a comment to an issue."),
                "set_issue_status": ToolConfig(read_only=False, cost_units=3, description="Open or close an issue."),
            },
        )

    def tool_config(self, tool_name: str) -> Optional[ToolConfig]:
        return self.tools.get(tool_name)
