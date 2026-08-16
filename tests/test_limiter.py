from __future__ import annotations

import pytest

from mcp_issue_tracker.config import RateLimitConfig
from mcp_issue_tracker.errors import ErrorCode, MCPError
from mcp_issue_tracker.limiter import SessionLimiter


def make_limiter(calls_per_min=3, cost_per_session=10, window_seconds=60, clock=None):
    cfg = RateLimitConfig(calls_per_min=calls_per_min, cost_per_session=cost_per_session, window_seconds=window_seconds)
    return SessionLimiter(cfg, clock=clock)


def test_allows_calls_within_budget():
    limiter = make_limiter(calls_per_min=3, cost_per_session=10)
    limiter.check_and_consume("s1", 1)
    limiter.check_and_consume("s1", 1)
    usage = limiter.usage("s1")
    assert usage["call_count"] == 2
    assert usage["cost_used"] == 2


def test_exceeding_call_count_raises_rate_limit_exceeded():
    limiter = make_limiter(calls_per_min=2, cost_per_session=100)
    limiter.check_and_consume("s1", 1)
    limiter.check_and_consume("s1", 1)
    with pytest.raises(MCPError) as exc_info:
        limiter.check_and_consume("s1", 1)
    assert exc_info.value.code == ErrorCode.RATE_LIMIT_EXCEEDED
    assert exc_info.value.retry_after is not None


def test_exceeding_cost_budget_raises_even_under_call_cap():
    limiter = make_limiter(calls_per_min=100, cost_per_session=5)
    limiter.check_and_consume("s1", 3)
    with pytest.raises(MCPError):
        limiter.check_and_consume("s1", 3)  # would be 6 > 5


def test_sessions_are_independent():
    limiter = make_limiter(calls_per_min=1, cost_per_session=10)
    limiter.check_and_consume("alice", 1)
    with pytest.raises(MCPError):
        limiter.check_and_consume("alice", 1)
    # bob's own budget is untouched by alice's exhaustion.
    limiter.check_and_consume("bob", 1)


def test_exhausted_session_blocks_every_subsequent_call_not_just_the_one_that_tripped_it():
    limiter = make_limiter(calls_per_min=1, cost_per_session=100)
    limiter.check_and_consume("s1", 1)
    for _ in range(5):
        with pytest.raises(MCPError):
            limiter.check_and_consume("s1", 1)


def test_window_resets_after_elapsed_time():
    t = [0.0]
    limiter = make_limiter(calls_per_min=1, cost_per_session=100, window_seconds=10, clock=lambda: t[0])
    limiter.check_and_consume("s1", 1)
    with pytest.raises(MCPError):
        limiter.check_and_consume("s1", 1)
    t[0] = 11.0  # past the window
    limiter.check_and_consume("s1", 1)  # should succeed again
    assert limiter.usage("s1")["call_count"] == 1


def test_status_reports_calls_and_cost_remaining():
    limiter = make_limiter(calls_per_min=5, cost_per_session=20, window_seconds=60)
    status = limiter.status("fresh-session")
    assert status["calls_remaining"] == 5
    assert status["cost_remaining"] == 20

    limiter.check_and_consume("fresh-session", 4)
    status = limiter.status("fresh-session")
    assert status["calls_remaining"] == 4
    assert status["cost_remaining"] == 16
