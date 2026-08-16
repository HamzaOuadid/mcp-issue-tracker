"""Pure domain logic for the issue tools: summarization + argument validation.

Deliberately has zero knowledge of SQLite, auth, or MCP -- every function
here takes plain data in and returns plain data out, which is what makes
it cheap to unit-test directly (see tests/test_summarize.py).
"""

from __future__ import annotations

from ..errors import ErrorCode, MCPError

VALID_STATUSES = ("open", "closed")
_BODY_SNIPPET_LEN = 160


def summarize_issue(issue: dict) -> str:
    """Deterministic extractive summary. No LLM call -- pure string logic.

    Combines: title, status, label list, a truncated body snippet, the
    comment count, and (if any) the most recent comment's snippet. This
    is intentionally simple and fully offline, matching the environment
    constraint that no LLM API keys are configured here.
    """
    title = issue["title"]
    status = issue["status"]
    labels = issue.get("labels") or []
    body = (issue.get("body") or "").strip().replace("\n", " ")
    comments = issue.get("comments") or []

    snippet = body[:_BODY_SNIPPET_LEN]
    if len(body) > _BODY_SNIPPET_LEN:
        snippet = snippet.rstrip() + "..."

    label_part = f" [{', '.join(labels)}]" if labels else ""
    parts = [f"#{issue['id']} \"{title}\" ({status}){label_part}: {snippet}"]

    if comments:
        last = comments[-1]
        last_snippet = last["body"].strip().replace("\n", " ")[:_BODY_SNIPPET_LEN]
        parts.append(
            f"{len(comments)} comment(s); most recent from {last['author']}: \"{last_snippet}\""
        )
    else:
        parts.append("no comments yet")

    return " | ".join(parts)


def validate_status(status: str) -> str:
    normalized = (status or "").strip().lower()
    if normalized not in VALID_STATUSES:
        raise MCPError(
            code=ErrorCode.INVALID_ARGUMENTS,
            message=f"status must be one of {VALID_STATUSES}, got {status!r}.",
        )
    return normalized


def validate_title_body(title: str, body: str) -> None:
    if not title or not title.strip():
        raise MCPError(code=ErrorCode.INVALID_ARGUMENTS, message="title must not be empty.")
    if not body or not body.strip():
        raise MCPError(code=ErrorCode.INVALID_ARGUMENTS, message="body must not be empty.")
    if len(title) > 200:
        raise MCPError(
            code=ErrorCode.INVALID_ARGUMENTS,
            message=f"title must be at most 200 characters, got {len(title)}.",
        )


def validate_comment_body(body: str) -> None:
    if not body or not body.strip():
        raise MCPError(code=ErrorCode.INVALID_ARGUMENTS, message="comment body must not be empty.")
