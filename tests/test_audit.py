from __future__ import annotations

import json

from mcp_issue_tracker.audit import AuditLogger, AuditRecord, now


def make_record(**overrides):
    base = dict(
        timestamp=now(),
        session_id="s1",
        user_id="alice",
        tool_name="search_issues",
        read_or_write="read",
        dry_run=False,
        allowed=True,
        latency_ms=1.23,
    )
    base.update(overrides)
    return AuditRecord(**base)


def test_records_kept_in_memory():
    logger = AuditLogger()
    logger.log(make_record())
    logger.log(make_record(tool_name="get_issue"))
    assert len(logger.records) == 2


def test_writes_jsonl_file(tmp_path):
    jsonl_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(jsonl_path=jsonl_path)
    logger.log(make_record(detail="ok"))
    logger.close()

    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["tool_name"] == "search_issues"
    assert parsed["allowed"] is True


def test_writes_sqlite_and_is_queryable(tmp_path):
    db_path = tmp_path / "audit.db"
    logger = AuditLogger(sqlite_path=db_path)
    logger.log(make_record(session_id="s1", allowed=True))
    logger.log(make_record(session_id="s2", allowed=False, error_code="UNAUTHENTICATED"))

    rows = logger.query()
    assert len(rows) == 2

    s1_rows = logger.query(session_id="s1")
    assert len(s1_rows) == 1
    assert s1_rows[0]["allowed"] == 1
    logger.close()


def test_denied_calls_are_logged_with_error_code():
    logger = AuditLogger()
    logger.log(make_record(allowed=False, error_code="RATE_LIMIT_EXCEEDED", detail="too many calls"))
    record = logger.records[0]
    assert record.allowed is False
    assert record.error_code == "RATE_LIMIT_EXCEEDED"


def test_dry_run_flag_recorded():
    logger = AuditLogger()
    logger.log(make_record(read_or_write="write", dry_run=True))
    assert logger.records[0].dry_run is True
