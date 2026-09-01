"""Baseline for the pre-Alembic schema.

Deliberately a no-op. The existing production database was built by
``Base.metadata.create_all`` plus the ad-hoc ALTER statements in
``app/main.py``, so there is no single earlier revision to replay. Making the
first revision empty means ``alembic upgrade head`` behaves correctly against
both a database that already has the legacy schema and a fresh one created by
``create_all`` at startup, without stamping anything by hand.

Everything from here on is a real, reviewable migration.

Revision ID: 0001_baseline
Revises:
"""

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
