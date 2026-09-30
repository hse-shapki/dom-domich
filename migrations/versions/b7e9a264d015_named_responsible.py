"""Сохраняет понятное название ответственной службы в проверенном правиле.

Revision ID: b7e9a264d015
Revises: 0a7b6c5d4e3f
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e9a264d015"
down_revision = "0a7b6c5d4e3f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rule_versions", sa.Column("responsible_name", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("rule_versions", "responsible_name")
