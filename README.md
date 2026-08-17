# mcp-issue-tracker

An MCP server over a **real, local, SQLite-backed issue tracker** — full CRUD (search, fetch, summarize, create, comment, close/reopen), a real seeded corpus, and the same auth-passthrough + read-only-by-default security pattern used across this portfolio's other MCP work.

Built as **Project 10** in a 20-project portfolio: *"a second, distinct MCP server implementation, sharing the same security philosophy as an earlier one, applied to a different domain."*

## Which variant, and why

The spec (`10-second-mcp-server-docs-wiki-search-or-issue-tracker.md`) offered a choice: docs/wiki search, or an issue tracker. I built the **issue tracker**.

Reasoning: a docs/wiki server is essentially two tools (`search`, `fetch`) over static content. An issue tracker needs a real data model (issues, comments, labels, status transitions), real authorization decisions (who can see what, who can write what), and a natural place to demonstrate the write-gating half of the security pattern — the spec's non-goal explicitly allows write operations "if explicitly justified and gated the same way" as the reference implementation, and CRUD is exactly that justification. It's the more concretely useful demo of the pattern, not just the read half of it.

## Cross-reference: shared pattern with `mcp-starter-template`

This server intentionally reuses the security architecture from the sibling **[`mcp-starter-template`](https://github.com/HamzaOuadid/mcp-starter-template)** project (Project 2 in this portfolio) rather than re-deriving it:

| Pattern | `mcp-starter-template` | `mcp-issue-tracker` (this repo) |
|---|---|---|
| Config-driven tool classification | `server.yaml`: `tools.<name>.read_only` | Same shape, same file name — [`server.yaml`](server.yaml) |
| Code/config cross-check at startup | `registry.py`: `ToolRegistrationError` on mismatch | Ported near-verbatim — [`registry.py`](src/mcp_issue_tracker/registry.py) |
| Read-only-by-default | Write tools refused unless in `allowed_write_tools` | Identical — plus a `dry_run` second gate (see below) |
| Auth passthrough | `auth.py` + `identity.py`: mock bearer tokens resolve to a real `User`, never a shared credential | Identical design, domain-appropriate users (`token-alice`/`token-bob`/`token-admin`) |
| Structured errors | `errors.py`: `MCPError{code, message, retry_after?}` | Identical, `+NOT_FOUND` for issue lookups |
| Audit trail | `audit.py`: JSONL + SQLite `audit_log`, every call logged | Identical dual-sink design |
| Rate limiting | `limiter.py`: fixed-window per-session cap | Identical, plus a `get_rate_status` tool surfacing it (the spec's `api_rate_state` data model, made queryable) |

[`mcp-starter-template`](https://github.com/HamzaOuadid/mcp-starter-template) links back to this repo under its own cross-reference section, so the pattern is documented from both directions.

## Architecture

```
Claude Desktop / Claude Code (MCP client)
        │  JSON-RPC over stdio
        ▼
  server.py            FastMCP tool definitions (mcp SDK) — 8 tools
        │
        ▼
  service.py            Guarded dispatch: auth → rate-limit → write-gate → dry-run → audit
        │
        ├── auth.py + identity.py    Bearer-token → User (mock IdP, never a shared credential)
        ├── config.py                Loads/validates server.yaml
        ├── registry.py              Tool read/write classification, code/config cross-check
        ├── limiter.py                Per-caller fixed-window rate/spend budget
        ├── audit.py                  Every call → JSONL + SQLite audit_log
        │
        ▼
  db.py                  Real SQLite CRUD: issues / comments / labels / issue_labels
        │
        ▼
  seed_data.py            15 real, hand-authored issues for the sibling `ragbench` project
```

Every tool call is one pipeline: **authenticate → rate-limit → (if a write) allowlist-check → (if a write) dry-run-or-real → audit-log**. A denial at any stage raises a structured `MCPError` (never a crash, never a silent no-op) and is still written to the audit trail.

### Data model

- `issues(id, title, body, status, team, created_by, assignee, created_at, updated_at)`
- `comments(id, issue_id, author, body, created_at)`
- `labels(id, name)` / `issue_labels(issue_id, label_id)` — many-to-many
- `audit_log(timestamp, session_id, user_id, tool_name, read_or_write, dry_run, allowed, latency_ms, error_code, detail)` — matches the spec's data model exactly
- `schema_meta(key, value)` — pins `schema_version` (see Risks, "target API version" edge case)

### Tools (8 — spec asked for 3-5; write ops are explicitly justified per the spec's non-goals)

| Tool | Read/Write | Cost | Description |
|---|---|---|---|
| `search_issues` | read | 1 | Full-text search over visible issues, filter by `status`/`label` |
| `get_issue` | read | 1 | Full detail: body, labels, every comment |
| `list_labels` | read | 1 | Every label known to the tracker |
| `summarize_issue` | read | 1 | Deterministic extractive summary — **no LLM call** (see below) |
| `get_rate_status` | read | 0 | Caller's remaining call/cost budget this window |
| `create_issue` | write | 5 | Create an issue, scoped to the caller's team |
| `add_comment` | write | 3 | Comment on a visible, open issue |
| `set_issue_status` | write | 3 | Open/close an issue |

**Why `summarize_issue` has no LLM:** this environment has no LLM API keys configured, and the tool's job is to hand *an external* LLM client (Claude Desktop, etc.) real data — it isn't supposed to call one itself. The summary is pure string logic: title + status + labels + a truncated body snippet + comment count + the most recent comment. Deterministic, testable, and honest about what it is.

### Security model, concretely

- **Auth passthrough**: every tool takes a `token` argument. It's resolved to a real `User` (`user_id`, `team`, `is_admin`) via a mock in-memory identity provider — the same DEV-ONLY pattern as `mcp-starter-template`, documented the same way (`identity.py`'s docstring is explicit that a real deployment must replace this with real credential verification). There is no fallback identity: missing/invalid token → `UNAUTHENTICATED`, always.
- **Team-scoped visibility**: an issue with `team=NULL` is public; otherwise it's visible only to same-team callers or an admin. `token-alice` (engineering) and `token-bob` (docs) see different result sets from the identical `search_issues("")` call — this is asserted directly in tests, not just claimed.
- **Read-only by default, two gates deep**: a write tool is refused with `WRITE_NOT_ALLOWED` unless its name is in `allowed_write_tools`. Even then, the global `dry_run` flag (on by default) makes it return a synthetic `{"dry_run": true, "would_create": {...}}` preview instead of touching the database. Both gates have to be explicitly opened for a real mutation to happen.
- **Rate limiting**: fixed-window, per-caller-token budget (`calls_per_min` and `cost_per_session`, tool cost from the registry). Exhausting it mid-session returns `RATE_LIMIT_EXCEEDED` with a `retry_after` on every subsequent call in that window — the process itself never crashes, and other callers are unaffected (tested explicitly, per the spec's edge case).
- **Audit log**: every call — allowed or denied, real or dry-run — becomes one row in `audit_log` (JSONL + SQLite).

## Install

```bash
git clone https://github.com/HamzaOuadid/mcp-issue-tracker.git
cd mcp-issue-tracker
pip install -e .
```

Requires Python 3.10+. Dependencies: `mcp` (official Python MCP SDK), `pydantic`, `PyYAML` — all installed by the command above.

## Usage

### Run it directly

```bash
mcp-issue-tracker
```

This starts the server on stdio (the standard MCP transport). It's not meant to be run interactively from a terminal — it's meant to be launched by an MCP client. To try it by hand, use the bundled demo script instead (see below).

### Register with Claude Desktop

Add to `claude_desktop_config.json` (Windows: `%APPDATA%\Claude\claude_desktop_config.json`; macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "issue-tracker": {
      "command": "mcp-issue-tracker",
      "args": [],
      "env": {
        "MCP_ISSUE_TRACKER_DB": "C:/Users/you/.mcp-issue-tracker/issue_tracker.db",
        "MCP_ISSUE_TRACKER_CONFIG": "C:/path/to/mcp-issue-tracker/server.yaml"
      }
    }
  }
}
```

(If `mcp-issue-tracker` isn't on PATH, point `command` at the interpreter instead: `"command": "python", "args": ["-m", "mcp_issue_tracker.server"]` with `"cwd"` set to the repo root, or use the full path to the venv's `mcp-issue-tracker.exe`.)

Restart Claude Desktop. Ask it something like *"Search the issue tracker for ragbench bugs, using token-alice"* — Claude will call `search_issues` for you. Every tool needs a `token` argument (see **Mock users**, below); a real deployment would replace this with actual per-user OAuth, same as `mcp-starter-template`'s documented upgrade path.

### Environment variable overrides

| Variable | Purpose | Default |
|---|---|---|
| `MCP_ISSUE_TRACKER_DB` | SQLite DB path | `~/.mcp-issue-tracker/issue_tracker.db` |
| `MCP_ISSUE_TRACKER_CONFIG` | Path to `server.yaml` | repo root's `server.yaml` |
| `MCP_ISSUE_TRACKER_AUDIT_JSONL` | JSONL audit log path | disabled if unset |
| `MCP_ISSUE_TRACKER_AUDIT_DB` | SQLite audit log path | in-memory if unset |
| `MCP_ISSUE_TRACKER_DRY_RUN` | Override `dry_run` (`true`/`false`) | from `server.yaml` (`true`) |
| `MCP_ISSUE_TRACKER_ALLOWED_WRITES` | Comma-separated tool names to allowlist | from `server.yaml` (empty) |

### Mock users

| Token | User | Team | Admin |
|---|---|---|---|
| `token-alice` | Alice Nguyen | engineering | no |
| `token-bob` | Bob Reyes | docs | no |
| `token-admin` | Priya Shah | engineering | **yes** (sees every team) |

### Enabling writes for a real run

By default every write tool is refused (`WRITE_NOT_ALLOWED`). To actually create issues/comments/status changes:

```bash
export MCP_ISSUE_TRACKER_ALLOWED_WRITES="create_issue,add_comment,set_issue_status"
export MCP_ISSUE_TRACKER_DRY_RUN=false
mcp-issue-tracker
```

(PowerShell: `$env:MCP_ISSUE_TRACKER_ALLOWED_WRITES = "create_issue,add_comment,set_issue_status"`, `$env:MCP_ISSUE_TRACKER_DRY_RUN = "false"`.)

## Demo run (real output)

Generated by [`scripts/demo.py`](scripts/demo.py), which spawns the actual server via `python -m mcp_issue_tracker.server` and drives it with the real `mcp` SDK client over stdio (`mcp.client.stdio` + `ClientSession`) — this is genuinely what the protocol returns, not hand-typed:

```
$ list_tools()
  - search_issues: Search issues visible to the caller (team-scoped + public issues).
  - get_issue: Fetch one issue's full detail: body, labels, and every comment.
  - list_labels: List every label known to the tracker.
  - summarize_issue: Deterministic extractive summary of one issue (no LLM call).
  - get_rate_status: Report the caller's remaining call/cost budget for the current rate-limit window.
  - create_issue: Create a new issue, scoped to the caller's team. Write, allowlist-gated, dry-run by default.
  - add_comment: Add a comment to an existing, visible, open issue. Write, allowlist-gated, dry-run by default.
  - set_issue_status: Open or close an issue. Write, allowlist-gated, dry-run by default.

$ search_issues(token="token-alice", query="ragbench eval")
  {
    "count": 3,
    "results": [
      {
        "id": 7,
        "title": "gate.py exits 0 even when --baseline file is missing",
        "status": "open",
        "team": "engineering",
        "labels": ["bug", "ci"]
      },
      {
        "id": 2,
        "title": "Support --k as a single int, not just a comma list",
        "status": "open",
        "team": null,
        "labels": ["cli", "enhancement"]
      },
      {
        "id": 1,
        "title": "eval crashes on queries.jsonl with a duplicate query_id",
        "status": "open",
        "team": "engineering",
        "labels": ["bug", "eval"]
      }
    ]
  }

$ search_issues(token="token-bob", label="docs")   # bob is on the docs team
  {
    "count": 3,
    "results": [
      { "id": 15, "title": "CLI help text for `ragbench eval --rerank` doesn't mention offline fallback", "team": "docs" },
      { "id": 8,  "title": "Add a copy-paste example for `report --format html` to the README", "team": "docs" },
      { "id": 4,  "title": "README missing a pointer to the pgvector migration path", "team": "docs" }
    ]
  }

$ get_issue(token="token-admin", issue_id=1)
  {
    "id": 1,
    "title": "eval crashes on queries.jsonl with a duplicate query_id",
    "status": "open",
    "team": "engineering",
    "labels": ["bug", "eval"],
    "comments": [
      { "id": 1, "author": "root-admin",
        "body": "Confirmed on a 40-query file with one accidental duplicate id. Repro attached in the linked gist." }
    ]
  }

$ summarize_issue(token="token-admin", issue_id=1)
  #1 "eval crashes on queries.jsonl with a duplicate query_id" (open) [bug, eval]: Running `ragbench eval
  ./index --queries queries.jsonl` raises an unhandled KeyError deep in metrics.py when two lines in the
  query file share the same query_id... | 1 comment(s); most recent from root-admin: "Confirmed on a
  40-query file with one accidental duplicate id. Repro attached in the linked gist."

$ list_labels(token="token-alice")
  ["bug", "ci", "cli", "docs", "dx", "enhancement", "eval", "good-first-issue",
   "hybrid", "ingest", "ops", "performance", "question", "rerank", "windows"]

$ get_rate_status(token="token-alice")
  { "calls_remaining": 27, "cost_remaining": 98, "reset_at_seconds": 59.938 }

$ create_issue(...)   # default config: write tools are NOT allowlisted
  ERROR: [WRITE_NOT_ALLOWED] Write tool 'create_issue' is not enabled. Add it to
  allowed_write_tools in server.yaml (or MCP_ISSUE_TRACKER_ALLOWED_WRITES) to allow it.

$ get_issue(token="token-bob", issue_id=1)   # issue 1 is engineering-scoped, bob is docs
  ERROR: [NOT_FOUND] Issue 1 was not found or is not visible to you.

$ search_issues(token="not-a-real-token")   # missing/invalid token
  ERROR: [UNAUTHENTICATED] Missing or invalid identity token; call rejected.
```

Reproduce it yourself:

```bash
python scripts/demo.py
```

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

**88 tests, all passing.** Coverage:

- `test_identity_auth.py` — mock IdP resolution, auth-passthrough rejection of missing/invalid tokens, no fallback identity
- `test_registry.py` — read-only-by-default, allowlist gating, code/config classification mismatch fails fast at startup
- `test_limiter.py` — fixed-window budget, per-session isolation, window reset, `retry_after`
- `test_audit.py` — JSONL + SQLite dual-sink logging, denied calls carry `error_code`
- `test_db.py` — real SQLite CRUD, team-scoped visibility, SQL-injection-shaped input doesn't crash or leak
- `test_tools_issues.py` — deterministic summarization, argument validation
- `test_service_read.py` — the four read tools end-to-end against the real seeded corpus, including "two users see different results from the same query"
- `test_service_write.py` — write-not-allowed by default, dry-run preview vs. real mutation, closed-issue comment blocking, cross-team write denial
- `test_edge_cases.py` — rate-limit exhaustion mid-session degrades gracefully (doesn't crash), schema-version pinning, SQL-injection safety, missing-config fallback
- **`test_server_integration.py`** — end-to-end against the **real MCP protocol**: spawns `python -m mcp_issue_tracker.server` as a subprocess and drives it with the actual `mcp` SDK's stdio client (`ClientSession`), confirming `list_tools()` and `call_tool()` work over genuine JSON-RPC, not a hand-rolled stand-in

```
88 passed, 1 warning in ~15-27s
```

## Environment

- Python 3.10+
- `mcp>=1.2.0` (official Python MCP SDK — `pip install mcp`), `pydantic>=2.0`, `PyYAML>=6.0`
- SQLite (bundled with Python) — no server to stand up, matching the rest of this portfolio's "SQLite instead of Postgres/Docker" convention
- No LLM API keys used or required — `summarize_issue` is pure string logic (see Architecture)

## Risks / Open Questions

- **Deviates from the spec's "live public API" framing.** Section 5/10/11 of the spec describe wrapping a live third-party API (e.g. the real GitHub Issues API) with real rate limits against that API's own quota. This build instead uses a **real local SQLite-backed tracker with genuine CRUD**, per this portfolio initiative's explicit environment note (no LLM keys, prefer local data over live third-party dependencies where the task allows it). Consequences: `api_rate_state` in the spec's data model is implemented as *this server's own* per-caller budget (surfaced via `get_rate_status`) rather than a third-party API's quota; the "document the API version targeted" edge case is implemented as a pinned local `schema_version` instead. Both are noted inline in the code (`limiter.py`, `db.py`) so the substitution isn't silent.
- **Mock identity, not a real IdP.** Explicitly DEV-ONLY, documented in `identity.py`'s docstring — same posture as `mcp-starter-template`. A real deployment needs OAuth/JWT/mTLS in front of `AuthMiddleware`.
- **Single-writer SQLite.** Fine for a demo/portfolio server; a concurrent multi-writer deployment would need a real database (same tradeoff `ragbench`'s README makes explicitly for its own SQLite use).
- **Scope cuts vs. the spec's milestones (section 8):** no separate CLI for querying the audit log (query it directly via `AuditLogger.query()` or `sqlite3 issue_tracker.db`); no tagged release (`git tag`) — left to the repo owner once published; label management has no dedicated `delete_label`/`rename_label` tool (labels are create-on-write only, which is enough to demonstrate the pattern without over-building an admin surface the spec didn't ask for).

## Portfolio note

Both this project and `mcp-starter-template` exist to make the same point twice, on purpose: MCP security philosophy (auth-passthrough, read-only-by-default, audited, rate-limited) is a **repeatable pattern**, not a one-off. Same modules, same test approach, same failure modes handled the same way — applied to a docs/config domain in one repo and a real issue tracker in this one.

## License

MIT — see [LICENSE](LICENSE).
