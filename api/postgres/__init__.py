"""PostgreSQL schema foundation.

Authentication (Phase 3B1) and the market cache (Phase 3B2) read and write
PostgreSQL. These modules declare the approved schema and expose a lazily
created engine/session; every other feature still runs on MongoDB.
"""
