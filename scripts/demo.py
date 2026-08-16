"""Demo script: drives the real MCP server over stdio and prints real
tool results. Used to generate the "Demo run" section of README.md --
every line of output in that section came from actually running this.

Usage:
    python scripts/demo.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]


def _print_header(title: str) -> None:
    print()
    print(f"$ {title}")


def _print_result(call_result) -> None:
    if call_result.isError:
        print(f"  ERROR: {call_result.content[0].text}")
        return
    if call_result.structuredContent is not None:
        payload = call_result.structuredContent
        if isinstance(payload, dict) and set(payload.keys()) == {"result"}:
            payload = payload["result"]
        print(json.dumps(payload, indent=2)[:1600])
        return
    block = call_result.content[0]
    if isinstance(block, types.TextContent):
        print(f"  {block.text}")


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        env = {
            "MCP_ISSUE_TRACKER_DB": str(tmp_path / "issue_tracker.db"),
            "MCP_ISSUE_TRACKER_CONFIG": str(REPO_ROOT / "server.yaml"),
            "MCP_ISSUE_TRACKER_AUDIT_JSONL": str(tmp_path / "audit.jsonl"),
            "MCP_ISSUE_TRACKER_AUDIT_DB": str(tmp_path / "audit.db"),
        }
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_issue_tracker.server"],
            env=env,
            cwd=str(REPO_ROOT),
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                _print_header("list_tools()")
                tools = await session.list_tools()
                for t in tools.tools:
                    print(f"  - {t.name}: {t.description}")

                _print_header('search_issues(token="token-alice", query="ragbench eval")')
                r = await session.call_tool(
                    "search_issues", {"token": "token-alice", "query": "ragbench eval"}
                )
                _print_result(r)

                _print_header('search_issues(token="token-bob", label="docs")  # bob is on the docs team')
                r = await session.call_tool("search_issues", {"token": "token-bob", "label": "docs"})
                _print_result(r)

                _print_header('get_issue(token="token-admin", issue_id=1)')
                r = await session.call_tool("get_issue", {"token": "token-admin", "issue_id": 1})
                _print_result(r)

                _print_header('summarize_issue(token="token-admin", issue_id=1)')
                r = await session.call_tool("summarize_issue", {"token": "token-admin", "issue_id": 1})
                print(f"  {r.content[0].text}")

                _print_header('list_labels(token="token-alice")')
                r = await session.call_tool("list_labels", {"token": "token-alice"})
                _print_result(r)

                _print_header('get_rate_status(token="token-alice")')
                r = await session.call_tool("get_rate_status", {"token": "token-alice"})
                _print_result(r)

                _print_header('create_issue(...)  # default config: write tools are NOT allowlisted')
                r = await session.call_tool(
                    "create_issue", {"token": "token-alice", "title": "Should be refused", "body": "x"}
                )
                _print_result(r)

                _print_header('get_issue(token="token-bob", issue_id=1)  # issue 1 is engineering-scoped, bob is docs')
                r = await session.call_tool("get_issue", {"token": "token-bob", "issue_id": 1})
                _print_result(r)

                _print_header('search_issues(token="not-a-real-token")  # missing/invalid token')
                r = await session.call_tool("search_issues", {"token": "not-a-real-token"})
                _print_result(r)


if __name__ == "__main__":
    asyncio.run(main())
