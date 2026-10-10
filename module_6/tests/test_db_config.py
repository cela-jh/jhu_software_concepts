"""
`test_db_config.py`
Covers how database credentials reach the application: building the
connection URL from the DB_* environment variables, and loading those
variables from a .env file without overriding real exports.
"""
import os

import pytest
from psycopg.conninfo import conninfo_to_dict

from database import db_helpers

DB_VARS = {
    "DB_HOST": "db.example.com",
    "DB_PORT": "6543",
    "DB_NAME": "cam_db",
    "DB_USER": "gradcafe_app",
    "DB_PASSWORD": "p@ss/word:with#symbols",
}


@pytest.fixture
def db_env(monkeypatch):
    # Clear DATABASE_URL so database_url_from_env() uses the DB_* fallback
    # path; in CI, DATABASE_URL is set in the job env and would short-circuit
    # every test that exercises the DB_* vars if left in place.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name, value in DB_VARS.items():
        monkeypatch.setenv(name, value)


@pytest.mark.db
def test_database_url_built_from_db_vars_round_trips(db_env):
    """Every part, including a password with URL-special characters,
    must reach psycopg unchanged."""
    parsed = conninfo_to_dict(db_helpers.database_url_from_env())

    assert parsed == {
        "host": "db.example.com", "port": "6543", "dbname": "cam_db",
        "user": "gradcafe_app", "password": "p@ss/word:with#symbols",
    }


@pytest.mark.db
def test_database_url_allows_blank_password(db_env, monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "")

    assert "password" not in conninfo_to_dict(db_helpers.database_url_from_env())


@pytest.mark.db
def test_database_url_names_every_missing_variable(db_env, monkeypatch):
    monkeypatch.delenv("DB_HOST")
    monkeypatch.setenv("DB_USER", "")

    with pytest.raises(db_helpers.DatabaseConfigError) as error:
        db_helpers.database_url_from_env()

    assert "DB_HOST" in str(error.value)
    assert "DB_USER" in str(error.value)
    assert "DB_PORT" not in str(error.value)


@pytest.mark.db
def test_database_url_rejects_non_numeric_port(db_env, monkeypatch):
    monkeypatch.setenv("DB_PORT", "5432; DROP")

    with pytest.raises(db_helpers.DatabaseConfigError, match="DB_PORT"):
        db_helpers.database_url_from_env()


@pytest.mark.db
def test_load_env_file_sets_unset_variables_only(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# local credentials\n"
        "\n"
        "PLAIN=plain\n"
        "export EXPORTED=exported\n"
        "QUOTED=\"has spaces\"\n"
        "EQUALS=a=b\n"
        "not a variable line\n"
        "ALREADY_SET=from_file\n"
    )
    # a throwaway environment, so nothing loaded here leaks into other tests
    fake_environ = {"ALREADY_SET": "from_shell"}
    monkeypatch.setattr(os, "environ", fake_environ)

    db_helpers.load_env_file(env_file)

    assert fake_environ == {
        "PLAIN": "plain",
        "EXPORTED": "exported",
        "QUOTED": "has spaces",
        "EQUALS": "a=b",
        "ALREADY_SET": "from_shell",  # a real export wins over the file
    }


@pytest.mark.db
def test_load_env_file_ignores_missing_file(tmp_path):
    db_helpers.load_env_file(tmp_path / "does_not_exist.env")  # must not raise


@pytest.mark.db
def test_database_url_uses_database_url_env_var_when_set(monkeypatch):
    """When DATABASE_URL is present it takes priority over DB_* variables."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/mydb")
    monkeypatch.delenv("DB_HOST", raising=False)

    result = db_helpers.database_url_from_env()

    assert result == "postgresql://u:p@host:5432/mydb"
