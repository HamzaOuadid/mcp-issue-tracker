"""Domain-level tool logic (pure functions over already-fetched data).

Kept separate from ``service.py`` (which wires auth/rate-limit/audit/db)
so summarization and validation can be unit-tested with plain dicts, no
database or security plumbing required.
"""
