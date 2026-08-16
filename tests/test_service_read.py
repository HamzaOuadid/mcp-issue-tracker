"""User story 2: "As a user of the server, I can search/fetch real content."

These tests exercise IssueTrackerService's read tools directly against
the real seeded SQLite corpus (see seed_data.py) -- no mocks standing in
for the data layer.
"""

from __future__ import annotations

import pytest

from mcp_issue_tracker.errors import ErrorCode, MCPError


def test_search_issues_returns_real_seeded_results(service):
    result = service.search_issues("token-alice", query="ragbench")
    assert result["count"] > 0
    assert all("ragbench" in (r["title"] + r["body"]).lower() for r in result["results"])


def test_search_empty_query_returns_all_visible_issues(service):
    alice_result = service.search_issues("token-alice")
    admin_result = service.search_issues("token-admin")
    # Admin (bypasses team scoping) must see at least as many as any
    # single team member.
    assert admin_result["count"] >= alice_result["count"]
    assert admin_result["count"] == 15  # full seed corpus


def test_two_users_see_different_results_same_query(service):
    alice_result = service.search_issues("token-alice", query="")  # engineering
    bob_result = service.search_issues("token-bob", query="")  # docs
    alice_titles = {r["title"] for r in alice_result["results"]}
    bob_titles = {r["title"] for r in bob_result["results"]}
    assert alice_titles != bob_titles


def test_search_by_label_and_status(service):
    bugs = service.search_issues("token-admin", label="bug")
    assert bugs["count"] > 0
    assert all("bug" in r["labels"] for r in bugs["results"])

    closed = service.search_issues("token-admin", status="closed")
    assert closed["count"] > 0
    assert all(r["status"] == "closed" for r in closed["results"])


def test_get_issue_returns_full_detail(service):
    issue = service.get_issue("token-admin", 1)
    assert issue["id"] == 1
    assert "labels" in issue
    assert "comments" in issue


def test_get_issue_cross_team_not_visible(service):
    # Issue 1 is engineering-scoped (see seed_data.py); bob is docs.
    with pytest.raises(MCPError) as exc_info:
        service.get_issue("token-bob", 1)
    assert exc_info.value.code == ErrorCode.NOT_FOUND


def test_get_issue_admin_sees_all_teams(service):
    issue = service.get_issue("token-admin", 1)
    assert issue is not None


def test_get_nonexistent_issue_raises_not_found(service):
    with pytest.raises(MCPError) as exc_info:
        service.get_issue("token-alice", 999999)
    assert exc_info.value.code == ErrorCode.NOT_FOUND


def test_list_labels_returns_real_labels(service):
    labels = service.list_labels("token-alice")
    assert "bug" in labels
    assert "enhancement" in labels
    assert labels == sorted(labels)


def test_summarize_issue_is_non_llm_and_deterministic(service):
    summary1 = service.summarize_issue("token-admin", 1)
    summary2 = service.summarize_issue("token-admin", 1)
    assert summary1 == summary2
    assert isinstance(summary1, str)
    assert len(summary1) > 0


def test_get_rate_status_reports_budget(service):
    status = service.get_rate_status("token-alice")
    assert "calls_remaining" in status
    assert "cost_remaining" in status
    assert "reset_at_seconds" in status


def test_missing_token_rejected_on_every_read_tool(service):
    for call in [
        lambda: service.search_issues(None),
        lambda: service.get_issue(None, 1),
        lambda: service.list_labels(None),
        lambda: service.summarize_issue(None, 1),
        lambda: service.get_rate_status(None),
    ]:
        with pytest.raises(MCPError) as exc_info:
            call()
        assert exc_info.value.code == ErrorCode.UNAUTHENTICATED


def test_invalid_token_rejected(service):
    with pytest.raises(MCPError) as exc_info:
        service.search_issues("totally-fake-token")
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED


def test_read_tools_are_audited(service):
    service.search_issues("token-alice", query="bug")
    assert len(service.audit.records) == 1
    record = service.audit.records[0]
    assert record.tool_name == "search_issues"
    assert record.read_or_write == "read"
    assert record.allowed is True
    assert record.user_id == "alice"
