"""K05 knowledge sources, chunks, rules and Russian FTS.

Revision ID: da1c7e9a5132
Revises: f2a6c18b7401
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "da1c7e9a5132"
down_revision = "f2a6c18b7401"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id")),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("uri", sa.String(1000), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("reviewed", sa.Boolean(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("source_id", "revision"),
    )
    op.create_index("ix_knowledge_sources_scope", "knowledge_sources", ["house_id", "reviewed"])
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.JSONB()),
        sa.Column("embedding_revision", sa.String(200)),
        sa.ForeignKeyConstraint(
            ["source_id", "revision"],
            ["knowledge_sources.source_id", "knowledge_sources.revision"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("source_id", "revision", "ordinal"),
    )
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_fts ON knowledge_chunks "
        "USING gin (to_tsvector('russian', text))"
    )
    # PG16 без pgvector остаётся на FTS; целевой PG17/pgvector получает ANN индекс.
    op.execute(
        """DO $k05$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
            CREATE EXTENSION IF NOT EXISTS vector;
            ALTER TABLE knowledge_chunks ADD COLUMN embedding_vector vector(1024);
            CREATE INDEX ix_knowledge_chunks_vector ON knowledge_chunks
              USING hnsw (embedding_vector vector_cosine_ops);
          END IF;
        END $k05$"""
    )
    op.create_table(
        "rule_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id")),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("responsible_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("deadline_origin", sa.String(100)),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["source_id", "source_revision"],
            ["knowledge_sources.source_id", "knowledge_sources.revision"],
        ),
    )


def downgrade() -> None:
    op.drop_table("rule_versions")
    op.execute("DROP INDEX ix_knowledge_chunks_fts")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_sources_scope", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
