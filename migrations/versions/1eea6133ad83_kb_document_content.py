"""kb document content

Revision ID: 1eea6133ad83
Revises: e1f2a3b4c5d6
Create Date: 2026-08-24 11:23:47.446861

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1eea6133ad83'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("kb_documents", sa.Column("content", sa.String(), nullable=True))




def downgrade() -> None:
    op.drop_column("kb_documents", "content")
