"""Edge cases called out in the spec's section 9 (adapted to this domain,
since this server sits over a local SQLite tracker rather than a live
third-party API -- see README's Risks section for that scope decision):

- "Target API changes/deprecates an endpoint" -> schema_version pinning.
- "Rate limit exhausted mid-session -- must degrade gracefully, not crash".
- Config/code classification drift is caught at startup, not at runtime.
- SQL-injection-shaped input doesn't crash or leak data (see test_db.py
  for the storage-layer version of this).
"""

from __future__ import annotations

import pytest

from mcp_issue_tracker import db
from mcp_issue_tracker.config import ServerConfig
from mcp_issue_tracker.errors import ErrorCode, MCPError
from mcp_issue_tracker.service import IssueTrackerService


def test_schema_version_is_pinned_and_stable():
    conn = db.get_connection(":memory:")
    db.init_schema(conn)
    version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
    assert version["value"] == db.SCHEMA_VERSION
    assert db.SCHEMA_VERSION.count(".") == 2  # semver-shaped


def test_rate_limit_exhausted_mid_session_degrades_gracefully():
    """A caller that blows their budget gets a structured error on every
    subsequent call in that window -- the process keeps running and other
    callers are unaffected. It must not crash the server."""
    config = ServerConfig.default()
    config.rate_limit.calls_per_min = 2
    config.rate_limit.cost_per_session = 100
    svc = IssueTrackerService(db_path=":memory:", config_path=None, jsonl_audit_path=None, sqlite_audit_path=None)
    svc.config = config
    svc.limiter._config = config.rate_limit  # apply the tightened cap

    svc.search_issues("token-alice")  # call 1: ok
    svc.search_issues("token-alice")  # call 2: ok

    # call 3: exhausted, must raise a structured error, not crash.
    with pytest.raises(MCPError) as exc_info:
        svc.search_issues("token-alice")
    assert exc_info.value.code == ErrorCode.RATE_LIMIT_EXCEEDED
    assert exc_info.value.retry_after is not None

    # The server process itself is still alive: a different caller
    # (different token/session) is unaffected by alice's exhaustion.
    result = svc.search_issues("token-bob")
    assert result["count"] >= 0

    # And alice herself gets the same clear, structured denial again
    # rather than a crash or a silent no-op, on a repeat attempt.
    with pytest.raises(MCPError) as exc_info2:
        svc.search_issues("token-alice")
    assert exc_info2.value.code == ErrorCode.RATE_LIMIT_EXCEEDED
    svc.close()


def test_service_constructs_cleanly_from_shipped_server_yaml():
    """The real server.yaml in the repo root must agree with the code's
    own TOOL_DECLARATIONS classification, or construction raises at
    startup (fail fast) rather than serving a misconfigured tool later."""
    svc = IssueTrackerService(db_path=":memory:", config_path="server.yaml", jsonl_audit_path=None, sqlite_audit_path=None)
    described = svc.registry.describe_all()
    assert len(described) == 8
    svc.close()


def test_missing_config_file_falls_back_to_safe_default(tmp_path):
    missing_path = tmp_path / "does_not_exist.yaml"
    svc = IssueTrackerService(db_path=":memory:", config_path=missing_path, jsonl_audit_path=None, sqlite_audit_path=None)
    assert svc.config.dry_run is True
    assert svc.config.allowed_write_tools == []
    svc.close()


def test_search_with_sql_injection_shaped_query_does_not_crash_service(service):
    result = service.search_issues("token-admin", query="'; DROP TABLE issues; --")
    assert result["count"] == 0
    # The corpus must still be intact for a normal query afterward.
    sanity = service.search_issues("token-admin", query="")
    assert sanity["count"] == 15


def test_get_issue_with_non_integer_like_id_is_handled(service):
    # FastMCP/pydantic would normally reject a non-int at the transport
    # boundary; at the service layer a nonexistent numeric id must still
    # come back as a clean NOT_FOUND, not a raw exception.
    with pytest.raises(MCPError) as exc_info:
        service.get_issue("token-alice", -1)
    assert exc_info.value.code == ErrorCode.NOT_FOUND


def test_unknown_tool_name_is_tool_not_found(service):
    with pytest.raises(MCPError) as exc_info:
        service._guard("not_a_real_tool", "token-alice", lambda user: None)
    assert exc_info.value.code == ErrorCode.TOOL_NOT_FOUND
