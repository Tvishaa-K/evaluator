"""deepgram sarvam kb documents

Revision ID: b3f1c2d4e5a6
Revises: 98443895b9f5
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f1c2d4e5a6'
down_revision: Union[str, Sequence[str], None] = '98443895b9f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('calls', sa.Column('detected_language', sa.String(), nullable=True))
    op.add_column('calls', sa.Column('original_transcript', sa.String(), nullable=True))
    op.create_table('kb_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(), nullable=False),
    sa.Column('uploaded_at', sa.String(), nullable=False),
    sa.Column('chunk_count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('kb_documents')
    op.drop_column('calls', 'original_transcript')
    op.drop_column('calls', 'detected_language')
