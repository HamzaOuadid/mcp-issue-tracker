"""SQLite-backed issue tracker data layer.

Real CRUD against a real local database -- no mocked data layer. Schema
covers issues, comments, and a labels/issue_labels many-to-many, plus
the ``audit_log`` table (written by ``audit.py``). All queries are
parameterized; nothing here ever string-formats caller input into SQL.

``SCHEMA_VERSION`` is this project's analog of the spec's "document the
API version targeted" edge case: there's no third-party API to version
against (this is a local database, not a live public API -- see
README's Risks section for why), so the schema itself is the versioned
contract instead.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "1.0.0"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    team TEXT,
    created_by TEXT NOT NULL,
    assignee TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL REFERENCES issues(id),
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS issue_labels (
    issue_id INTEGER NOT NULL REFERENCES issues(id),
    label_id INTEGER NOT NULL REFERENCES labels(id),
    PRIMARY KEY (issue_id, label_id)
);

CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status);
CREATE INDEX IF NOT EXISTS idx_issues_team ON issues(team);
CREATE INDEX IF NOT EXISTS idx_comments_issue ON comments(issue_id);
"""


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def is_empty(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) AS n FROM issues").fetchone()
    return row["n"] == 0


def _get_or_create_label(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip().lower()
    row = conn.execute("SELECT id FROM labels WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO labels (name) VALUES (?)", (name,))
    return cur.lastrowid


def seed(conn: sqlite3.Connection, issues: list[dict], force: bool = False) -> int:
    """Populate the database from ``issues`` (see ``seed_data.py``).

    No-ops if the database already has issues, unless ``force=True``.
    Returns the number of issues inserted.
    """
    if not force and not is_empty(conn):
        return 0

    count = 0
    for item in issues:
        now = item.get("created_at", time.time())
        cur = conn.execute(
            "INSERT INTO issues (title, body, status, team, created_by, assignee, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item["title"],
                item["body"],
                item.get("status", "open"),
                item.get("team"),
                item["created_by"],
                item.get("assignee"),
                now,
                item.get("updated_at", now),
            ),
        )
        issue_id = cur.lastrowid
        count += 1

        for label_name in item.get("labels", []):
            label_id = _get_or_create_label(conn, label_name)
            conn.execute(
                "INSERT OR IGNORE INTO issue_labels (issue_id, label_id) VALUES (?, ?)",
                (issue_id, label_id),
            )

        for comment in item.get("comments", []):
            conn.execute(
                "INSERT INTO comments (issue_id, author, body, created_at) VALUES (?, ?, ?, ?)",
                (issue_id, comment["author"], comment["body"], comment.get("created_at", now)),
            )

    conn.commit()
    return count


def _labels_for(conn: sqlite3.Connection, issue_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT l.name FROM labels l "
        "JOIN issue_labels il ON il.label_id = l.id "
        "WHERE il.issue_id = ? ORDER BY l.name",
        (issue_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def _comments_for(conn: sqlite3.Connection, issue_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, author, body, created_at FROM comments WHERE issue_id = ? ORDER BY created_at",
        (issue_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _visibility_clause() -> str:
    # team IS NULL -> public issue, visible to everyone.
    # team = :team -> same-team issue.
    # :is_admin -> admins bypass team scoping entirely.
    return "(team IS NULL OR team = :team OR :is_admin = 1)"


def row_to_issue(conn: sqlite3.Connection, row: sqlite3.Row, include_comments: bool = False) -> dict:
    issue = dict(row)
    issue["labels"] = _labels_for(conn, row["id"])
    if include_comments:
        issue["comments"] = _comments_for(conn, row["id"])
    return issue


def search_issues(
    conn: sqlite3.Connection,
    query: str,
    team: str,
    is_admin: bool,
    status: Optional[str] = None,
    label: Optional[str] = None,
    limit: int = 25,
) -> list[dict]:
    query_norm = (query or "").strip().lower()
    sql = (
        "SELECT DISTINCT i.* FROM issues i "
        "LEFT JOIN issue_labels il ON il.issue_id = i.id "
        "LEFT JOIN labels l ON l.id = il.label_id "
        f"WHERE {_visibility_clause()} "
    )
    params: dict = {"team": team, "is_admin": int(is_admin)}

    if query_norm:
        sql += "AND (LOWER(i.title) LIKE :q OR LOWER(i.body) LIKE :q) "
        params["q"] = f"%{query_norm}%"
    if status:
        sql += "AND i.status = :status "
        params["status"] = status
    if label:
        sql += "AND LOWER(l.name) = :label "
        params["label"] = label.strip().lower()

    sql += "ORDER BY i.created_at DESC LIMIT :limit"
    params["limit"] = limit

    rows = conn.execute(sql, params).fetchall()
    return [row_to_issue(conn, r) for r in rows]


def get_issue(conn: sqlite3.Connection, issue_id: int, team: str, is_admin: bool) -> Optional[dict]:
    sql = f"SELECT * FROM issues WHERE id = :id AND {_visibility_clause()}"
    row = conn.execute(sql, {"id": issue_id, "team": team, "is_admin": int(is_admin)}).fetchone()
    if row is None:
        return None
    return row_to_issue(conn, row, include_comments=True)


def list_labels(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM labels ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def create_issue(
    conn: sqlite3.Connection,
    title: str,
    body: str,
    team: Optional[str],
    created_by: str,
    labels: Optional[list[str]] = None,
) -> dict:
    now = time.time()
    cur = conn.execute(
        "INSERT INTO issues (title, body, status, team, created_by, assignee, created_at, updated_at) "
        "VALUES (?, ?, 'open', ?, ?, NULL, ?, ?)",
        (title, body, team, created_by, now, now),
    )
    issue_id = cur.lastrowid
    for label_name in labels or []:
        label_id = _get_or_create_label(conn, label_name)
        conn.execute(
            "INSERT OR IGNORE INTO issue_labels (issue_id, label_id) VALUES (?, ?)",
            (issue_id, label_id),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    return row_to_issue(conn, row, include_comments=True)


def add_comment(conn: sqlite3.Connection, issue_id: int, author: str, body: str) -> dict:
    now = time.time()
    conn.execute(
        "INSERT INTO comments (issue_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        (issue_id, author, body, now),
    )
    conn.execute("UPDATE issues SET updated_at = ? WHERE id = ?", (now, issue_id))
    conn.commit()
    row = conn.execute(
        "SELECT id, author, body, created_at FROM comments WHERE issue_id = ? ORDER BY id DESC LIMIT 1",
        (issue_id,),
    ).fetchone()
    return dict(row)


def set_issue_status(conn: sqlite3.Connection, issue_id: int, status: str) -> dict:
    now = time.time()
    conn.execute("UPDATE issues SET status = ?, updated_at = ? WHERE id = ?", (status, now, issue_id))
    conn.commit()
    row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    return row_to_issue(conn, row, include_comments=True)


def issue_exists_raw(conn: sqlite3.Connection, issue_id: int) -> Optional[sqlite3.Row]:
    """Fetch an issue by id with NO visibility filtering (internal use only)."""
    return conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
