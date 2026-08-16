"""FastMCP wiring: thin ``@mcp.tool()`` wrappers over ``IssueTrackerService``.

All auth-passthrough, rate limiting, write-gating, dry-run and audit
logging happens in ``service.py`` -- this module's only job is
translating MCP's JSON-RPC tool-call shape into calls against one
shared :class:`IssueTrackerService` instance, and letting a raised
``MCPError`` propagate so the real ``mcp`` SDK surfaces it to the client
as a genuine tool error, not a hand-rolled protocol.

Every tool takes a ``token`` identifying the caller (mock users:
``token-alice``, ``token-bob``, ``token-admin`` -- see ``identity.py``),
demonstrating the same auth-passthrough shape as the sibling
`mcp-starter-template` project.
"""

from __future__ import annotations

import os
from typing import Annotated, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .service import IssueTrackerService


def _env_str(name: str) -> Optional[str]:
    val = os.environ.get(name)
    return val if val else None


def _env_bool(name: str) -> Optional[bool]:
    val = os.environ.get(name)
    if val is None or val == "":
        return None
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str) -> Optional[list[str]]:
    val = os.environ.get(name)
    if val is None:
        return None
    return [x.strip() for x in val.split(",") if x.strip()]


def build_service() -> IssueTrackerService:
    """Construct the shared service, honoring env var overrides.

    ``MCP_ISSUE_TRACKER_DB`` / ``_CONFIG`` / ``_AUDIT_JSONL`` / ``_AUDIT_DB``
    override storage locations (handy for tests and for isolating a demo
    run). ``MCP_ISSUE_TRACKER_DRY_RUN`` and ``MCP_ISSUE_TRACKER_ALLOWED_WRITES``
    let a deployer flip the write-gate without editing server.yaml.
    """
    svc = IssueTrackerService(
        db_path=_env_str("MCP_ISSUE_TRACKER_DB"),
        config_path=_env_str("MCP_ISSUE_TRACKER_CONFIG"),
        jsonl_audit_path=_env_str("MCP_ISSUE_TRACKER_AUDIT_JSONL"),
        sqlite_audit_path=_env_str("MCP_ISSUE_TRACKER_AUDIT_DB"),
    )
    dry_run_override = _env_bool("MCP_ISSUE_TRACKER_DRY_RUN")
    if dry_run_override is not None:
        svc.config.dry_run = dry_run_override
    allowed_override = _env_list("MCP_ISSUE_TRACKER_ALLOWED_WRITES")
    if allowed_override is not None:
        svc.config.allowed_write_tools = allowed_override
    return svc


service = build_service()

mcp = FastMCP(
    name="mcp-issue-tracker",
    instructions=(
        "Local, real SQLite-backed issue tracker seeded with a demo corpus "
        "for the sibling `ragbench` project. Read tools (search_issues, "
        "get_issue, list_labels, summarize_issue, get_rate_status) work "
        "out of the box. Write tools (create_issue, add_comment, "
        "set_issue_status) are read-only-by-default: refused unless "
        "allowlisted in server.yaml / MCP_ISSUE_TRACKER_ALLOWED_WRITES, and "
        "even then run in dry-run preview mode unless dry_run is explicitly "
        "disabled. Every tool call requires a `token` identifying the "
        "caller (mock users: token-alice [engineering], token-bob [docs], "
        "token-admin [engineering, admin])."
    ),
)

_TokenField = Annotated[
    str,
    Field(description="Bearer token identifying the caller (e.g. 'token-alice', 'token-bob', 'token-admin')."),
]


@mcp.tool()
def search_issues(
    token: _TokenField,
    query: Annotated[str, Field(description="Free-text search over title/body. Empty string matches all visible issues.")] = "",
    status: Annotated[Optional[str], Field(description="Filter: 'open' or 'closed'.")] = None,
    label: Annotated[Optional[str], Field(description="Filter: exact label name (e.g. 'bug').")] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="Max results to return.")] = 25,
) -> dict:
    """Search issues visible to the caller (team-scoped + public issues)."""
    return service.search_issues(token, query=query, status=status, label=label, limit=limit)


@mcp.tool()
def get_issue(
    token: _TokenField,
    issue_id: Annotated[int, Field(description="Issue id.")],
) -> dict:
    """Fetch one issue's full detail: body, labels, and every comment."""
    return service.get_issue(token, issue_id)


@mcp.tool()
def list_labels(token: _TokenField) -> list[str]:
    """List every label known to the tracker."""
    return service.list_labels(token)


@mcp.tool()
def summarize_issue(
    token: _TokenField,
    issue_id: Annotated[int, Field(description="Issue id.")],
) -> str:
    """Deterministic extractive summary of one issue (no LLM call)."""
    return service.summarize_issue(token, issue_id)


@mcp.tool()
def get_rate_status(token: _TokenField) -> dict:
    """Report the caller's remaining call/cost budget for the current rate-limit window."""
    return service.get_rate_status(token)


@mcp.tool()
def create_issue(
    token: _TokenField,
    title: Annotated[str, Field(description="Issue title, max 200 characters.")],
    body: Annotated[str, Field(description="Issue body.")],
    labels: Annotated[Optional[list[str]], Field(description="Label names to attach (created if new).")] = None,
) -> dict:
    """Create a new issue, scoped to the caller's team. Write, allowlist-gated, dry-run by default."""
    return service.create_issue(token, title, body, labels=labels)


@mcp.tool()
def add_comment(
    token: _TokenField,
    issue_id: Annotated[int, Field(description="Issue id to comment on.")],
    body: Annotated[str, Field(description="Comment body.")],
) -> dict:
    """Add a comment to an existing, visible, open issue. Write, allowlist-gated, dry-run by default."""
    return service.add_comment(token, issue_id, body)


@mcp.tool()
def set_issue_status(
    token: _TokenField,
    issue_id: Annotated[int, Field(description="Issue id.")],
    status: Annotated[str, Field(description="'open' or 'closed'.")],
) -> dict:
    """Open or close an issue. Write, allowlist-gated, dry-run by default."""
    return service.set_issue_status(token, issue_id, status)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
