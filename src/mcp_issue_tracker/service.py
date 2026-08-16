"""Guarded dispatch: wires auth, rate limiting, write-gating, dry-run,
and audit logging around the real SQLite issue tracker.

Every public method here corresponds 1:1 to an MCP tool in ``server.py``.
Each call goes through the same pipeline, in this order:

1. Resolve the caller's identity from ``token`` (reject if missing/invalid).
2. Consume from that caller's rate/spend budget (reject if exhausted).
3. For write tools: confirm the tool is allowlisted (reject if not).
4. Run the actual domain logic. Write tools additionally check the
   global ``dry_run`` flag and return a synthetic preview instead of
   mutating the database when it's on (the default).
5. Write one audit record either way -- success or a structured denial.

Kept independent of the MCP transport entirely so tests can call these
methods directly without spinning up a server process.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional, TypeVar

from . import audit as audit_mod
from . import db
from .audit import AuditLogger, AuditRecord
from .auth import AuthMiddleware
from .config import ServerConfig
from .errors import ErrorCode, MCPError
from .identity import MockIdentityProvider, User
from .limiter import SessionLimiter
from .registry import ToolRegistry, ToolSpec
from .seed_data import ISSUES as SEED_ISSUES
from .tools import issues as issue_logic

T = TypeVar("T")

# The server's own code-declared classification for every tool, kept
# separate from server.yaml's copy so ToolRegistry.register() can
# actually cross-check the two disagree-or-not (see registry.py).
TOOL_DECLARATIONS: dict[str, ToolSpec] = {
    "search_issues": ToolSpec(name="search_issues", read_only=True, cost_units=1, description="Full-text search over visible issues."),
    "get_issue": ToolSpec(name="get_issue", read_only=True, cost_units=1, description="Fetch one issue's full detail."),
    "list_labels": ToolSpec(name="list_labels", read_only=True, cost_units=1, description="List every known label."),
    "summarize_issue": ToolSpec(name="summarize_issue", read_only=True, cost_units=1, description="Deterministic extractive issue summary."),
    "get_rate_status": ToolSpec(name="get_rate_status", read_only=True, cost_units=0, description="Report the caller's remaining budget."),
    "create_issue": ToolSpec(name="create_issue", read_only=False, cost_units=5, description="Create a new issue."),
    "add_comment": ToolSpec(name="add_comment", read_only=False, cost_units=3, description="Add a comment to an issue."),
    "set_issue_status": ToolSpec(name="set_issue_status", read_only=False, cost_units=3, description="Open or close an issue."),
}


def default_db_path() -> Path:
    return Path.home() / ".mcp-issue-tracker" / "issue_tracker.db"


def default_config_path() -> Path:
    # src/mcp_issue_tracker/service.py -> parents[2] is the repo root,
    # where server.yaml lives (works for both an editable install and
    # running straight out of the source tree).
    return Path(__file__).resolve().parents[2] / "server.yaml"


def default_audit_dir() -> Path:
    return Path.home() / ".mcp-issue-tracker"


def _visible(row, user: User) -> bool:
    team = row["team"]
    return team is None or team == user.team or user.is_admin


class IssueTrackerService:
    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        config_path: Optional[str | Path] = None,
        jsonl_audit_path: Optional[str | Path] = None,
        sqlite_audit_path: Optional[str | Path] = None,
        identity_provider: Optional[MockIdentityProvider] = None,
        clock: Optional[Callable[[], float]] = None,
        seed_issues: Optional[list[dict]] = None,
        auto_seed: bool = True,
    ) -> None:
        resolved_config = config_path if config_path is not None else default_config_path()
        self.config = ServerConfig.load(resolved_config)

        resolved_db = db_path if db_path is not None else default_db_path()
        self.conn = db.get_connection(resolved_db)
        db.init_schema(self.conn)
        if auto_seed:
            db.seed(self.conn, seed_issues if seed_issues is not None else SEED_ISSUES)

        self.identity_provider = identity_provider or MockIdentityProvider()
        self.auth = AuthMiddleware(self.identity_provider)
        self.audit = AuditLogger(jsonl_audit_path, sqlite_audit_path)
        self.limiter = SessionLimiter(self.config.rate_limit, clock=clock)

        self.registry = ToolRegistry(self.config)
        for spec in TOOL_DECLARATIONS.values():
            self.registry.register(spec)

    def close(self) -> None:
        self.conn.close()
        self.audit.close()

    def __enter__(self) -> "IssueTrackerService":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Guarded dispatch
    # ------------------------------------------------------------------

    def _session_id(self, token: Optional[str]) -> str:
        return token or "anonymous"

    def _guard(self, tool_name: str, token: Optional[str], work: Callable[[User], T]) -> T:
        start = time.monotonic()
        spec = self.registry.get(tool_name)
        if spec is None:
            raise MCPError(code=ErrorCode.TOOL_NOT_FOUND, message=f"Unknown tool {tool_name!r}.")

        read_or_write = "read" if spec.read_only else "write"
        session_id = self._session_id(token)
        user: Optional[User] = None
        dry_run_flag = False

        try:
            user = self.auth.authenticate(token)
            self.limiter.check_and_consume(session_id, spec.cost_units)

            if not spec.read_only:
                if not self.registry.is_write_allowed(tool_name):
                    raise MCPError(
                        code=ErrorCode.WRITE_NOT_ALLOWED,
                        message=(
                            f"Write tool {tool_name!r} is not enabled. Add it to "
                            "allowed_write_tools in server.yaml (or "
                            "MCP_ISSUE_TRACKER_ALLOWED_WRITES) to allow it."
                        ),
                    )
                dry_run_flag = self.config.dry_run

            result = work(user)
            if isinstance(result, dict) and result.get("dry_run"):
                dry_run_flag = True

            self.audit.log(
                AuditRecord(
                    timestamp=audit_mod.now(),
                    session_id=session_id,
                    user_id=user.user_id,
                    tool_name=tool_name,
                    read_or_write=read_or_write,
                    dry_run=dry_run_flag,
                    allowed=True,
                    latency_ms=(time.monotonic() - start) * 1000,
                )
            )
            return result
        except MCPError as e:
            user_id = user.user_id if user else (token or "anonymous")
            self.audit.log(
                AuditRecord(
                    timestamp=audit_mod.now(),
                    session_id=session_id,
                    user_id=user_id,
                    tool_name=tool_name,
                    read_or_write=read_or_write,
                    dry_run=dry_run_flag,
                    allowed=False,
                    latency_ms=(time.monotonic() - start) * 1000,
                    error_code=e.code,
                    detail=e.message,
                )
            )
            raise

    # ------------------------------------------------------------------
    # Read tools
    # ------------------------------------------------------------------

    def search_issues(
        self,
        token: Optional[str],
        query: str = "",
        status: Optional[str] = None,
        label: Optional[str] = None,
        limit: int = 25,
    ) -> dict:
        def work(user: User) -> dict:
            if status is not None:
                issue_logic.validate_status(status)
            results = db.search_issues(
                self.conn, query, user.team, user.is_admin, status=status, label=label, limit=limit
            )
            return {"count": len(results), "results": results}

        return self._guard("search_issues", token, work)

    def get_issue(self, token: Optional[str], issue_id: int) -> dict:
        def work(user: User) -> dict:
            result = db.get_issue(self.conn, issue_id, user.team, user.is_admin)
            if result is None:
                raise MCPError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Issue {issue_id} was not found or is not visible to you.",
                )
            return result

        return self._guard("get_issue", token, work)

    def list_labels(self, token: Optional[str]) -> list[str]:
        return self._guard("list_labels", token, lambda user: db.list_labels(self.conn))

    def summarize_issue(self, token: Optional[str], issue_id: int) -> str:
        def work(user: User) -> str:
            issue = db.get_issue(self.conn, issue_id, user.team, user.is_admin)
            if issue is None:
                raise MCPError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Issue {issue_id} was not found or is not visible to you.",
                )
            return issue_logic.summarize_issue(issue)

        return self._guard("summarize_issue", token, work)

    def get_rate_status(self, token: Optional[str]) -> dict:
        return self._guard("get_rate_status", token, lambda user: self.limiter.status(self._session_id(token)))

    # ------------------------------------------------------------------
    # Write tools (allowlist-gated, dry-run by default)
    # ------------------------------------------------------------------

    def create_issue(
        self,
        token: Optional[str],
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict:
        def work(user: User) -> dict:
            issue_logic.validate_title_body(title, body)
            if self.config.dry_run:
                return {
                    "dry_run": True,
                    "would_create": {
                        "title": title,
                        "body": body,
                        "team": user.team,
                        "created_by": user.user_id,
                        "labels": labels or [],
                    },
                }
            return db.create_issue(self.conn, title, body, user.team, user.user_id, labels)

        return self._guard("create_issue", token, work)

    def add_comment(self, token: Optional[str], issue_id: int, body: str) -> dict:
        def work(user: User) -> dict:
            issue_logic.validate_comment_body(body)
            raw = db.issue_exists_raw(self.conn, issue_id)
            if raw is None or not _visible(raw, user):
                raise MCPError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Issue {issue_id} was not found or is not visible to you.",
                )
            if raw["status"] == "closed" and not user.is_admin:
                raise MCPError(
                    code=ErrorCode.INVALID_ARGUMENTS,
                    message=f"Issue {issue_id} is closed; ask an admin to reopen it before commenting.",
                )
            if self.config.dry_run:
                return {
                    "dry_run": True,
                    "would_add_comment": {"issue_id": issue_id, "author": user.user_id, "body": body},
                }
            return db.add_comment(self.conn, issue_id, user.user_id, body)

        return self._guard("add_comment", token, work)

    def set_issue_status(self, token: Optional[str], issue_id: int, status: str) -> dict:
        def work(user: User) -> dict:
            normalized = issue_logic.validate_status(status)
            raw = db.issue_exists_raw(self.conn, issue_id)
            if raw is None or not _visible(raw, user):
                raise MCPError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Issue {issue_id} was not found or is not visible to you.",
                )
            if self.config.dry_run:
                return {"dry_run": True, "would_set_status": {"issue_id": issue_id, "status": normalized}}
            return db.set_issue_status(self.conn, issue_id, normalized)

        return self._guard("set_issue_status", token, work)
