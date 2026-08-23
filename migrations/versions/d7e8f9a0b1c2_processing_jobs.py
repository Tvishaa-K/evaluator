"""processing jobs

Revision ID: d7e8f9a0b1c2
Revises: b3f1c2d4e5a6
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'b3f1c2d4e5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('processing_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('error', sa.String(), nullable=True),
    sa.Column('call_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.String(), nullable=False),
    sa.Column('updated_at', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('processing_jobs')
