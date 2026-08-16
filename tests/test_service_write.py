"""Write-tool tests: allowlist gating + dry-run, reusing the same
auth/read-only test approach as the read-tool suite, per the spec's
"reuse Project 2's auth/read-only test approach" testing plan.
"""

from __future__ import annotations

import pytest

from mcp_issue_tracker.errors import ErrorCode, MCPError


def test_write_tools_refused_by_default(service):
    # Default config (server.yaml as shipped) has an empty allowlist.
    with pytest.raises(MCPError) as exc_info:
        service.create_issue("token-alice", "Title", "Body")
    assert exc_info.value.code == ErrorCode.WRITE_NOT_ALLOWED

    with pytest.raises(MCPError) as exc_info:
        service.add_comment("token-alice", 1, "hello")
    assert exc_info.value.code == ErrorCode.WRITE_NOT_ALLOWED

    with pytest.raises(MCPError) as exc_info:
        service.set_issue_status("token-alice", 1, "closed")
    assert exc_info.value.code == ErrorCode.WRITE_NOT_ALLOWED


def test_default_config_is_fully_read_only(service):
    assert service.registry.default_read_only_check() is True


def test_allowlisted_but_dry_run_returns_preview_without_mutating(service):
    service.config.allowed_write_tools = ["create_issue"]
    # dry_run stays True (the default).
    before_count = service.search_issues("token-admin")["count"]
    result = service.create_issue("token-alice", "Draft title", "Draft body")
    assert result["dry_run"] is True
    assert result["would_create"]["title"] == "Draft title"
    after_count = service.search_issues("token-admin")["count"]
    assert after_count == before_count  # nothing was actually written


def test_allowlisted_and_dry_run_off_actually_writes(writable_service):
    before_count = writable_service.search_issues("token-admin")["count"]
    created = writable_service.create_issue("token-alice", "Real issue", "Real body", labels=["triage"])
    assert "dry_run" not in created
    assert created["title"] == "Real issue"
    assert created["team"] == "engineering"  # scoped to alice's own team
    assert created["created_by"] == "alice"
    after_count = writable_service.search_issues("token-admin")["count"]
    assert after_count == before_count + 1


def test_add_comment_real_write(writable_service):
    issue = writable_service.create_issue("token-alice", "Commentable", "Body")
    comment = writable_service.add_comment("token-alice", issue["id"], "First comment")
    assert comment["author"] == "alice"
    assert comment["body"] == "First comment"
    fetched = writable_service.get_issue("token-alice", issue["id"])
    assert len(fetched["comments"]) == 1


def test_cannot_comment_on_closed_issue_unless_admin(writable_service):
    issue = writable_service.create_issue("token-alice", "Will be closed", "Body")
    writable_service.set_issue_status("token-alice", issue["id"], "closed")

    with pytest.raises(MCPError) as exc_info:
        writable_service.add_comment("token-alice", issue["id"], "too late")
    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENTS

    # Admin can still comment on a closed issue.
    comment = writable_service.add_comment("token-admin", issue["id"], "admin note")
    assert comment["author"] == "root-admin"


def test_cannot_write_to_issue_outside_visible_team(writable_service):
    issue = writable_service.create_issue("token-alice", "Engineering only", "Body")  # team=engineering
    with pytest.raises(MCPError) as exc_info:
        writable_service.add_comment("token-bob", issue["id"], "sneaking in")
    assert exc_info.value.code == ErrorCode.NOT_FOUND


def test_set_issue_status_rejects_invalid_value(writable_service):
    issue = writable_service.create_issue("token-alice", "Status test", "Body")
    with pytest.raises(MCPError) as exc_info:
        writable_service.set_issue_status("token-alice", issue["id"], "archived")
    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENTS


def test_create_issue_rejects_empty_title(writable_service):
    with pytest.raises(MCPError) as exc_info:
        writable_service.create_issue("token-alice", "", "Body")
    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENTS


def test_write_denials_are_audited_with_error_code(service):
    with pytest.raises(MCPError):
        service.create_issue("token-alice", "x", "y")
    record = service.audit.records[-1]
    assert record.allowed is False
    assert record.error_code == ErrorCode.WRITE_NOT_ALLOWED
    assert record.read_or_write == "write"


def test_partial_allowlist_only_enables_named_tools(service):
    service.config.allowed_write_tools = ["create_issue"]
    service.config.dry_run = False
    # create_issue works now...
    service.create_issue("token-alice", "Allowed", "Body")
    # ...but add_comment is still refused, since it wasn't allowlisted.
    with pytest.raises(MCPError) as exc_info:
        service.add_comment("token-alice", 1, "nope")
    assert exc_info.value.code == ErrorCode.WRITE_NOT_ALLOWED
