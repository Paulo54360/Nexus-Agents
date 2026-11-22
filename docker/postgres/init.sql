-- Create a dedicated database for self-hosted Langfuse
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec

-- Enable pgvector extension for semantic memory / RAG on the main Nexus DB
CREATE EXTENSION IF NOT EXISTS vector;
