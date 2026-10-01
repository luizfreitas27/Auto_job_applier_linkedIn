'''
Integration tests for app.py (the local control panel) via Flask's test client.
These exercise real request/response behaviour: schema exposure, config save
coercion + round-trip, unknown-key rejection, and the applied-jobs history
CSV -> JSON mapping and mark-applied flow.

All tests isolate their writes to a tmp_path, so the user's real user_config.json
and "all excels/" folder are never touched.

License: MIT  (https://opensource.org/license/mit)
'''

import csv
import json
import os

# Every state-changing request must carry this header (see app._reject_cross_site_requests).
PANEL = {"X-Requested-With": "control-panel"}


def _isolate_config(tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    return cfg_path


# --------------------------------- schema -----------------------------------
def test_schema_endpoint_returns_nonempty_list(client):
    resp = client.get("/api/schema")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list) and len(data) > 0
    assert "section" in data[0] and "fields" in data[0]


# ------------------------------- config save/get ----------------------------
def test_config_save_coerces_and_roundtrips(client, tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)

    # "true" (string) must be coerced to a real bool for the use_AI field.
    resp = client.post("/api/config", json={"secrets": {"use_AI": "true"}}, headers=PANEL)
    assert resp.status_code == 200

    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["secrets"]["use_AI"] is True

    # GET reflects the saved value.
    got = client.get("/api/config").get_json()
    assert got["secrets"]["use_AI"] is True


def test_config_save_rejects_unknown_key(client, tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)

    resp = client.post("/api/config", json={"secrets": {"definitely_not_a_field": 1}}, headers=PANEL)
    assert resp.status_code == 400
    assert not os.path.exists(cfg_path)  # nothing written on rejection


def test_config_save_rejects_unknown_section(client, tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)

    resp = client.post("/api/config", json={"not_a_section": {"x": 1}}, headers=PANEL)
    assert resp.status_code == 400


# ------------------------------ secret masking ------------------------------
def test_saved_secrets_are_masked_in_every_response(client, tmp_path, monkeypatch):
    import app
    cfg_path = _isolate_config(tmp_path, monkeypatch)

    resp = client.post("/api/config", json={"secrets": {"password": "hunter2", "llm_api_key": "sk-real"}},
                       headers=PANEL)
    assert resp.status_code == 200
    # Neither the save response nor a later GET leaks the clear text...
    assert resp.get_json()["secrets"]["password"] == app.SECRET_MASK
    got = client.get("/api/config").get_json()["secrets"]
    assert got["password"] == app.SECRET_MASK
    assert got["llm_api_key"] == app.SECRET_MASK
    assert "hunter2" not in client.get("/api/config").get_data(as_text=True)
    # ...while the file on disk holds the real values the bot needs.
    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)["secrets"]
    assert saved["password"] == "hunter2" and saved["llm_api_key"] == "sk-real"


def test_shipped_default_placeholders_are_not_masked(client, tmp_path, monkeypatch):
    _isolate_config(tmp_path, monkeypatch)
    got = client.get("/api/config").get_json()["secrets"]
    # "not-needed" is documentation, not a secret: the user must be able to read it.
    assert got["llm_api_key"] == "not-needed"


def test_sending_the_mask_back_keeps_the_stored_secret(client, tmp_path, monkeypatch):
    import app
    cfg_path = _isolate_config(tmp_path, monkeypatch)
    client.post("/api/config", json={"secrets": {"password": "hunter2"}}, headers=PANEL)

    # Re-saving the form as the browser shows it (mask in the field) changes nothing.
    resp = client.post("/api/config", json={"secrets": {"password": app.SECRET_MASK, "use_AI": True}},
                       headers=PANEL)
    assert resp.status_code == 200
    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)["secrets"]
    assert saved["password"] == "hunter2"
    assert saved["use_AI"] is True

    # Clearing the field really does clear it.
    client.post("/api/config", json={"secrets": {"password": ""}}, headers=PANEL)
    with open(cfg_path, encoding="utf-8") as f:
        assert json.load(f)["secrets"]["password"] == ""


