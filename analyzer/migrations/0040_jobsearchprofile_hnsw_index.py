"""
Add an HNSW index on JobSearchProfile.embedding.

The original pgvector migration (0014) created an HNSW index on
analyzer_discoveredjob but not on analyzer_jobsearchprofile, so resume-side
similarity queries ran without an ANN index. This adds it.

Postgres-only and fully guarded: it no-ops on non-postgres backends (e.g. the
SQLite test database) and if the pgvector `vector` type / embedding column
isn't present.
"""
import logging

from django.db import migrations

logger = logging.getLogger('analyzer')


def add_jsp_hnsw_index(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_type WHERE typname = 'vector' LIMIT 1;")
        if not cursor.fetchone():
            logger.warning('vector type not found — skipping jobsearchprofile HNSW index')
            return
        # Only create the index if the embedding column actually exists.
        cursor.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'analyzer_jobsearchprofile' AND column_name = 'embedding'
            LIMIT 1;
        """)
        if not cursor.fetchone():
            logger.warning('embedding column missing — skipping jobsearchprofile HNSW index')
            return
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS jobsearchprofile_embedding_hnsw_idx
            ON analyzer_jobsearchprofile
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """)
        logger.info('jobsearchprofile HNSW index ensured')


def drop_jsp_hnsw_index(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS jobsearchprofile_embedding_hnsw_idx;")


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0039_add_tailor_resume_fields'),
    ]

    operations = [
        migrations.RunPython(add_jsp_hnsw_index, drop_jsp_hnsw_index, elidable=True),
    ]
