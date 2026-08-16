from __future__ import annotations

import pytest

from mcp_issue_tracker.service import IssueTrackerService


@pytest.fixture
def service():
    """An IssueTrackerService over an in-memory DB, default (safe) config.

    Uses server.yaml's real tool declarations via config_path pointing at
    the repo's own server.yaml, so tests exercise the actual shipped
    config, not a synthetic one.
    """
    svc = IssueTrackerService(
        db_path=":memory:",
        config_path="server.yaml",
        jsonl_audit_path=None,
        sqlite_audit_path=None,
    )
    yield svc
    svc.close()


@pytest.fixture
def writable_service():
    """Same as ``service`` but with all write tools allowlisted and dry_run off."""
    svc = IssueTrackerService(
        db_path=":memory:",
        config_path="server.yaml",
        jsonl_audit_path=None,
        sqlite_audit_path=None,
    )
    svc.config.allowed_write_tools = ["create_issue", "add_comment", "set_issue_status"]
    svc.config.dry_run = False
    yield svc
    svc.close()
