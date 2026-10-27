"""remove password hash

Revision ID: 3a233bd1a8c1
Revises: 2ed4dbd5ebc0
Create Date: 2026-08-29 02:57:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3a233bd1a8c1'
down_revision: Union[str, None] = '2ed4dbd5ebc0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # drop password_hash from users
    op.drop_column('users', 'password_hash')


def downgrade() -> None:
    # add it back
    op.add_column('users', sa.Column('password_hash', sa.String(length=255), nullable=True))
