"""add propagation param columns

Revision ID: e3a33b72b1cf
Revises: caf3c010faf5
Create Date: 2025-10-27 14:45:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3a33b72b1cf'
down_revision = '4f65fed2f5a5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('time_percentage', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('polarization', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('temperature_k', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('pressure_hpa', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('water_density', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('p452_version', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('p452_version')
        batch_op.drop_column('water_density')
        batch_op.drop_column('pressure_hpa')
        batch_op.drop_column('temperature_k')
        batch_op.drop_column('polarization')
        batch_op.drop_column('time_percentage')
