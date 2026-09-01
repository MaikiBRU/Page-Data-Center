"""Demo sandbox: session table, database-backed demo files, tenant column.

Adds:
  * ``demo_sessions``      - one row per anonymous visitor sandbox
  * ``demo_dataset_files`` - CSV payloads for demo datasets, kept in the
                             database because App Runner's disk is ephemeral
  * ``datasets.demo_session_id`` / ``cases.demo_session_id`` - the partition
                             key. NULL means the authenticated application.

Every step checks the catalogue first so the migration is safe to re-run and
safe to apply to a database where ``create_all`` already produced the tables.
No existing row is modified: all pre-existing datasets and cases keep
``demo_session_id = NULL`` and therefore stay in the application partition.

Revision ID: 0002_demo_sandbox
Revises: 0001_baseline
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_demo_sandbox"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {col["name"] for col in _inspector().get_columns(table)}


def _has_index(table: str, index: str) -> bool:
    if not _has_table(table):
        return False
    return index in {idx["name"] for idx in _inspector().get_indexes(table)}


def upgrade() -> None:
    if not _has_table("demo_sessions"):
        op.create_table(
            "demo_sessions",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("label", sa.String(length=60), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("runs_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("exports_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("storage_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_ip_hash", sa.String(length=64), nullable=True),
        )
    if not _has_index("demo_sessions", "ix_demo_sessions_expires_at"):
        op.create_index("ix_demo_sessions_expires_at", "demo_sessions", ["expires_at"])

    if not _has_table("demo_dataset_files"):
        op.create_table(
            "demo_dataset_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("demo_session_id", sa.String(length=64), nullable=False),
            sa.Column("dataset_id", sa.Integer(), nullable=False, unique=True),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("content", sa.LargeBinary(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not _has_index("demo_dataset_files", "ix_demo_dataset_files_demo_session_id"):
        op.create_index(
            "ix_demo_dataset_files_demo_session_id", "demo_dataset_files", ["demo_session_id"]
        )

    if not _has_column("datasets", "demo_session_id"):
        op.add_column("datasets", sa.Column("demo_session_id", sa.String(length=64), nullable=True))
    if not _has_index("datasets", "ix_datasets_demo_session_id"):
        op.create_index("ix_datasets_demo_session_id", "datasets", ["demo_session_id"])

    if not _has_column("cases", "demo_session_id"):
        op.add_column("cases", sa.Column("demo_session_id", sa.String(length=64), nullable=True))
    if not _has_index("cases", "ix_cases_demo_session_id"):
        op.create_index("ix_cases_demo_session_id", "cases", ["demo_session_id"])


def downgrade() -> None:
    # Drops sandbox data only; application rows have demo_session_id = NULL and
    # are untouched.
    if _has_index("cases", "ix_cases_demo_session_id"):
        op.drop_index("ix_cases_demo_session_id", table_name="cases")
    if _has_column("cases", "demo_session_id"):
        op.drop_column("cases", "demo_session_id")

    if _has_index("datasets", "ix_datasets_demo_session_id"):
        op.drop_index("ix_datasets_demo_session_id", table_name="datasets")
    if _has_column("datasets", "demo_session_id"):
        op.drop_column("datasets", "demo_session_id")

    if _has_table("demo_dataset_files"):
        op.drop_table("demo_dataset_files")
    if _has_table("demo_sessions"):
        op.drop_table("demo_sessions")
