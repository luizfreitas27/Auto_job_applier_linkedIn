'''
Secrets from the environment or `.env`: parsing, precedence over user_config.json and the
config defaults, and the control panel showing such fields as locked.

License: MIT  (https://opensource.org/license/mit)
'''

import importlib
import json
import os

import pytest

from config import _overrides

PANEL = {"X-Requested-With": "control-panel"}
ENV_NAMES = ["LINKEDIN_USERNAME", "LINKEDIN_PASSWORD", "LLM_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    '''A temp .env and user_config.json, and none of the five variables in the real environment.'''
    import app
    env_path = tmp_path / ".env"
    cfg_path = tmp_path / "user_config.json"
    monkeypatch.setattr(_overrides, "ENV_FILE_PATH", str(env_path))
    monkeypatch.setattr(_overrides, "USER_CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(app, "USER_CONFIG_PATH", str(cfg_path))
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return env_path, cfg_path


# ------------------------------------ .env parsing ---------------------------
def test_env_file_parsing_handles_comments_quotes_export_and_junk(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# login\n"
        "LINKEDIN_USERNAME=me@example.com\n"
        "LINKEDIN_PASSWORD='p#ss=word'\n"
        'export LLM_API_KEY="sk-123"\n'
        "\n"
        "TELEGRAM_BOT_TOKEN =  123:abc  \n"
        "this line has no equals sign\n"
        "=novalue\n",
        encoding="utf-8")
    assert _overrides.load_env_file(str(path)) == {
        "LINKEDIN_USERNAME": "me@example.com",
        "LINKEDIN_PASSWORD": "p#ss=word",
        "LLM_API_KEY": "sk-123",
        "TELEGRAM_BOT_TOKEN": "123:abc",
    }


def test_a_missing_or_unreadable_env_file_is_empty(tmp_path):
    assert _overrides.load_env_file(str(tmp_path / "nope")) == {}
    assert _overrides.load_env_file(str(tmp_path)) == {}            # a directory


# ------------------------------------ precedence ----------------------------
def test_env_file_beats_user_config_and_a_real_variable_beats_the_file(isolated, monkeypatch):
    env_path, cfg_path = isolated
    cfg_path.write_text(json.dumps({"secrets": {"password": "from-json", "llm_api_key": "json-key"}}), encoding="utf-8")
    env_path.write_text("LINKEDIN_PASSWORD=from-dotenv\nLLM_API_KEY=dotenv-key\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "from-environment")

    namespace = {"password": "default", "llm_api_key": "default", "username": "default", "use_AI": False}
    _overrides.apply("config.secrets", namespace)

    assert namespace["password"] == "from-dotenv"
    assert namespace["llm_api_key"] == "from-environment"
    assert namespace["username"] == "default"                 # untouched when nothing sets it
    assert namespace["use_AI"] is False


def test_an_empty_variable_means_not_set(isolated, monkeypatch):
    env_path, cfg_path = isolated
    cfg_path.write_text(json.dumps({"secrets": {"password": "from-json"}}), encoding="utf-8")
    env_path.write_text("LINKEDIN_PASSWORD=\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "")
    namespace = {"password": "default", "llm_api_key": "default"}
    _overrides.apply("config.secrets", namespace)
    assert namespace == {"password": "from-json", "llm_api_key": "default"}


def test_only_secret_settings_have_environment_names(isolated, monkeypatch):
    monkeypatch.setenv("LINKEDIN_PASSWORD", "x")
    assert _overrides.env_overrides("secrets") == {"password": "x"}
    assert _overrides.env_overrides("settings") == {}
    assert _overrides.env_overrides("personals") == {}


def test_the_live_secrets_module_picks_the_environment_up(isolated, monkeypatch):
    monkeypatch.setenv("LINKEDIN_PASSWORD", "live-secret")
    import config.secrets as secrets
    importlib.reload(secrets)
    try:
        assert secrets.password == "live-secret"
    finally:
        monkeypatch.delenv("LINKEDIN_PASSWORD")
        importlib.reload(secrets)


# ------------------------------------ control panel --------------------------
def test_the_panel_reports_locked_fields_masked(client, isolated, monkeypatch):
    env_path, _ = isolated
    env_path.write_text("LINKEDIN_PASSWORD=from-dotenv\nTELEGRAM_CHAT_ID=987\n", encoding="utf-8")
    import app
    body = client.get("/api/config").get_json()
    assert body["_locked"] == {"secrets": ["password", "telegram_chat_id"]}
    assert body["secrets"]["password"] == app.SECRET_MASK
    assert body["secrets"]["telegram_chat_id"] == "987"
    assert "from-dotenv" not in client.get("/api/config").get_data(as_text=True)


def test_nothing_is_locked_without_environment_values(client, isolated):
    assert client.get("/api/config").get_json()["_locked"] == {}


def test_saving_a_locked_field_is_refused_and_nothing_is_written(client, isolated):
    env_path, cfg_path = isolated
    env_path.write_text("LINKEDIN_PASSWORD=from-dotenv\n", encoding="utf-8")
    resp = client.post("/api/config", json={"secrets": {"password": "typed-in-the-panel"}}, headers=PANEL)
    assert resp.status_code == 400
    assert "LINKEDIN_PASSWORD" in resp.get_json()["error"]
    assert not cfg_path.exists()


def test_other_fields_still_save_while_one_is_locked(client, isolated):
    env_path, cfg_path = isolated
    env_path.write_text("LINKEDIN_PASSWORD=from-dotenv\n", encoding="utf-8")
    resp = client.post("/api/config", json={"secrets": {"use_AI": True}}, headers=PANEL)
    assert resp.status_code == 200
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["secrets"]["use_AI"] is True


def test_the_defaults_snapshot_ignores_the_environment(isolated, monkeypatch):
    '''The panel's "default" column must stay the shipped default even when .env is set.'''
    monkeypatch.setenv("LINKEDIN_PASSWORD", "live-secret")
    import app
    defaults = app._load_defaults()
    assert defaults["secrets"]["password"] == "example_password"


# ------------------------------------ repo hygiene --------------------------
def test_env_is_gitignored_and_the_example_lists_every_variable():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    assert "\n.env\n" in root.joinpath(".gitignore").read_text(encoding="utf-8")
    example = root.joinpath(".env.example").read_text(encoding="utf-8")
    for name in ENV_NAMES:
        assert f"{name}=" in example
    assert set(_overrides.SECRET_ENV_NAMES["secrets"].values()) == set(ENV_NAMES)
