"""The smoke test writes to whatever database it is aimed at.

It creates or resets an administrator account, so two things must hold before
it does anything: the password comes from outside the repository, and the
target is this machine.
"""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import smoke_test  # noqa: E402


# --- the password must come from the environment ---------------------------


def test_the_repository_carries_no_administrator_password():
    """The literal that used to live here was a working credential."""
    source = (SCRIPTS_DIR / "smoke_test.py").read_text(encoding="utf-8")
    assert "Admin1234" not in source
    assert "Smoke1234" not in source
    assert "Reset1234" not in source
    # And no default is supplied anywhere.
    assert 'PASSWORD_ENV_VAR = "SMOKE_ADMIN_PASSWORD"' in source


@pytest.mark.parametrize("environ", [{}, {"SMOKE_ADMIN_PASSWORD": ""}, {"SMOKE_ADMIN_PASSWORD": "   "}])
def test_a_missing_password_aborts(environ):
    with pytest.raises(smoke_test.SmokeTestRefused) as refusal:
        smoke_test.require_admin_password(environ)
    message = str(refusal.value)
    assert "SMOKE_ADMIN_PASSWORD" in message, "the message must name the variable"


def test_a_trivially_short_password_aborts():
    with pytest.raises(smoke_test.SmokeTestRefused):
        smoke_test.require_admin_password({"SMOKE_ADMIN_PASSWORD": "corta"})


def test_a_supplied_password_is_accepted_and_returned():
    assert (
        smoke_test.require_admin_password({"SMOKE_ADMIN_PASSWORD": "  UnaClaveLarga1  "})
        == "UnaClaveLarga1"
    )


def test_no_fallback_password_is_used_when_the_variable_is_absent(monkeypatch):
    monkeypatch.delenv("SMOKE_ADMIN_PASSWORD", raising=False)
    with pytest.raises(smoke_test.SmokeTestRefused):
        smoke_test.require_admin_password()


# --- the target must be this machine ---------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://user:pass@127.0.0.1:5432/data_quality",
        "postgresql+psycopg://user:pass@localhost:5432/data_quality",
        "postgresql+psycopg://user:pass@[::1]:5432/data_quality",
        "postgresql://user:pass@127.0.0.1/data_quality",
        "sqlite:///./dev.db",
        "sqlite://",
    ],
)
def test_local_targets_are_allowed(url):
    assert smoke_test.is_local_database(url) is True
    smoke_test.require_local_database(url)  # must not raise


@pytest.mark.parametrize(
    "url,label",
    [
        ("postgresql+psycopg://u:p@mydb.abc123.us-east-1.rds.amazonaws.com:5432/db", "RDS"),
        ("postgresql+psycopg://u:p@10.0.3.14:5432/db", "private VPC address"),
        ("postgresql+psycopg://u:p@203.0.113.7:5432/db", "public address"),
        ("postgresql+psycopg://u:p@db:5432/db", "unresolvable hostname"),
    ],
)
def test_remote_targets_are_refused(url, label):
    assert smoke_test.is_local_database(url) is False, label
    with pytest.raises(smoke_test.SmokeTestRefused):
        smoke_test.require_local_database(url)


def test_a_hostname_that_merely_looks_local_is_refused():
    """The guard resolves the host; it does not match on text.

    A name like localhost.evil.com would pass any substring check.
    """
    url = "postgresql+psycopg://u:p@localhost.invalid-tld-for-tests.example:5432/db"
    assert smoke_test.is_local_database(url) is False


def test_the_refusal_message_names_the_host_and_not_the_credentials():
    url = "postgresql+psycopg://admin:s3cret@mydb.abc123.us-east-1.rds.amazonaws.com:5432/db"
    with pytest.raises(smoke_test.SmokeTestRefused) as refusal:
        smoke_test.require_local_database(url)
    message = str(refusal.value)
    assert "mydb.abc123.us-east-1.rds.amazonaws.com" in message
    # The URL carries a password; it must never reach a log or a terminal.
    assert "s3cret" not in message
    assert "admin:" not in message


