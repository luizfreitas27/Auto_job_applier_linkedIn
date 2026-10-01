'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Local "control panel" web app. It lets a non-technical person configure and run
the tool from a browser instead of editing Python files and using a terminal.

IMPORTANT - how configuration works:
  * This app reads/writes ONLY `user_config.json` at the project root.
  * It NEVER edits the config/*.py files.
  * The config/*.py modules load user_config.json over their built-in defaults
    (see config/_overrides.py), so saving here changes the tool's behaviour
    while leaving the classic "edit the .py files" workflow intact. With no
    user_config.json present the tool behaves exactly as it always has.

SECURITY: this app handles LinkedIn credentials, so it binds to 127.0.0.1 only
(never 0.0.0.0), runs with debug OFF, sends no CORS headers, masks every
password-type value it returns, and rejects state-changing requests that do not
carry the control-panel header (see `_reject_cross_site_requests`). Do not
change these: any web page open in the same browser can reach 127.0.0.1.
'''

from flask import Flask, Response, request, jsonify, render_template, abort
import csv
from datetime import datetime
import os
import sys
import json
import copy
import signal
import subprocess
import threading
import importlib

import config_schema
from config import _overrides
from modules import updater
from modules.answers_memory import AnswerMemory, STATES

app = Flask(__name__)


# ===========================================================================
# Browser-side hardening
#
# A web page open in the same browser can send requests to 127.0.0.1. Three
# rules close that off without changing how the panel itself works:
#   * No CORS headers are ever sent, so a cross-origin fetch() cannot READ a
#     response (never add flask-cors back).
#   * Every state-changing request (POST/PUT/DELETE) must carry a custom header. A
#     cross-origin request with a custom header needs a CORS preflight, which
#     fails here, so another page cannot even SEND one. Plain <form> posts have
#     no way to add the header either.
#   * The Host header must be a loopback name, which stops DNS rebinding from
#     dressing an attacker's hostname up as this server.
# ===========================================================================
PANEL_HEADER = "X-Requested-With"
PANEL_HEADER_VALUE = "control-panel"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def _host_is_loopback(host: str) -> bool:
    '''True for "127.0.0.1", "localhost" or "[::1]", with or without a :port.'''
    host = (host or "").strip().lower()
    if host.startswith("["):                      # [::1]:5000
        host = host.split("]", 1)[0] + "]"
    else:
        host = host.rsplit(":", 1)[0]
    return host in _LOOPBACK_HOSTS


@app.before_request
def _reject_cross_site_requests():
    if not _host_is_loopback(request.host):
        abort(403, "This panel only answers to 127.0.0.1 / localhost.")
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if request.headers.get(PANEL_HEADER) != PANEL_HEADER_VALUE:
        abort(403, "Missing the control-panel request header.")
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/").lower() != ("%s://%s" % (request.scheme, request.host)).lower():
        abort(403, "Cross-origin request rejected.")
    return None

# Project root is the folder this file lives in.
ROOT = os.path.dirname(os.path.abspath(__file__))
USER_CONFIG_PATH = _overrides.USER_CONFIG_PATH
LOG_PATH = os.path.join(ROOT, ".bot_run.log")
PID_PATH = os.path.join(ROOT, ".bot_run.pid")

PATH = 'all excels/'


# ===========================================================================
# Default config values (the pristine config/*.py defaults, ignoring any
# user_config.json). Captured once at startup so /api/config can always show
# "default overlaid with the user's current saved values".
# ===========================================================================
def _load_defaults() -> dict:
    '''
    Import each config module with overrides temporarily disabled, so we read
    the untouched Python defaults regardless of whether user_config.json exists
    right now. Returns {config_module: {key: default_value}}.
    '''
    original_loader = _overrides.load_user_config
    _overrides.load_user_config = lambda: {}
    try:
        import config.secrets as _secrets
        import config.personals as _personals
        import config.questions as _questions
        import config.search as _search
        import config.settings as _settings
        modules = {
            "secrets": _secrets,
            "personals": _personals,
            "questions": _questions,
            "search": _search,
            "settings": _settings,
        }
        # Reload in case they were already imported (with real overrides) earlier.
        for module in modules.values():
            importlib.reload(module)
        defaults = {}
        for field in config_schema.iter_fields():
            module_name = field["config_module"]
            key = field["key"]
            module = modules.get(module_name)
            defaults.setdefault(module_name, {})[key] = getattr(module, key, None)
        return defaults
    finally:
        _overrides.load_user_config = original_loader


DEFAULTS = _load_defaults()


# ===========================================================================
# Secret masking. Password-type fields (LinkedIn password, AI key) never leave
# the server in clear text: responses show SECRET_MASK in their place, and a
# save that sends SECRET_MASK back means "keep what is stored". Values equal to
# the shipped default (e.g. "not-needed") are not secrets and stay visible.
# ===========================================================================
SECRET_MASK = "********"


def _secret_fields():
    '''[(config_module, key)] of every password-type field in the schema.'''
    return [(field["config_module"], field["key"])
            for field in config_schema.iter_fields() if field.get("type") == "password"]


def _mask_secrets(config: dict) -> dict:
    '''A deep copy of `config` with every non-default secret replaced by SECRET_MASK.'''
    masked = copy.deepcopy(config)
    for module_name, key in _secret_fields():
        section = masked.get(module_name)
        if not isinstance(section, dict):
            continue
        value = section.get(key)
        if value and value != DEFAULTS.get(module_name, {}).get(key):
            section[key] = SECRET_MASK
    return masked


# ===========================================================================
# Config API helpers
# ===========================================================================
def _effective_config() -> dict:
    '''
    Return {config_module: {key: value}} of the pristine defaults overlaid with
    the CURRENT contents of user_config.json (re-read from disk on every call).
    Only keys defined in config_schema are included.
    '''
    effective = copy.deepcopy(DEFAULTS)
    user = _overrides.load_user_config()
    for field in config_schema.iter_fields():
        module_name = field["config_module"]
        key = field["key"]
        section = user.get(module_name)
        if isinstance(section, dict) and key in section:
            effective[module_name][key] = section[key]
    return effective


def _coerce(field_type: str, value):
    '''
    Coerce an incoming JSON value into the type declared for the field in the
    schema. Raises ValueError on invalid numbers so the caller can reject them.
    '''
    if field_type in ("text", "password", "textarea", "select"):
        return "" if value is None else str(value)

    if field_type == "number":
        if isinstance(value, bool):
            raise ValueError("expected a number, got a boolean")
        if isinstance(value, (int, float)):
            number = value
        else:
            text = str(value).strip()
            if text == "":
                raise ValueError("expected a number, got an empty value")
            number = float(text)
        # Keep whole numbers as ints (the config defaults are ints).
        if isinstance(number, float) and number.is_integer():
            return int(number)
        return number

    if field_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")

    if field_type == "list":
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip() != ""]
        text = str(value).strip()
        if text == "":
            return []
        return [item.strip() for item in text.split(",") if item.strip() != ""]

    # Unknown type: pass through untouched.
    return value


# ===========================================================================
# Bot subprocess management (run / stop / status / logs)
# ===========================================================================
_bot_proc = None
_bot_lock = threading.Lock()


def _bot_command():
    '''The command used to launch the bot. Isolated so tests can monkeypatch it.'''
    return [sys.executable, os.path.join(ROOT, "runAiBot.py")]


def _is_running() -> bool:
    '''True if the tracked bot subprocess exists and has not exited.'''
    global _bot_proc
    if _bot_proc is None:
        return False
    if _bot_proc.poll() is None:
        return True
    # Process has exited; clean up tracking + PID file.
    _bot_proc = None
    _remove_pid_file()
    return False


def _remove_pid_file():
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


def _terminate(proc) -> None:
    '''Terminate the subprocess and, where feasible, its child processes.'''
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # Kill the whole process tree on Windows.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            # We launched with start_new_session=True, so the child is its own
            # process-group leader; signal the whole group.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    # Give it a moment, then force-kill if still alive.
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            pass


# The update bar is appended to the rendered page instead of being written into
# control_panel.html, so that template stays a pure offline document.
# ponytail: string append at </body>; move it into the template if it ever needs
# to be more than a one-line banner.
_UPDATE_BAR = '''
<div id="updateBar" style="display:none;position:sticky;bottom:0;z-index:10;background:#fffbeb;
     border-top:1px solid #dce1e8;padding:10px 16px;font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1f2733">
  <span id="updateText"></span>
  <button id="updateBtn" style="margin-left:8px;padding:4px 12px;border:0;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer">Update now</button>
</div>
<script>
(function () {
    var bar = document.getElementById('updateBar');
    var text = document.getElementById('updateText');
    var btn = document.getElementById('updateBtn');
    // Fired after the page is already interactive, so a slow or dead network
    // delays nothing. A failed check simply leaves the bar hidden.
    fetch('/api/update-check').then(function (r) { return r.json(); }).then(function (d) {
        if (!d.update_available) return;
        text.textContent = 'Update available: ' + d.current + ' -> ' + d.latest;
        bar.style.display = 'block';
    }).catch(function () {});
    btn.addEventListener('click', function () {
        btn.disabled = true;
        text.textContent = 'Updating, please wait...';
        fetch('/api/update', {method: 'POST', headers: {'X-Requested-With': 'control-panel'}}).then(function (r) { return r.json(); }).then(function (d) {
            text.textContent = d.ok ? 'Updated. Close this window and start the app again.'
                                    : 'Update failed. ' + d.message;
            btn.style.display = 'none';
        }).catch(function (err) { text.textContent = 'Update failed. ' + err; btn.disabled = false; });
    });
})();
</script>
'''


@app.route('/')
def home():
    """Serve the control panel single-page app, with the update bar appended."""
    return render_template('control_panel.html').replace('</body>', _UPDATE_BAR + '</body>', 1)


@app.route('/history')
def history():
    """Serve the applied-jobs history page."""
    return render_template('index.html')


# The applied-jobs history CSV the bot writes, and how its columns map to the JSON
# keys the history page consumes.
_HISTORY_CSV = 'all_applied_applications_history.csv'
_HISTORY_FIELDS = {
    'Job ID': 'Job_ID',
    'Title': 'Title',
    'Company': 'Company',
    'HR Name': 'HR_Name',
    'HR Link': 'HR_Link',
    'Job Link': 'Job_Link',
    'External Job link': 'External_Job_link',
    'Date Applied': 'Date_Applied',
}


@app.route('/applied-jobs', methods=['GET'])
def get_applied_jobs():
    """Return the applied-jobs history as JSON for the history page."""
    csv_path = os.path.join(PATH, _HISTORY_CSV)
    if not os.path.exists(csv_path):
        return jsonify({"error": "No applications history found yet."}), 404
    try:
        jobs = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                jobs.append({key: row.get(col, '') for col, key in _HISTORY_FIELDS.items()})
        return jsonify(jobs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/applied-jobs/<job_id>', methods=['PUT'])
def mark_job_applied(job_id):
    """Stamp one job's 'Date Applied' (matched by Job ID) with the current time."""
    csv_path = os.path.join(PATH, _HISTORY_CSV)
    if not os.path.exists(csv_path):
        return jsonify({"error": f"History file not found at {csv_path}"}), 404
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames
            rows = list(reader)
        matched = False
        for row in rows:
            if row.get('Job ID') == job_id:
                row['Date Applied'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                matched = True
        if not matched:
            return jsonify({"error": f"Job ID {job_id} not found"}), 404
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return jsonify({"message": "Date Applied updated."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===========================================================================
# Control-panel API
# ===========================================================================
@app.route('/api/schema', methods=['GET'])
def api_schema():
    '''Returns the field schema the UI renders its forms from.'''
    return jsonify(config_schema.SCHEMA)


@app.route('/api/config', methods=['GET'])
def api_get_config():
    '''
    Returns the effective config: pristine defaults overlaid with the current
    user_config.json, grouped by config module (secrets, personals, questions,
    search, settings).
    '''
    return jsonify(_mask_secrets(_effective_config()))


@app.route('/api/config', methods=['POST'])
def api_save_config():
    '''
    Accepts {config_module: {key: value}}, validates against the schema, coerces
    each value to its declared type, rejects unknown modules/keys, merges into
    user_config.json (read-modify-write) and returns the full saved config with
    secrets masked. A password-type value equal to SECRET_MASK is ignored, so
    re-saving a form that shows the mask never overwrites the stored secret.
    '''
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object of {section: {key: value}}"}), 400

    valid = config_schema.valid_keys()
    unknown = []
    coerced = {}

    for section, values in payload.items():
        if not isinstance(values, dict):
            return jsonify({"error": f"Section '{section}' must be an object"}), 400
        if section not in valid:
            unknown.append(section)
            continue
        for key, value in values.items():
            field = valid[section].get(key)
            if field is None:
                unknown.append(f"{section}.{key}")
                continue
            if field["type"] == "password" and value == SECRET_MASK:
                continue
            try:
                coerced.setdefault(section, {})[key] = _coerce(field["type"], value)
            except ValueError as err:
                return jsonify({"error": f"Invalid value for '{section}.{key}': {err}"}), 400

    if unknown:
        return jsonify({"error": "Unknown settings rejected", "unknown": unknown}), 400

    # Read-modify-write user_config.json.
    current = _overrides.load_user_config()
    for section, values in coerced.items():
        target = current.get(section)
        if not isinstance(target, dict):
            target = {}
        target.update(values)
        current[section] = target

    try:
        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(current, file, indent=2, ensure_ascii=False)
    except OSError as err:
        return jsonify({"error": f"Could not save settings: {err}"}), 500

    return jsonify(_mask_secrets(current))


@app.route('/api/run', methods=['POST'])
def api_run():
    '''Starts the bot as a subprocess if it isn't already running.'''
    global _bot_proc
    with _bot_lock:
        if _is_running():
            return jsonify({"running": True, "pid": _bot_proc.pid,
                            "message": "The tool is already running."})
        try:
            # Truncate the log at the start of each run.
            log_file = open(LOG_PATH, "w", encoding="utf-8")
            popen_kwargs = {
                "cwd": ROOT,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            _bot_proc = subprocess.Popen(_bot_command(), **popen_kwargs)
        except Exception as err:
            return jsonify({"running": False, "error": str(err)}), 500
        try:
            with open(PID_PATH, "w", encoding="utf-8") as pid_file:
                pid_file.write(str(_bot_proc.pid))
        except OSError:
            pass
        return jsonify({"running": True, "pid": _bot_proc.pid})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    '''Stops the running bot subprocess (and its children where possible).'''
    global _bot_proc
    with _bot_lock:
        if _bot_proc is not None:
            _terminate(_bot_proc)
            _bot_proc = None
        _remove_pid_file()
        return jsonify({"running": False})


@app.route('/api/status', methods=['GET'])
def api_status():
    '''Reports whether the bot subprocess is currently running.'''
    with _bot_lock:
        running = _is_running()
        pid = _bot_proc.pid if (running and _bot_proc is not None) else None
        return jsonify({"running": running, "pid": pid})


@app.route('/api/logs', methods=['GET'])
def api_logs():
    '''
    Returns the run log starting from byte offset ?offset=N, plus the byte
    offset to read from next time. The UI polls this while the bot runs.
    '''
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    if not os.path.exists(LOG_PATH):
        return jsonify({"content": "", "next_offset": 0})
    try:
        with open(LOG_PATH, "rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            if offset > size:
                # Log was truncated (a new run started); start over.
                offset = 0
            log_file.seek(offset)
            data = log_file.read()
        content = data.decode("utf-8", errors="replace")
        return jsonify({"content": content, "next_offset": offset + len(data)})
    except OSError as err:
        return jsonify({"content": "", "next_offset": offset, "error": str(err)})


# ===========================================================================
# Review queue (see modules/answers_memory.py). The memory reloads itself when
# the bot, in its own process, changes the file, so every request sees fresh data.
# ===========================================================================
answers_memory = AnswerMemory()


def _review_state(raw: str | None, allow_all: bool) -> str | None:
    '''
    A review state from the query string. None means "all" when `allow_all`; anything that is
    not a known state raises ValueError.
    '''
    if allow_all and raw in (None, "", "all"):
        return None
    if raw not in STATES:
        allowed = list(STATES) + (["all"] if allow_all else [])
        raise ValueError(f"state must be one of {allowed}")
    return raw


def _with_pending_count(body: dict) -> Response:
    '''Every review-queue response carries the pending count, so the tab title can follow it.'''
    body["pending_count"] = answers_memory.pending_count()
    return jsonify(body)


@app.route('/api/answers', methods=['GET'])
def api_list_answers() -> Response | tuple:
    '''Remembered answers, newest first, optionally filtered by ?state=pending|approved|all.'''
    try:
        state = _review_state(request.args.get("state"), allow_all=True)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return _with_pending_count({"answers": [entry.as_row() for entry in answers_memory.list(state)]})


@app.route('/api/answers/<entry_id>', methods=['POST'])
def api_approve_answer(entry_id: str) -> Response | tuple:
    '''Approve a remembered answer, replacing its text first when the body carries "answer".'''
    payload = request.get_json(silent=True) or {}
    answer = payload.get("answer")
    if answer is not None:
        answer = str(answer).strip()
        if answer == "":
            return jsonify({"error": "An approved answer cannot be empty; delete it instead."}), 400
    entry = answers_memory.approve(entry_id, answer)
    if entry is None:
        return jsonify({"error": "No remembered answer with that id."}), 404
    return _with_pending_count({"answer": entry.as_row()})


@app.route('/api/answers/<entry_id>', methods=['DELETE'])
def api_delete_answer(entry_id: str) -> Response | tuple:
    '''Forget one remembered answer, so its question is treated as new again.'''
    if not answers_memory.delete(entry_id):
        return jsonify({"error": "No remembered answer with that id."}), 404
    return _with_pending_count({"deleted": 1})


@app.route('/api/answers', methods=['DELETE'])
def api_delete_answers_in_state() -> Response | tuple:
    '''Forget every remembered answer in ?state=pending|approved (bulk clear of the review queue).'''
    try:
        state = _review_state(request.args.get("state"), allow_all=False)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return _with_pending_count({"deleted": answers_memory.delete_all(state)})


# ===========================================================================
# Update check (see modules/updater.py)
# ===========================================================================
def _freeze_config() -> None:
    '''
    Copy the settings the tool is using RIGHT NOW into user_config.json, before
    an update rewrites the config/*.py files.

    For control-panel users this is a no-op: their values are already in the
    JSON. For someone who configured the old way by hand-editing config/*.py it
    is what stops the update reverting them to the shipped defaults, because
    config/_overrides.py re-applies the JSON over whatever `git pull` writes.

    ponytail: this pins every schema key to today's value, so a later change to
    a shipped default stops reaching that user. Acceptable - a hand-edited file
    was already pinned. Freeze only the keys that differ from HEAD if it bites.
    '''
    current = _overrides.load_user_config()
    for section, values in _effective_config().items():
        if not isinstance(current.get(section), dict):
            current[section] = {}
        for key, value in values.items():
            current[section].setdefault(key, value)
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as file:
        json.dump(current, file, indent=2, ensure_ascii=False)


@app.route('/api/update-check', methods=['GET'])
def api_update_check():
    '''
    The local version vs the published one. Reports "no update" rather than an
    error when the check fails, so being offline is invisible to the user. The
    UI calls this after the page is interactive, so it never delays startup.
    '''
    latest = updater.latest_version()
    current = updater.current_version()
    return jsonify({"current": current, "latest": latest,
                    "update_available": updater.is_newer(latest, current)})


@app.route('/api/update', methods=['POST'])
def api_update():
    '''Saves the live settings, then fast-forwards this clone to the newest commit.'''
    try:
        _freeze_config()
    except OSError as err:
        return jsonify({"ok": False,
                        "message": "Could not save your settings first: %s" % err}), 500
    return jsonify(updater.self_update())


def _resolve_port(preferred: int = 5000) -> int:
    '''
    Pick a port to serve on. Honors the PORT environment variable (the launcher
    scripts set it). Otherwise tries `preferred`, and if that's taken - e.g. port
    5000 is used by AirPlay Receiver on macOS - asks the OS for any free port so
    the panel always starts instead of crashing with "address already in use".
    '''
    import socket
    requested = os.environ.get("PORT", "").strip()
    if requested.isdigit():
        return int(requested)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


if __name__ == '__main__':
    # SECURITY: localhost only, debug OFF. This app handles credentials.
    port = _resolve_port(5000)
    url = "http://127.0.0.1:%d" % port
    print(
        "\n  Control panel ready at:  %s\n"
        "  Keep this window open while you use the tool; close it to stop.\n" % url,
        flush=True,
    )
    # The launcher scripts set PANEL_OPEN_BROWSER=1 so the browser opens itself,
    # to the right port, cross-platform. Running `python app.py` by hand won't.
    if os.environ.get("PANEL_OPEN_BROWSER", "").strip() not in ("", "0", "false", "False"):
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
