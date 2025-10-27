"""add tx location metadata

Revision ID: cc3d3ad4f9a1
Revises: e3a33b72b1cf
Create Date: 2025-10-27 15:40:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cc3d3ad4f9a1'
down_revision = 'e3a33b72b1cf'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tx_location_name', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('tx_site_elevation', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('climate_lat', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('climate_lon', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('climate_updated_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('climate_updated_at')
        batch_op.drop_column('climate_lon')
        batch_op.drop_column('climate_lat')
        batch_op.drop_column('tx_site_elevation')
        batch_op.drop_column('tx_location_name')