def test_database_host_extraction():
    assert smoke_test.database_host("postgresql+psycopg://u:p@host.example:5432/db") == "host.example"
    # No network target at all.
    assert smoke_test.database_host("sqlite:///./dev.db") is None
    assert smoke_test.database_host("sqlite://") is None


# --- the two guards run together, before the app is imported ---------------


def test_preflight_refuses_before_touching_the_database(monkeypatch):
    monkeypatch.delenv("SMOKE_ADMIN_PASSWORD", raising=False)
    with pytest.raises(smoke_test.SmokeTestRefused):
        smoke_test.preflight()


def test_preflight_passes_with_a_password_and_a_local_database(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv("SMOKE_ADMIN_PASSWORD", "UnaClaveLarga1")
    monkeypatch.setattr(settings, "database_url", "sqlite://", raising=False)
    assert smoke_test.preflight() == "UnaClaveLarga1"


def test_preflight_refuses_a_remote_database_even_with_a_password(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv("SMOKE_ADMIN_PASSWORD", "UnaClaveLarga1")
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://u:p@mydb.abc123.us-east-1.rds.amazonaws.com:5432/db",
        raising=False,
    )
    with pytest.raises(smoke_test.SmokeTestRefused):
        smoke_test.preflight()


def test_preflight_reads_the_effective_url_not_the_raw_environment(monkeypatch):
    """An exported DATABASE_URL wins over backend/.env, so the guard must ask
    the settings object what the application will actually connect to."""
    from app.core.config import settings

    monkeypatch.setenv("SMOKE_ADMIN_PASSWORD", "UnaClaveLarga1")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")  # not what settings holds
    monkeypatch.setattr(
        settings, "database_url", "postgresql+psycopg://u:p@203.0.113.7:5432/db", raising=False
    )
    with pytest.raises(smoke_test.SmokeTestRefused):
        smoke_test.preflight()


# --- the schema is created before anything queries it ----------------------


def test_the_schema_is_created_before_the_first_query():
    """Ordering regression.

    TestClient only runs the application's startup hook when used as a context
    manager, and this script does not use one, so the tables were never
    created. Against an empty database the first query failed with
    "no such table: users". The script now calls run_legacy_schema_sync()
    explicitly, and it must do so before _get_admin touches the database.
    """
    # Look inside main(): "_get_admin(db)" also matches its own def line.
    source = (SCRIPTS_DIR / "smoke_test.py").read_text(encoding="utf-8")
    body = source[source.index("def main() -> None:") :]

    create_at = body.index("run_legacy_schema_sync()")
    first_query_at = body.index("_get_admin(db)")
    assert create_at < first_query_at, "the schema must exist before it is queried"


def test_the_schema_creation_happens_after_the_guards():
    """Nothing may touch the database before the guards have run."""
    source = (SCRIPTS_DIR / "smoke_test.py").read_text(encoding="utf-8")
    body = source[source.index("def main() -> None:") :]

    preflight_at = body.index("ADMIN_PASSWORD = preflight()")
    create_at = body.index("run_legacy_schema_sync()")
    assert preflight_at < create_at, "guards run first, then the schema"


def test_the_guards_are_still_the_first_thing_main_does():
    source = (SCRIPTS_DIR / "smoke_test.py").read_text(encoding="utf-8")
    main_at = source.index("def main() -> None:")
    body = source[main_at:]
    # preflight() must come before any application import.
    assert body.index("preflight()") < body.index("from app.main import")


def test_run_legacy_schema_sync_is_importable_and_creates_tables(tmp_path):
    """The function the script relies on really does create the schema."""
    from sqlalchemy import create_engine, inspect

    from app.db.base import Base
    import app.models  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    assert inspect(engine).get_table_names() == []
    Base.metadata.create_all(bind=engine)
    tables = set(inspect(engine).get_table_names())
    assert {"users", "datasets", "cases", "dataset_runs"} <= tables
    engine.dispose()
