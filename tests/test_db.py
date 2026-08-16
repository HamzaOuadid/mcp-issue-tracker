from __future__ import annotations

from mcp_issue_tracker import db


def make_conn():
    conn = db.get_connection(":memory:")
    db.init_schema(conn)
    return conn


SAMPLE = [
    {
        "title": "First issue",
        "body": "Something about ragbench ingest crashing",
        "status": "open",
        "team": "engineering",
        "created_by": "alice",
        "labels": ["bug", "ingest"],
        "comments": [{"author": "bob", "body": "Can repro too"}],
    },
    {
        "title": "Second issue",
        "body": "Docs page is missing an example",
        "status": "closed",
        "team": "docs",
        "created_by": "bob",
        "labels": ["docs"],
        "comments": [],
    },
    {
        "title": "Public triage item",
        "body": "General question about hybrid retrieval",
        "status": "open",
        "team": None,
        "created_by": "bob",
        "labels": ["question"],
        "comments": [],
    },
]


def test_schema_creates_expected_tables():
    conn = make_conn()
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"issues", "comments", "labels", "issue_labels", "schema_meta"}.issubset(tables)
    version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
    assert version["value"] == db.SCHEMA_VERSION


def test_seed_populates_and_is_idempotent():
    conn = make_conn()
    inserted = db.seed(conn, SAMPLE)
    assert inserted == 3
    assert db.is_empty(conn) is False

    # Calling seed again on a non-empty DB is a no-op by default.
    inserted_again = db.seed(conn, SAMPLE)
    assert inserted_again == 0
    total = conn.execute("SELECT COUNT(*) AS n FROM issues").fetchone()["n"]
    assert total == 3


def test_search_visibility_team_scoping():
    conn = make_conn()
    db.seed(conn, SAMPLE)

    # engineering user sees engineering + public, not docs-only.
    eng_results = db.search_issues(conn, "", team="engineering", is_admin=False)
    titles = {r["title"] for r in eng_results}
    assert "First issue" in titles
    assert "Public triage item" in titles
    assert "Second issue" not in titles

    # docs user sees docs + public, not engineering-only.
    docs_results = db.search_issues(conn, "", team="docs", is_admin=False)
    titles = {r["title"] for r in docs_results}
    assert "Second issue" in titles
    assert "Public triage item" in titles
    assert "First issue" not in titles

    # admin sees everything regardless of team.
    admin_results = db.search_issues(conn, "", team="sales", is_admin=True)
    assert len(admin_results) == 3


def test_search_query_filters_title_and_body():
    conn = make_conn()
    db.seed(conn, SAMPLE)
    results = db.search_issues(conn, "hybrid", team="docs", is_admin=False)
    assert len(results) == 1
    assert results[0]["title"] == "Public triage item"


def test_search_empty_query_returns_all_visible():
    conn = make_conn()
    db.seed(conn, SAMPLE)
    results = db.search_issues(conn, "", team="engineering", is_admin=False)
    assert len(results) == 2


def test_search_status_and_label_filters():
    conn = make_conn()
    db.seed(conn, SAMPLE)
    closed = db.search_issues(conn, "", team="docs", is_admin=False, status="closed")
    assert len(closed) == 1
    assert closed[0]["status"] == "closed"

    labeled = db.search_issues(conn, "", team="engineering", is_admin=False, label="bug")
    assert len(labeled) == 1
    assert labeled[0]["title"] == "First issue"


def test_search_query_with_sql_special_characters_does_not_crash():
    conn = make_conn()
    db.seed(conn, SAMPLE)
    # A naive string-formatted query would break or inject here.
    malicious = "'; DROP TABLE issues; --"
    results = db.search_issues(conn, malicious, team="engineering", is_admin=False)
    assert results == []
    # Table must still exist and be intact.
    remaining = conn.execute("SELECT COUNT(*) AS n FROM issues").fetchone()["n"]
    assert remaining == 3


def test_get_issue_respects_visibility():
    conn = make_conn()
    db.seed(conn, SAMPLE)
    eng_only_id = conn.execute("SELECT id FROM issues WHERE title = 'First issue'").fetchone()["id"]

    assert db.get_issue(conn, eng_only_id, team="engineering", is_admin=False) is not None
    assert db.get_issue(conn, eng_only_id, team="docs", is_admin=False) is None
    assert db.get_issue(conn, eng_only_id, team="docs", is_admin=True) is not None


def test_get_issue_includes_comments_and_labels():
    conn = make_conn()
    db.seed(conn, SAMPLE)
    eng_only_id = conn.execute("SELECT id FROM issues WHERE title = 'First issue'").fetchone()["id"]
    issue = db.get_issue(conn, eng_only_id, team="engineering", is_admin=False)
    assert issue["labels"] == ["bug", "ingest"]
    assert len(issue["comments"]) == 1
    assert issue["comments"][0]["author"] == "bob"


def test_get_issue_nonexistent_returns_none():
    conn = make_conn()
    db.seed(conn, SAMPLE)
    assert db.get_issue(conn, 99999, team="engineering", is_admin=True) is None


def test_list_labels_sorted_and_deduped():
    conn = make_conn()
    db.seed(conn, SAMPLE)
    labels = db.list_labels(conn)
    assert labels == sorted(labels)
    assert len(labels) == len(set(labels))


def test_create_issue_and_labels_are_reused_not_duplicated():
    conn = make_conn()
    db.seed(conn, SAMPLE)
    issue = db.create_issue(conn, "New title", "New body", team="engineering", created_by="alice", labels=["bug", "new-label"])
    assert issue["title"] == "New title"
    assert set(issue["labels"]) == {"bug", "new-label"}
    # "bug" label row should be reused, not duplicated.
    bug_rows = conn.execute("SELECT COUNT(*) AS n FROM labels WHERE name = 'bug'").fetchone()["n"]
    assert bug_rows == 1


def test_add_comment_updates_issue_updated_at():
    conn = make_conn()
    db.seed(conn, SAMPLE)
    issue_id = conn.execute("SELECT id FROM issues WHERE title = 'First issue'").fetchone()["id"]
    before = conn.execute("SELECT updated_at FROM issues WHERE id = ?", (issue_id,)).fetchone()["updated_at"]
    comment = db.add_comment(conn, issue_id, "carol", "Adding more detail")
    after = conn.execute("SELECT updated_at FROM issues WHERE id = ?", (issue_id,)).fetchone()["updated_at"]
    assert comment["author"] == "carol"
    assert after >= before


def test_set_issue_status_transitions():
    conn = make_conn()
    db.seed(conn, SAMPLE)
    issue_id = conn.execute("SELECT id FROM issues WHERE title = 'First issue'").fetchone()["id"]
    updated = db.set_issue_status(conn, issue_id, "closed")
    assert updated["status"] == "closed"
    reopened = db.set_issue_status(conn, issue_id, "open")
    assert reopened["status"] == "open"
