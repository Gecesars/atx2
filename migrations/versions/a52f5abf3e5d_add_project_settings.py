"""add project settings column

Revision ID: a52f5abf3e5d
Revises: fd0aa8e4b52b
Create Date: 2025-02-14 23:05:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a52f5abf3e5d"
down_revision = "fd0aa8e4b52b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("settings", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("settings")