# --------------------------- cross-site protection ---------------------------
def test_responses_carry_no_cors_headers(client):
    resp = client.get("/api/schema", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 200
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_state_changing_requests_need_the_panel_header(client, tmp_path, monkeypatch):
    import app
    cfg_path = _isolate_config(tmp_path, monkeypatch)
    started = []
    monkeypatch.setattr(app, "_bot_command", lambda: started.append(True) or ["true"])

    assert client.post("/api/run").status_code == 403
    assert client.post("/api/stop").status_code == 403
    assert client.post("/api/update").status_code == 403
    assert client.post("/api/config", json={"secrets": {"use_AI": True}}).status_code == 403
    assert client.put("/applied-jobs/J1").status_code == 403
    # A <form> post can set Content-Type but never a custom header.
    assert client.post("/api/run", data="x", content_type="text/plain").status_code == 403
    assert started == [] and not os.path.exists(cfg_path)

    # The panel's own requests (same origin, header present) still work.
    resp = client.post("/api/config", json={"secrets": {"use_AI": True}},
                       headers=dict(PANEL, Origin="http://localhost"))
    assert resp.status_code == 200


def test_foreign_origin_header_is_rejected_even_with_panel_header(client, tmp_path, monkeypatch):
    cfg_path = _isolate_config(tmp_path, monkeypatch)
    resp = client.post("/api/config", json={"secrets": {"use_AI": True}},
                       headers=dict(PANEL, Origin="http://evil.example"))
    assert resp.status_code == 403
    assert not os.path.exists(cfg_path)


def test_non_loopback_host_is_rejected(client):
    # DNS rebinding: an attacker's hostname resolving to 127.0.0.1 arrives with their Host.
    assert client.get("/api/config", base_url="http://evil.example/").status_code == 403
    assert client.get("/api/config", base_url="http://127.0.0.1:5000/").status_code == 200
    assert client.get("/api/config", base_url="http://localhost:5000/").status_code == 200


# ------------------------------ applied-jobs CSV ----------------------------
_CSV_COLUMNS = ['Job ID', 'Title', 'Company', 'HR Name', 'HR Link',
                'Job Link', 'External Job link', 'Date Applied']


def _write_history_csv(folder):
    path = os.path.join(folder, "all_applied_applications_history.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        writer.writerow({
            'Job ID': 'J1', 'Title': 'Engineer', 'Company': 'Acme',
            'HR Name': 'Unknown', 'HR Link': '', 'Job Link': 'http://x',
            'External Job link': 'http://ext', 'Date Applied': 'Pending',
        })
    return path


def test_applied_jobs_get_maps_columns_to_json_keys(client, tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "PATH", str(tmp_path) + os.sep)
    _write_history_csv(str(tmp_path))

    resp = client.get("/applied-jobs")
    assert resp.status_code == 200
    row = resp.get_json()[0]
    assert row["Job_ID"] == "J1"
    assert row["Title"] == "Engineer"
    assert row["External_Job_link"] == "http://ext"
    assert row["Date_Applied"] == "Pending"


def test_applied_jobs_mark_applied_updates_date(client, tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "PATH", str(tmp_path) + os.sep)
    _write_history_csv(str(tmp_path))

    resp = client.put("/applied-jobs/J1", headers=PANEL)
    assert resp.status_code == 200

    row = client.get("/applied-jobs").get_json()[0]
    assert row["Date_Applied"] != "Pending"


def test_applied_jobs_missing_file_returns_404(client, tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "PATH", str(tmp_path) + os.sep)  # empty dir, no CSV
    assert client.get("/applied-jobs").status_code == 404


def test_applied_jobs_mark_unknown_id_returns_404(client, tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "PATH", str(tmp_path) + os.sep)
    _write_history_csv(str(tmp_path))
    assert client.put("/applied-jobs/does-not-exist", headers=PANEL).status_code == 404


# ------------------------------- bot status ---------------------------------
def test_status_reports_not_running(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.get_json()["running"] is False


# ------------------------------- pages render -------------------------------
def test_control_panel_and_history_pages_render(client):
    assert client.get("/").status_code == 200
    assert client.get("/history").status_code == 200
