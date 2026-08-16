"""End-to-end test against the REAL MCP protocol.

This spawns `python -m mcp_issue_tracker.server` as a subprocess and
talks to it over stdio using the official `mcp` SDK's client
(`mcp.client.stdio` + `ClientSession`) -- the same transport Claude
Desktop/Claude Code use. This proves the tools are wired into a genuine
MCP server, not a hand-rolled substitute for the protocol.
"""

from __future__ import annotations

import json
import sys

import pytest
from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client


def _server_params(tmp_path, extra_env: dict | None = None) -> StdioServerParameters:
    env = {
        "MCP_ISSUE_TRACKER_DB": str(tmp_path / "issue_tracker.db"),
        "MCP_ISSUE_TRACKER_CONFIG": "server.yaml",
        "MCP_ISSUE_TRACKER_AUDIT_JSONL": str(tmp_path / "audit.jsonl"),
        "MCP_ISSUE_TRACKER_AUDIT_DB": str(tmp_path / "audit.db"),
    }
    if extra_env:
        env.update(extra_env)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_issue_tracker.server"],
        env=env,
    )


async def test_list_tools_exposes_all_eight_tools(tmp_path):
    params = _server_params(tmp_path)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            names = {t.name for t in result.tools}
            assert names == {
                "search_issues",
                "get_issue",
                "list_labels",
                "summarize_issue",
                "get_rate_status",
                "create_issue",
                "add_comment",
                "set_issue_status",
            }


async def test_call_search_issues_returns_real_results(tmp_path):
    params = _server_params(tmp_path)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_issues", {"token": "token-admin", "query": "ragbench"})
            assert result.isError is not True
            payload = _first_json_payload(result)
            assert payload["count"] > 0
            assert any("ragbench" in (r["title"] + r["body"]).lower() for r in payload["results"])


async def test_call_get_issue_and_summarize_round_trip(tmp_path):
    params = _server_params(tmp_path)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            issue_result = await session.call_tool("get_issue", {"token": "token-admin", "issue_id": 1})
            issue = _first_json_payload(issue_result)
            assert issue["id"] == 1

            summary_result = await session.call_tool("summarize_issue", {"token": "token-admin", "issue_id": 1})
            summary_text = summary_result.content[0].text
            assert "#1" in summary_text


async def test_missing_token_surfaces_as_real_mcp_tool_error(tmp_path):
    params = _server_params(tmp_path)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_issues", {"token": "not-a-real-token"})
            assert result.isError is True
            assert "UNAUTHENTICATED" in result.content[0].text


async def test_write_tool_refused_over_real_protocol_when_not_allowlisted(tmp_path):
    params = _server_params(tmp_path)  # no MCP_ISSUE_TRACKER_ALLOWED_WRITES set
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "create_issue", {"token": "token-alice", "title": "x", "body": "y"}
            )
            assert result.isError is True
            assert "WRITE_NOT_ALLOWED" in result.content[0].text


async def test_write_tool_allowlisted_and_dry_run_disabled_actually_creates(tmp_path):
    params = _server_params(
        tmp_path,
        extra_env={
            "MCP_ISSUE_TRACKER_ALLOWED_WRITES": "create_issue",
            "MCP_ISSUE_TRACKER_DRY_RUN": "false",
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "create_issue",
                {"token": "token-alice", "title": "Created over MCP", "body": "Real body"},
            )
            assert result.isError is not True
            payload = _first_json_payload(result)
            assert payload["title"] == "Created over MCP"
            assert "dry_run" not in payload


def _first_json_payload(call_result) -> dict:
    """Extract and parse the first text content block's JSON payload."""
    block = call_result.content[0]
    assert isinstance(block, types.TextContent)
    return json.loads(block.text)

