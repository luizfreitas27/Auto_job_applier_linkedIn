'''
Schedule windows: the pure logic in modules/schedule.py, the panel's /api/schedule routes,
and the scheduler tick driving start/stop through the same functions as the Run buttons.

License: MIT  (https://opensource.org/license/mit)
'''

import json
from datetime import datetime

import pytest

from modules import schedule
from modules.schedule import ScheduleWindow, parse_windows, window_is_active, decide

PANEL = {"X-Requested-With": "control-panel"}

# Monday 2026-10-05 is a known Monday (weekday 0).
MON = datetime(2026, 10, 5)
TUE = datetime(2026, 10, 6)
SAT = datetime(2026, 10, 10)


def at(day: datetime, hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return day.replace(hour=hour, minute=minute, second=17)


# ------------------------------------ parse ---------------------------------
def test_parse_accepts_the_panel_shape_and_normalises_days():
    windows = parse_windows([{"days": [4, 0, 0, 2], "start": "09:00", "end": "17:30"}])
    assert windows == [ScheduleWindow(days=(0, 2, 4), start="09:00", end="17:30")]
    assert windows[0].as_dict() == {"days": [0, 2, 4], "start": "09:00", "end": "17:30"}


def test_parse_of_nothing_is_no_windows():
    assert parse_windows(None) == [] and parse_windows([]) == []


@pytest.mark.parametrize("raw, message", [
    ({"days": [0]}, "must be a list"),
    ([{"days": [], "start": "09:00", "end": "10:00"}], "at least one weekday"),
    ([{"days": [7], "start": "09:00", "end": "10:00"}], "weekdays are 0"),
    ([{"days": [True], "start": "09:00", "end": "10:00"}], "weekdays are 0"),
    ([{"days": [0], "start": "9:00", "end": "10:00"}], "start"),
    ([{"days": [0], "start": "09:00", "end": "24:00"}], "end"),
    ([{"days": [0], "start": "09:00"}], "end"),
    (["not an object"], "must be an object"),
    ([{"days": [0], "start": "09:00", "end": "09:00"}], "same time"),
])
def test_parse_rejects_bad_input_with_a_message_for_the_user(raw, message):
    with pytest.raises(ValueError, match=message):
        parse_windows(raw)


# ------------------------------------ active --------------------------------
WEEKDAY_NINE_TO_FIVE = parse_windows([{"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00"}])


def test_inside_the_window_on_a_listed_day_is_active():
    assert window_is_active(WEEKDAY_NINE_TO_FIVE, at(MON, "12:00"))


def test_start_is_inclusive_and_end_is_exclusive():
    assert window_is_active(WEEKDAY_NINE_TO_FIVE, at(MON, "09:00"))
    assert not window_is_active(WEEKDAY_NINE_TO_FIVE, at(MON, "17:00"))
    assert window_is_active(WEEKDAY_NINE_TO_FIVE, at(MON, "16:59"))


def test_outside_the_hours_or_on_another_day_is_not_active():
    assert not window_is_active(WEEKDAY_NINE_TO_FIVE, at(MON, "08:59"))
    assert not window_is_active(WEEKDAY_NINE_TO_FIVE, at(SAT, "12:00"))


def test_an_overnight_window_belongs_to_the_day_it_starts_on():
    night = parse_windows([{"days": [0], "start": "22:00", "end": "02:00"}])       # Monday night
    assert night[0].spans_midnight
    assert window_is_active(night, at(MON, "23:30"))
    assert window_is_active(night, at(TUE, "01:59"))      # Tuesday small hours, started Monday
    assert not window_is_active(night, at(TUE, "02:00"))
    assert not window_is_active(night, at(TUE, "23:30"))  # Tuesday night is not listed
    assert not window_is_active(night, at(MON, "01:00"))  # Monday small hours belong to Sunday night


def test_no_windows_means_never_active():
    assert not window_is_active([], at(MON, "12:00"))


# ------------------------------------ decide --------------------------------
def test_decisions_are_edge_triggered():
    assert decide(True, None) == "start"       # the panel came up inside a window
    assert decide(True, False) == "start"      # a window began
    assert decide(True, True) is None          # still inside: leave the bot alone, even if it stopped
    assert decide(False, True) == "stop"       # the window ended
    assert decide(False, False) is None
    assert decide(False, None) is None


# ------------------------------------ panel API -----------------------------
@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    cfg_path = tmp_path / "user_config.json"
    monkeypatch.setattr(app, "USER_CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(app, "_schedule_active_before", None)
    return cfg_path


def test_schedule_round_trips_through_the_panel_and_lives_beside_the_settings(client, isolated_config):
    # Settings saved first must survive the schedule save (read-modify-write).
    client.post("/api/config", json={"secrets": {"use_AI": True}}, headers=PANEL)

    resp = client.post("/api/schedule", json={"windows": [{"days": [0, 4], "start": "09:00", "end": "17:00"}]}, headers=PANEL)
    assert resp.status_code == 200
    assert resp.get_json()["windows"] == [{"days": [0, 4], "start": "09:00", "end": "17:00"}]

    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["schedule"] == {"windows": [{"days": [0, 4], "start": "09:00", "end": "17:00"}]}
    assert saved["secrets"]["use_AI"] is True

    got = client.get("/api/schedule").get_json()
    assert got["windows"] == [{"days": [0, 4], "start": "09:00", "end": "17:00"}]
    assert got["active_now"] in (True, False) and "error" not in got


def test_an_empty_list_clears_the_schedule(client, isolated_config):
    client.post("/api/schedule", json={"windows": [{"days": [0], "start": "09:00", "end": "17:00"}]}, headers=PANEL)
    client.post("/api/schedule", json={"windows": []}, headers=PANEL)
    assert client.get("/api/schedule").get_json()["windows"] == []


def test_a_bad_schedule_is_rejected_and_nothing_is_written(client, isolated_config):
    resp = client.post("/api/schedule", json={"windows": [{"days": [], "start": "09:00", "end": "17:00"}]}, headers=PANEL)
    assert resp.status_code == 400 and "weekday" in resp.get_json()["error"]
    assert client.post("/api/schedule", json=["nope"], headers=PANEL).status_code == 400
    assert not isolated_config.exists()


def test_the_schedule_section_does_not_leak_into_the_config_api_or_the_bot(client, isolated_config):
    client.post("/api/schedule", json={"windows": [{"days": [0], "start": "09:00", "end": "17:00"}]}, headers=PANEL)
    assert "schedule" not in client.get("/api/config").get_json()
    import config._overrides as overrides
    namespace = {"use_AI": False}
    overrides.apply("config.schedule", namespace)          # a section that is not a config module
    assert namespace == {"use_AI": False}


def test_saving_the_schedule_needs_the_panel_header(client, isolated_config):
    assert client.post("/api/schedule", json={"windows": []}).status_code == 403
    assert client.get("/api/schedule", base_url="http://evil.example/").status_code == 403


def test_a_corrupt_schedule_section_is_treated_as_no_windows(client, isolated_config):
    isolated_config.write_text(json.dumps({"schedule": {"windows": "garbage"}}), encoding="utf-8")
    assert client.get("/api/schedule").get_json()["windows"] == []


# ------------------------------------ scheduler tick -------------------------
@pytest.fixture
def fake_bot(monkeypatch):
    '''Record start/stop requests instead of launching a process.'''
    import app
    calls = []
    monkeypatch.setattr(app, "start_bot", lambda: (calls.append("start") or ({"running": True, "started": True, "pid": 1}, 200)))
    monkeypatch.setattr(app, "stop_bot", lambda: (calls.append("stop") or {"running": False}))
    return calls


def test_the_tick_starts_on_entering_a_window_and_stops_on_leaving(client, isolated_config, fake_bot):
    import app
    client.post("/api/schedule", json={"windows": [{"days": [0], "start": "09:00", "end": "17:00"}]}, headers=PANEL)

    assert app.scheduler_tick(at(MON, "08:59")) is None
    assert app.scheduler_tick(at(MON, "09:00")) == "start"
    assert app.scheduler_tick(at(MON, "12:00")) is None        # inside: hands off, even if the bot stopped
    assert app.scheduler_tick(at(MON, "17:00")) == "stop"
    assert app.scheduler_tick(at(MON, "18:00")) is None
    assert fake_bot == ["start", "stop"]


def test_the_panel_coming_up_inside_a_window_starts_the_bot(client, isolated_config, fake_bot):
    import app
    client.post("/api/schedule", json={"windows": [{"days": [0], "start": "09:00", "end": "17:00"}]}, headers=PANEL)
    assert app.scheduler_tick(at(MON, "10:00")) == "start"
    assert fake_bot == ["start"]


def test_a_manual_stop_inside_a_window_is_not_undone_until_the_next_window(client, isolated_config, fake_bot):
    import app
    client.post("/api/schedule", json={"windows": [{"days": [0, 1], "start": "09:00", "end": "17:00"}]}, headers=PANEL)
    app.scheduler_tick(at(MON, "09:00"))
    client.post("/api/stop", headers=PANEL)                     # the user clicks Stop at 10:00
    assert app.scheduler_tick(at(MON, "10:00")) is None         # not restarted
    assert app.scheduler_tick(at(MON, "17:00")) == "stop"       # the window end still fires (idempotent)
    assert app.scheduler_tick(at(TUE, "09:00")) == "start"      # the next window begins
    assert fake_bot == ["start", "stop", "stop", "start"]


def test_a_start_that_fails_at_the_window_edge_is_retried_next_tick(client, isolated_config, monkeypatch):
    import app
    attempts = []
    outcomes = [({"running": False, "started": False, "error": "chromedriver missing"}, 500),
                ({"running": True, "started": True, "pid": 7}, 200)]
    monkeypatch.setattr(app, "start_bot", lambda: (attempts.append(1) or outcomes[len(attempts) - 1]))
    client.post("/api/schedule", json={"windows": [{"days": [0], "start": "09:00", "end": "17:00"}]}, headers=PANEL)

    assert app.scheduler_tick(at(MON, "09:00")) == "start"
    assert app.scheduler_tick(at(MON, "09:00").replace(second=47)) == "start"   # retried
    assert app.scheduler_tick(at(MON, "09:01")) is None                            # and then left alone
    assert len(attempts) == 2


def test_a_corrupt_schedule_section_is_reported_not_hidden(client, isolated_config):
    isolated_config.write_text(json.dumps({"schedule": {"windows": [{"days": [], "start": "x", "end": "y"}]}}), encoding="utf-8")
    body = client.get("/api/schedule").get_json()
    assert body["windows"] == []
    assert "not valid" in body["error"]


def test_user_config_is_written_atomically_and_both_savers_share_one_file(client, isolated_config):
    client.post("/api/schedule", json={"windows": [{"days": [0], "start": "09:00", "end": "17:00"}]}, headers=PANEL)
    client.post("/api/config", json={"secrets": {"use_AI": True}}, headers=PANEL)
    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["schedule"]["windows"][0]["start"] == "09:00" and saved["secrets"]["use_AI"] is True
    assert not (isolated_config.parent / "user_config.json.tmp").exists()


def test_the_tick_without_windows_does_nothing(client, isolated_config, fake_bot):
    import app
    assert app.scheduler_tick(at(MON, "10:00")) is None
    assert fake_bot == []


def test_the_scheduler_thread_is_not_started_by_importing_or_testing_the_app():
    import app
    assert app._scheduler_thread is None
