"""Real seed corpus: an issue tracker for `ragbench`.

`ragbench` (a sibling project in the same portfolio -- see
../ragbench/README.md) is a real, already-built CLI that benchmarks
dense/sparse/hybrid/reranked retrieval. These 15 issues are written
against its actual documented behavior (CLI flags, module names, the
Pride & Prejudice benchmark fixture, etc.) so the corpus is genuinely
plausible engineering content rather than lorem-ipsum filler -- while
still being a hand-authored demo corpus for THIS server, not a scrape
of a real live tracker. Teams: "engineering" and "docs"; `team=None`
means visible to everyone (public triage queue).
"""

from __future__ import annotations

import time

_DAY = 86400.0
_NOW = time.time()


def _days_ago(n: float) -> float:
    return _NOW - n * _DAY


ISSUES: list[dict] = [
    {
        "title": "eval crashes on queries.jsonl with a duplicate query_id",
        "body": (
            "Running `ragbench eval ./index --queries queries.jsonl` raises an "
            "unhandled KeyError deep in metrics.py when two lines in the query "
            "file share the same query_id. Expected: either the loader rejects "
            "the file up front with a clear message, or duplicate ids are "
            "namespaced instead of silently overwriting each other's rows."
        ),
        "status": "open",
        "team": "engineering",
        "created_by": "alice",
        "assignee": "alice",
        "labels": ["bug", "eval"],
        "created_at": _days_ago(21),
        "comments": [
            {"author": "root-admin", "body": "Confirmed on a 40-query file with one accidental duplicate id. Repro attached in the linked gist.", "created_at": _days_ago(20)},
        ],
    },
    {
        "title": "Support --k as a single int, not just a comma list",
        "body": (
            "`ragbench eval ./index --queries queries.jsonl --k 5,10` works, but "
            "`--k 5` (a single value) currently fails argument parsing because "
            "the flag assumes a comma-separated string. Should accept both."
        ),
        "status": "open",
        "team": None,
        "created_by": "bob",
        "assignee": None,
        "labels": ["enhancement", "cli"],
        "created_at": _days_ago(18),
        "comments": [],
    },
    {
        "title": "Corrupt PDF ingestion warning is printed twice",
        "body": (
            "loaders.py already logs 'skipping corrupt PDF: <path>' once, but "
            "ingest.py's batching wrapper also logs a generic warning for the "
            "same failed file, so the console shows the same skip twice per "
            "corrupt file. Should be a single, clear warning."
        ),
        "status": "closed",
        "team": "engineering",
        "created_by": "alice",
        "assignee": "root-admin",
        "labels": ["bug", "ingest"],
        "created_at": _days_ago(40),
        "updated_at": _days_ago(33),
        "comments": [
            {"author": "root-admin", "body": "Fixed by moving the log call out of the retry loop in ingest.py. Verified with a fixture corpus that has 2 corrupt PDFs mixed in.", "created_at": _days_ago(33)},
        ],
    },
    {
        "title": "README missing a pointer to the pgvector migration path",
        "body": (
            "The Environment section mentions 'A pgvector backend is a natural "
            "v2... if you need concurrent multi-process writes' but there's no "
            "linked issue or design doc to follow up on. Add a stub doc or at "
            "least a tracking issue link so it's discoverable."
        ),
        "status": "open",
        "team": "docs",
        "created_by": "bob",
        "assignee": None,
        "labels": ["docs", "good-first-issue"],
        "created_at": _days_ago(10),
        "comments": [],
    },
    {
        "title": "Add --rerank-top-n to control the cross-encoder candidate pool size",
        "body": (
            "rerank.py always rescoring the hybrid retriever's fixed top-N "
            "candidates works, but N is hardcoded. On larger corpora this makes "
            "the hybrid+rerank row's p95 latency (currently 124ms on the "
            "808-chunk P&P fixture) grow faster than necessary for benchmarks "
            "that only care about recall@5. Expose it as a flag."
        ),
        "status": "open",
        "team": "engineering",
        "created_by": "root-admin",
        "assignee": None,
        "labels": ["enhancement", "rerank"],
        "created_at": _days_ago(15),
        "comments": [
            {"author": "alice", "body": "+1, I want to sweep top_n in {20, 50, 100} for a corpus report and right now that means editing source.", "created_at": _days_ago(14)},
        ],
    },
    {
        "title": "Why does RRF fusion use k=60 by default?",
        "body": (
            "retrieve.py's HybridRetriever hardcodes RRF's k=60. Is this from "
            "the original Cormack et al. paper's recommendation, or tuned "
            "against the P&P fixture specifically? The README's benchmark "
            "section shows RRF actually pulling a correct BM25 hit down for "
            "proper-noun queries -- curious if a lower k would help there."
        ),
        "status": "open",
        "team": None,
        "created_by": "bob",
        "assignee": None,
        "labels": ["question", "hybrid"],
        "created_at": _days_ago(9),
        "comments": [],
    },
    {
        "title": "gate.py exits 0 even when --baseline file is missing",
        "body": (
            "`ragbench eval ./index --queries queries.jsonl --baseline "
            "missing.json --fail-below -2pt` should fail loudly (baseline file "
            "not found is a setup error, not 'no regression'), but it currently "
            "prints a warning to stderr and exits 0. CI would silently pass a "
            "misconfigured gate."
        ),
        "status": "open",
        "team": "engineering",
        "created_by": "root-admin",
        "assignee": "alice",
        "labels": ["bug", "ci"],
        "created_at": _days_ago(6),
        "comments": [
            {"author": "alice", "body": "Picking this up -- should be a one-line fix, raise instead of warn when --baseline path doesn't exist.", "created_at": _days_ago(5)},
        ],
    },
    {
        "title": "Add a copy-paste example for `report --format html` to the README",
        "body": (
            "The Usage section shows `ragbench report result.json --format md` "
            "but never the html variant, even though report.py clearly supports "
            "it (see the ARCHITECTURE bullet). Small doc gap, good first PR."
        ),
        "status": "open",
        "team": "docs",
        "created_by": "bob",
        "assignee": None,
        "labels": ["good-first-issue", "docs"],
        "created_at": _days_ago(4),
        "comments": [],
    },
    {
        "title": "Cache embeddings across ingest re-runs when the file hash is unchanged",
        "body": (
            "Re-running `ragbench ingest ./docs --out ./index` after editing one "
            "file in a 500-doc corpus currently re-embeds everything. Hashing "
            "each file and skipping embed calls for unchanged content would make "
            "iterative corpus editing much faster, especially with the default "
            "sentence-transformers model on CPU."
        ),
        "status": "closed",
        "team": "engineering",
        "created_by": "alice",
        "assignee": "alice",
        "labels": ["enhancement", "ingest", "performance"],
        "created_at": _days_ago(60),
        "updated_at": _days_ago(50),
        "comments": [
            {"author": "root-admin", "body": "Landed via content-hash column on `documents`. Re-ingest of the P&P fixture with 1 changed chapter went from ~9s to ~0.4s.", "created_at": _days_ago(50)},
        ],
    },
    {
        "title": "n_excluded count looks off by one for empty relevant_chunk_ids",
        "body": (
            "The README says a query with empty relevant_chunk_ids is excluded "
            "from recall/MRR and counted in n_excluded. On a queries.jsonl with "
            "exactly one such query, the printed n_excluded is 0, not 1 -- "
            "possibly a filter running after the count is taken instead of "
            "before in eval.py."
        ),
        "status": "open",
        "team": "engineering",
        "created_by": "bob",
        "assignee": None,
        "labels": ["bug", "eval"],
        "created_at": _days_ago(3),
        "comments": [],
    },
    {
        "title": "Validate --model against a known-good sentence-transformers name",
        "body": (
            "`ragbench ingest ./docs --out ./index --model nonexistent-model` "
            "fails with a raw HuggingFace stack trace instead of a clear "
            "'unknown model' error naming the flag that caused it."
        ),
        "status": "open",
        "team": None,
        "created_by": "root-admin",
        "assignee": None,
        "labels": ["enhancement", "dx"],
        "created_at": _days_ago(12),
        "comments": [],
    },
    {
        "title": "Does ingest support .docx files?",
        "body": (
            "README lists pdf/md/txt for loaders.py. Is .docx on the roadmap, "
            "or should we convert to markdown ourselves before ingest? Asking "
            "because our internal docs are mostly .docx."
        ),
        "status": "closed",
        "team": "docs",
        "created_by": "bob",
        "assignee": None,
        "labels": ["question"],
        "created_at": _days_ago(25),
        "updated_at": _days_ago(24),
        "comments": [
            {"author": "alice", "body": "Not yet -- loaders.py is pluggable via register_loader() though, a .docx loader using python-docx would be a clean addition without touching core ingest.py.", "created_at": _days_ago(24)},
        ],
    },
    {
        "title": "Chunk id determinism breaks across OS due to path separators",
        "body": (
            "storage.py assigns chunk ids in 'deterministic ingestion order', "
            "but the order is derived from os.walk() results which sort "
            "differently on Windows (backslash paths) vs Linux (forward-slash) "
            "for mixed-depth corpora. A queries.jsonl authored on Linux against "
            "chunk ids can point at the wrong chunk when re-ingested on Windows."
        ),
        "status": "open",
        "team": "engineering",
        "created_by": "root-admin",
        "assignee": None,
        "labels": ["bug", "ingest", "windows"],
        "created_at": _days_ago(7),
        "comments": [
            {"author": "alice", "body": "Should sort by normalized posix-style relative path before assigning ids, not raw os.walk() order.", "created_at": _days_ago(7)},
        ],
    },
    {
        "title": "Publish a Dockerfile alongside the SQLite-only setup",
        "body": (
            "Given the README explicitly frames pgvector as a v2 for "
            "concurrent multi-process writes, it'd help adopters to have an "
            "optional Dockerfile + docker-compose for that path documented "
            "now, even if SQLite stays the default for single-writer use."
        ),
        "status": "open",
        "team": None,
        "created_by": "bob",
        "assignee": None,
        "labels": ["enhancement", "ops"],
        "created_at": _days_ago(2),
        "comments": [],
    },
    {
        "title": "CLI help text for `ragbench eval --rerank` doesn't mention offline fallback",
        "body": (
            "eval.py's --rerank flag silently falls back to unreranked hybrid "
            "order if the cross-encoder model can't be downloaded (nice "
            "behavior!), but `ragbench eval --help` doesn't say so, so users "
            "on an air-gapped machine won't know why hybrid+rerank looks "
            "identical to hybrid in their output."
        ),
        "status": "open",
        "team": "docs",
        "created_by": "bob",
        "assignee": None,
        "labels": ["docs", "good-first-issue"],
        "created_at": _days_ago(1),
        "comments": [],
    },
]
