"""Service layer: ingestion, analysis, queries, authors, jobs.

Present (Stage 2): ``gitcmd`` (the single git CLI wrapper), ``jobs``
(background runner + progress), ``registry`` (repos table), ``ingest``
(zip/URL ingestion). The analyzer and query layer arrive in Stages 3-4.

The rule that keeps metrics trustworthy: metric computation and the query
layer are pure over the SQLite cache, and the UI only ever talks to the
REST API.
"""
