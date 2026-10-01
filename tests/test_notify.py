'''
Telegram notifications: modules/notify.py with urlopen patched (no network), the bot's two
call sites, the config validation, and the panel masking the token.

License: MIT  (https://opensource.org/license/mit)
'''

import io
import json
import urllib.error
import urllib.request

import pytest

from modules import notify


class _Response:
    '''Minimal stand-in for what urlopen() returns.'''
    def __init__(self, status=200):
        self.status = status

    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def read(self): return b"{}"


@pytest.fixture
def sent(monkeypatch):
    '''Capture the request urlopen would send; answer 200 unless `outcome` says otherwise.'''
    box = {"requests": [], "outcome": _Response(200)}

    def fake_urlopen(request, timeout=None):
        box["requests"].append((request, timeout))
        if isinstance(box["outcome"], BaseException):
            raise box["outcome"]
        return box["outcome"]
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return box


TOKEN = "123456789:AAHtoken"
CHAT = "987654321"


# ------------------------------------ module --------------------------------
def test_a_configured_send_posts_json_to_the_bot_api(sent):
    assert notify.send_message("Run finished.\nApplied: 3", TOKEN, CHAT) is True
    request, timeout = sent["requests"][0]
    assert request.full_url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"chat_id": CHAT, "text": "Run finished.\nApplied: 3", "disable_web_page_preview": True}
    assert timeout == 10


@pytest.fixture(autouse=True)
def forget_half_configured_warning(monkeypatch):
    monkeypatch.setattr(notify, "_half_configured_warned", False)


@pytest.mark.parametrize("token, chat", [("", ""), (None, None), ("  ", "")])
def test_nothing_is_sent_or_logged_when_both_settings_are_empty(sent, log_records, token, chat):
    assert notify.send_message("x", token, chat) is False
    assert sent["requests"] == []
    assert not [r for r in log_records if r.levelname in ("WARNING", "ERROR")]


@pytest.mark.parametrize("token, chat", [(TOKEN, ""), ("", CHAT), ("   ", CHAT)])
def test_half_configured_sends_nothing_and_warns_once(sent, log_records, token, chat):
    '''The user meant to turn it on; say so once, but never abort a run over it.'''
    assert notify.send_message("x", token, chat) is False
    assert notify.send_message("y", token, chat) is False
    assert sent["requests"] == []
    warnings = [r for r in log_records if r.levelname == "WARNING"]
    assert len(warnings) == 1 and "BOTH" in warnings[0].getMessage()
    assert not [r for r in log_records if r.levelname == "ERROR"]


def test_the_chat_id_may_be_a_number(sent):
    assert notify.send_message("x", TOKEN, 987654321) is True
    assert json.loads(sent["requests"][0][0].data)["chat_id"] == "987654321"


def test_a_network_failure_is_a_warning_not_an_exception(sent, log_records):
    sent["outcome"] = urllib.error.URLError("nodename nor servname provided")
    assert notify.send_message("x", TOKEN, CHAT) is False
    assert any("Could not send" in r.getMessage() for r in log_records if r.levelname == "WARNING")


def test_a_rejection_logs_telegrams_description_but_never_the_token(sent, log_records):
    sent["outcome"] = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b'{"ok":false,"description":"Unauthorized"}'))
    assert notify.send_message("x", TOKEN, CHAT) is False
    warnings = [r.getMessage() for r in log_records if r.levelname == "WARNING"]
    assert any("401" in w and "Unauthorized" in w for w in warnings)
    assert all(TOKEN not in w for w in warnings)


def test_a_non_2xx_without_an_exception_is_a_warning(sent, log_records):
    sent["outcome"] = _Response(500)
    assert notify.send_message("x", TOKEN, CHAT) is False
    assert any("500" in r.getMessage() for r in log_records if r.levelname == "WARNING")


def test_long_messages_are_cut_to_telegrams_limit(sent):
    notify.send_message("x" * 5000, TOKEN, CHAT)
    assert len(json.loads(sent["requests"][0][0].data)["text"]) == notify.MAX_MESSAGE_LENGTH


# ------------------------------------ the bot's call sites ------------------
@pytest.fixture
def bot(monkeypatch):
    from tests.fakes import import_bot
    bot = import_bot()
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    return bot


def test_the_bot_sends_the_run_summary_with_the_live_secrets(bot, sent, monkeypatch):
    import config.secrets as secrets
    monkeypatch.setattr(secrets, "telegram_bot_token", TOKEN, raising=False)
    monkeypatch.setattr(secrets, "telegram_chat_id", CHAT, raising=False)

    assert bot.notify_run_end("Total runs: 1\nJobs Easy Applied: 4") is True
    text = json.loads(sent["requests"][0][0].data)["text"]
    assert text.startswith("Auto Job Applier: run finished.")
    assert "Jobs Easy Applied: 4" in text


def test_the_bot_reports_a_fatal_error_with_its_type(bot, sent, monkeypatch):
    import config.secrets as secrets
    monkeypatch.setattr(secrets, "telegram_bot_token", TOKEN, raising=False)
    monkeypatch.setattr(secrets, "telegram_chat_id", CHAT, raising=False)

    assert bot.notify_error("an unexpected error", RuntimeError("boom")) is True
    text = json.loads(sent["requests"][0][0].data)["text"]
    assert text.startswith("Auto Job Applier stopped: an unexpected error")
    assert "RuntimeError: boom" in text


def test_the_bot_stays_quiet_when_telegram_is_not_configured(bot, sent, monkeypatch):
    import config.secrets as secrets
    monkeypatch.setattr(secrets, "telegram_bot_token", "", raising=False)
    monkeypatch.setattr(secrets, "telegram_chat_id", "", raising=False)
    assert bot.notify_run_end("summary") is False
    assert bot.notify_error("x") is False
    assert sent["requests"] == []


def test_main_notifies_on_both_fatal_paths_and_at_the_end(bot):
    import inspect
    source = inspect.getsource(bot.main)
    assert source.count("notify_error(") == 2
    assert "notify_run_end(summary)" in source


# ------------------------------------ config -------------------------------
def test_both_settings_ship_empty_and_one_alone_never_blocks_a_run(monkeypatch):
    import config.secrets as secrets
    import modules.validator as validator
    assert secrets.telegram_bot_token == "" and secrets.telegram_chat_id == ""
    monkeypatch.setattr(validator, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(validator, "telegram_chat_id", "")
    validator.validate_secrets()                       # off, not an error
    monkeypatch.setattr(validator, "telegram_chat_id", 12345)
    with pytest.raises(TypeError):                     # but the type is still checked
        validator.validate_secrets()


def test_the_token_is_a_password_field_and_the_panel_masks_it(client, tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    import config_schema
    fields = {f["key"]: f for f in config_schema.iter_fields() if f["config_module"] == "secrets"}
    assert fields["telegram_bot_token"]["type"] == "password"
    assert fields["telegram_chat_id"]["type"] == "text"
    assert fields["telegram_bot_token"]["section"] == "Account" and not fields["telegram_bot_token"].get("advanced")

    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    resp = client.post("/api/config", json={"secrets": {"telegram_bot_token": TOKEN, "telegram_chat_id": CHAT}},
                       headers={"X-Requested-With": "control-panel"})
    assert resp.status_code == 200
    got = client.get("/api/config").get_json()["secrets"]
    assert got["telegram_bot_token"] == app.SECRET_MASK
    assert got["telegram_chat_id"] == CHAT
