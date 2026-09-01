"""SECRET_KEY has no default and the application refuses to run without it.

It signs every JWT. A default would mean an instance deployed without the
variable signs tokens with a value published in this repository, and anyone
who read it could mint an administrator token.

Settings are built with ``_env_file=None`` so a developer's own backend/.env
cannot make these pass by accident.
"""

import pathlib

import pytest
from pydantic import ValidationError

from app.core.config import _PLACEHOLDER_SECRETS, Settings

# Everything except secret_key, so each test isolates the one field.
BASE = {"database_url": "sqlite://"}


def build(**overrides) -> Settings:
    return Settings(_env_file=None, **BASE, **overrides)


# --- 1. a configured key is accepted ---------------------------------------


def test_a_configured_secret_key_produces_valid_settings():
    settings = build(secret_key="k7Qp2vN8xR4mL9wT3yB6zC1jH5sF0dGa")
    assert settings.secret_key == "k7Qp2vN8xR4mL9wT3yB6zC1jH5sF0dGa"


def test_surrounding_whitespace_is_trimmed_not_rejected():
    assert build(secret_key="  abcdef0123456789  ").secret_key == "abcdef0123456789"


def test_the_real_environment_is_configured(monkeypatch):
    """The suite itself must supply one, proving the app is usable with it."""
    from app.core.config import settings

    assert settings.secret_key
    assert settings.secret_key.lower() not in _PLACEHOLDER_SECRETS


# --- 2. an absent key is invalid -------------------------------------------


def test_an_absent_secret_key_is_rejected(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError) as failure:
        Settings(_env_file=None, **BASE)

    error = failure.value.errors()[0]
    assert error["loc"] == ("secret_key",)
    assert error["type"] == "missing"


def test_the_field_declares_no_default_at_all():
    """Guards against a default being reintroduced later."""
    field = Settings.model_fields["secret_key"]
    assert field.is_required(), "secret_key must have no default"
    assert field.default is not None or field.is_required()


def test_no_known_placeholder_survives_as_a_default():
    source = (
        pathlib.Path(__file__).resolve().parents[1] / "app" / "core" / "config.py"
    ).read_text(encoding="utf-8")
    # The old line was: secret_key: str = "change-me"
    assert 'secret_key: str = "change-me"' not in source
    assert 'secret_key: str = "' not in source


# --- 3. an empty key is invalid --------------------------------------------


@pytest.mark.parametrize("value", ["", "   ", "\t", "\n"])
def test_an_empty_secret_key_is_rejected(value):
    with pytest.raises(ValidationError) as failure:
        build(secret_key=value)
    assert failure.value.errors()[0]["loc"] == ("secret_key",)


# --- 4. a known placeholder is never used ----------------------------------


@pytest.mark.parametrize("value", sorted(_PLACEHOLDER_SECRETS))
def test_every_known_placeholder_is_rejected(value):
    with pytest.raises(ValidationError):
        build(secret_key=value)


@pytest.mark.parametrize("value", ["Change-Me", "CHANGE-ME", "  change-me  "])
def test_placeholders_are_rejected_regardless_of_case_or_spacing(value):
    with pytest.raises(ValidationError):
        build(secret_key=value)


def test_the_old_default_is_specifically_rejected():
    """The exact string this project used to ship with."""
    assert "change-me" in _PLACEHOLDER_SECRETS
    with pytest.raises(ValidationError):
        build(secret_key="change-me")


def test_a_value_merely_containing_a_placeholder_is_still_accepted():
    """The check is on the whole value, not a substring.

    A random key could legitimately contain the letters "secret".
    """
    assert build(secret_key="my-secret-9f3a2b7c1d4e").secret_key


# --- the template ships no value -------------------------------------------


def test_the_env_template_declares_the_variable_without_a_value():
    template = (
        pathlib.Path(__file__).resolve().parents[1] / ".env.example"
    ).read_text(encoding="utf-8")
    assert "\nSECRET_KEY=\n" in template, "the template must not carry a value"
    assert "SECRET_KEY=change-me" not in template
