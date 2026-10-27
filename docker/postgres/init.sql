-- Extensions required by the application.
-- Executed automatically on first database creation by PostgreSQL's
-- docker-entrypoint-initdb.d mechanism.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "vector";     -- pgvector HNSW/IVFFlat indexes
