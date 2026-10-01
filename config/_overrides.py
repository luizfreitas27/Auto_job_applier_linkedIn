'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Loads user settings saved by the local control panel (see app.py) from
`user_config.json` at the project root, and applies them over the Python
defaults defined in the config/*.py files. Secrets can also come from the
environment or a `.env` file, which win over both.

Precedence, highest first:
  1. a real environment variable (LINKEDIN_PASSWORD, ...)
  2. the same name in `.env` at the project root (gitignored)
  3. `user_config.json` (written by the control panel, gitignored)
  4. the defaults in config/*.py

Only the five secret settings listed in SECRET_ENV_NAMES have an environment
name: structured settings stay in the config files and the panel. If neither
`.env` nor `user_config.json` exists, everything here is a no-op and the tool
behaves exactly as it always has.
'''

import os
import json

# This file lives in <project_root>/config/, so the project root is one level up.
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_CONFIG_DIR)
USER_CONFIG_PATH = os.path.join(_ROOT_DIR, "user_config.json")
ENV_FILE_PATH = os.path.join(_ROOT_DIR, ".env")

# {config section: {setting: environment variable}} for the settings that may come from the
# environment. Secrets only: a leaked config file must never carry them, and an operator
# running the bot on a server wants them in the environment, not on disk.
SECRET_ENV_NAMES = {
    "secrets": {
        "username": "LINKEDIN_USERNAME",
        "password": "LINKEDIN_PASSWORD",
        "llm_api_key": "LLM_API_KEY",
        "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
        "telegram_chat_id": "TELEGRAM_CHAT_ID",
    },
}


def load_env_file(path: str | None = None) -> dict:
    '''
    The KEY=VALUE pairs in `.env` (or `path`). Blank lines and lines starting with `#` are
    skipped (a `#` after the value is part of the value: passwords contain them), an optional
    `export ` prefix and surrounding single or double quotes are removed, and a line without
    `=` is ignored. Missing or unreadable file: {}. Never raises.
    '''
    values = {}
    try:
        with open(path or ENV_FILE_PATH, "r", encoding="utf-8") as file:
            lines = file.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        if text.startswith("export "):
            text = text[len("export "):].strip()
        key, _, value = text.partition("=")
        key, value = key.strip(), value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def all_env_overrides() -> dict:
    '''
    {section: {setting: value}} for every setting the environment provides, reading `.env`
    once. A real environment variable wins over `.env`; empty values count as "not set".
    Sections with nothing set are left out.
    '''
    fromFile = load_env_file()
    found = {}
    for sectionName, names in SECRET_ENV_NAMES.items():
        for setting, envName in names.items():
            value = os.environ.get(envName)
            if value is None or value == "":
                value = fromFile.get(envName)
            if value is not None and value != "":
                found.setdefault(sectionName, {})[setting] = value
    return found


def env_overrides(section_name: str) -> dict:
    '''{setting: value} for the settings of `section_name` that the environment provides.'''
    return all_env_overrides().get(section_name, {})


def load_user_config() -> dict:
    '''
    Returns the full override dictionary from `user_config.json`, or an empty
    dict if the file is missing, unreadable, or not valid JSON. Never raises.
    '''
    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def apply(module_name: str, module_globals: dict) -> None:
    '''
    Overrides a config module's existing globals with values from the matching
    section of `user_config.json`.

    - `module_name` is the module's `__name__` (e.g. "config.settings"); the last
      dotted part is the section name looked up in the JSON ("settings").
    - Only keys that ALREADY exist as globals in the module are applied, so the
      JSON can never introduce new names into the config namespace.
    - Environment / `.env` values (see SECRET_ENV_NAMES) are applied last and win.
    '''
    section_name = module_name.split(".")[-1]
    section = load_user_config().get(section_name, {})
    if not isinstance(section, dict):
        section = {}
    for key, value in {**section, **env_overrides(section_name)}.items():
        if key in module_globals:
            module_globals[key] = value
