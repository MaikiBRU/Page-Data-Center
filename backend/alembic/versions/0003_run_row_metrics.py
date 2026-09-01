"""Record row-level quality facts on each run.

``dataset_runs`` already stored ``issue_rows``, but that column is the sum of
per-finding counts: a row breaking three rules contributes three, so the value
can exceed ``total_rows`` and cannot be used as a denominator. The two new
columns store distinct row counts instead, which is what the quality and risk
scores are now built on and what the dashboard needs to compare one run against
the previous one.

Existing rows keep NULL. Callers must treat NULL as "not measured on this run"
and skip it rather than reading it as zero, because a pre-migration run has no
recoverable row-level figure.

Revision ID: 0003_run_row_metrics
Revises: 0002_demo_sandbox
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_run_row_metrics"
down_revision = "0002_demo_sandbox"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    existing = _columns("dataset_runs")
    if not existing:
        return
    if "rows_affected" not in existing:
        op.add_column("dataset_runs", sa.Column("rows_affected", sa.Integer(), nullable=True))
    if "critical_rows" not in existing:
        op.add_column("dataset_runs", sa.Column("critical_rows", sa.Integer(), nullable=True))


def downgrade() -> None:
    existing = _columns("dataset_runs")
    if "critical_rows" in existing:
        op.drop_column("dataset_runs", "critical_rows")
    if "rows_affected" in existing:
        op.drop_column("dataset_runs", "rows_affected")
