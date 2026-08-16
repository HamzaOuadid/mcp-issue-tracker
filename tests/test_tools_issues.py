from __future__ import annotations

import pytest

from mcp_issue_tracker.errors import ErrorCode, MCPError
from mcp_issue_tracker.tools.issues import (
    summarize_issue,
    validate_comment_body,
    validate_status,
    validate_title_body,
)


def test_summarize_includes_title_status_and_labels():
    issue = {
        "id": 7,
        "title": "Example bug",
        "status": "open",
        "labels": ["bug", "ci"],
        "body": "Short body text.",
        "comments": [],
    }
    summary = summarize_issue(issue)
    assert "#7" in summary
    assert "Example bug" in summary
    assert "open" in summary
    assert "bug, ci" in summary
    assert "no comments yet" in summary


def test_summarize_truncates_long_body():
    long_body = "x" * 500
    issue = {"id": 1, "title": "t", "status": "open", "labels": [], "body": long_body, "comments": []}
    summary = summarize_issue(issue)
    assert "..." in summary
    assert len(summary) < len(long_body) + 100


def test_summarize_includes_most_recent_comment():
    issue = {
        "id": 2,
        "title": "t",
        "status": "closed",
        "labels": [],
        "body": "b",
        "comments": [
            {"author": "alice", "body": "first"},
            {"author": "bob", "body": "most recent comment text"},
        ],
    }
    summary = summarize_issue(issue)
    assert "2 comment(s)" in summary
    assert "bob" in summary
    assert "most recent comment text" in summary


def test_validate_status_accepts_open_and_closed():
    assert validate_status("open") == "open"
    assert validate_status("CLOSED") == "closed"
    assert validate_status("  open  ") == "open"


def test_validate_status_rejects_other_values():
    with pytest.raises(MCPError) as exc_info:
        validate_status("archived")
    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENTS


def test_validate_title_body_rejects_empty():
    with pytest.raises(MCPError):
        validate_title_body("", "body")
    with pytest.raises(MCPError):
        validate_title_body("title", "   ")


def test_validate_title_body_rejects_too_long_title():
    with pytest.raises(MCPError):
        validate_title_body("x" * 201, "body")


def test_validate_title_body_accepts_valid():
    validate_title_body("A fine title", "A fine body")  # should not raise


def test_validate_comment_body_rejects_empty():
    with pytest.raises(MCPError):
        validate_comment_body("")
    with pytest.raises(MCPError):
        validate_comment_body("   ")
