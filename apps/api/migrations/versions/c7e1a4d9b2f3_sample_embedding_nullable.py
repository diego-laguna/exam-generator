"""sample question embeddings are filled in by the worker

Revision ID: c7e1a4d9b2f3
Revises: bc531fec827d
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c7e1a4d9b2f3"
down_revision: Union[str, Sequence[str], None] = "bc531fec827d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("sample_questions", "embedding", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM sample_questions WHERE embedding IS NULL")
    op.alter_column("sample_questions", "embedding", nullable=False)
