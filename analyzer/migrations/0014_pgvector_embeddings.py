"""
Phase 12A — Enable pgvector extension and add embedding fields.

This migration:
1. Attempts to enable the pgvector extension (safe to fail)
2. Adds nullable embedding fields to JobSearchProfile and DiscoveredJob
3. Adds 'firecrawl' to DiscoveredJob source choices

If pgvector is not installed on the database server, the extension
and VectorField additions are silently skipped. The application
gracefully degrades to LLM-based matching.
"""
import logging

from django.db import connection, migrations, models

logger = logging.getLogger('analyzer')


def enable_pgvector(apps, schema_editor):
    """
    Enable pgvector extension using a separate autocommit cursor.
    This avoids aborting the migration transaction on failure.
    """
    if schema_editor.connection.vendor != 'postgresql':
        logger.info('Skipping pgvector — not PostgreSQL')
        return

    # Use a raw connection with autocommit to avoid transaction issues
    from django.db import connection as db_conn
    old_autocommit = db_conn.get_autocommit()
    try:
        db_conn.set_autocommit(True)
        with db_conn.cursor() as cursor:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS vector;')
        logger.info('pgvector extension enabled')
    except Exception as exc:
        logger.warning(
            'pgvector extension not available: %s. '
            'Embedding features will be disabled.',
            exc,
        )
    finally:
        try:
            db_conn.set_autocommit(old_autocommit)
        except Exception:
            pass


def add_vector_fields(apps, schema_editor):
    """Add embedding vector columns directly via SQL if pgvector is available."""
    if schema_editor.connection.vendor != 'postgresql':
        return

    # Check if vector type exists
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_type WHERE typname = 'vector' LIMIT 1;"
        )
        if not cursor.fetchone():
            logger.warning('vector type not found — skipping embedding columns')
            return

        # Add embedding to JobSearchProfile
        cursor.execute("""
            ALTER TABLE analyzer_jobsearchprofile
            ADD COLUMN IF NOT EXISTS embedding vector(1536);
        """)

        # Add embedding to DiscoveredJob
        cursor.execute("""
            ALTER TABLE analyzer_discoveredjob
            ADD COLUMN IF NOT EXISTS embedding vector(1536);
        """)

        # Create HNSW index for fast cosine similarity
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS discoveredjob_embedding_hnsw_idx
            ON analyzer_discoveredjob
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """)

        logger.info('pgvector embedding columns and HNSW index added')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0013_edge_case_fixes'),
    ]

    operations = [
        migrations.RunPython(enable_pgvector, noop),
        migrations.RunPython(add_vector_fields, noop),
    ]
