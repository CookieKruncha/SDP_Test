"""Service layer: ingestion, analysis, queries, authors, jobs.

Modules are populated in later stages of the build plan. The rule that keeps
metrics trustworthy: metric computation and the query layer are pure over the
SQLite cache, and the UI only ever talks to the REST API.
"""
