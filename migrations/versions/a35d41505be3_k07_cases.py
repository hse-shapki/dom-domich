"""K07 case retrieval schema.

Revision ID: a35d41505be3
Revises: da1c7e9a5132
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a35d41505be3"
down_revision = "da1c7e9a5132"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id"), nullable=False
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("entrance", sa.Integer()),
        sa.Column("floor", sa.Integer()),
        sa.Column("object_name", sa.String(100)),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("recurrence_of", postgresql.UUID(as_uuid=True)),
        sa.Column("embedding", postgresql.JSONB()),
        sa.Column("embedding_revision", sa.String(200)),
        sa.UniqueConstraint("id", "house_id"),
        sa.ForeignKeyConstraint(["recurrence_of", "house_id"], ["cases.id", "cases.house_id"]),
    )
    op.create_index("ix_cases_house_status_created", "cases", ["house_id", "status", "created_at"])
    op.create_index(
        "ix_cases_house_location", "cases", ["house_id", "entrance", "floor", "object_name"]
    )
    op.execute(
        "CREATE INDEX ix_cases_fts ON cases "
        "USING gin (to_tsvector('russian', title || ' ' || description))"
    )
    op.execute(
        """DO $k07$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            ALTER TABLE cases ADD COLUMN embedding_vector vector(1024);
            CREATE INDEX ix_cases_vector ON cases
              USING hnsw (embedding_vector vector_cosine_ops);
          END IF;
        END $k07$"""
    )


def downgrade() -> None:
    op.drop_table("cases")
