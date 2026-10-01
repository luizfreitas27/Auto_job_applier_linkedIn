# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Selenium bot (`runAiBot.py`) that applies to LinkedIn Easy Apply jobs from the user's own
machine, plus a local Flask "control panel" (`app.py`) that edits settings, starts/stops the
bot and shows the applied-jobs history. Everything is local: credentials live in
`config/secrets.py` or `user_config.json`, both on disk only. This is a fork; upstream is
`GodsScion/Auto_job_applier_linkedIn`, and upstream accepts PRs only on its
`community-version` branch.

## Commands

```bash
./run_tests.sh                 # creates .venv, installs deps, runs pytest (extra args pass through)
./run_tests.sh -k helpers      # subset by keyword
python -m pytest tests/test_helpers.py::test_name   # one test (needs deps installed, pytest.ini sets pythonpath=.)
python app.py                  # control panel on 127.0.0.1:5000 (or a free port); PANEL_OPEN_BROWSER=1 opens the browser
python runAiBot.py             # the bot directly (opens Chrome at import time)
./start.sh                     # one-click launcher: venv + pip + app.py
```

`requirements.txt` is fully pinned; `pip install -r requirements.txt -r requirements-dev.txt`
for a manual setup. There is no linter configured.

The suite runs on any machine, including one without a display or `tkinter`, and in GitHub
Actions (`.github/workflows/tests.yml`). The `live` marker (one OpenAI smoke test) runs only
when `OPENAI_API_KEY` is set.

## Architecture

### Import-time side effects (the main trap)

- `modules/open_chrome.py` **launches Chrome when imported**. `runAiBot.py` does
  `from modules.open_chrome import *` and uses `driver`, `wait`, `actions` as module globals.
  With `auto_manage_driver = True` it uses SeleniumBase UC Mode (`seleniumbase.Driver(uc=True,
  ...)`, imported lazily, in `create_chrome_session()`; ADR 0001), which returns a plain Selenium WebDriver; `False` is plain
  Selenium via Selenium Manager with no anti-detection. `uc_driver_kwargs()` and
  `plain_selenium_options()` are the testable seams. `seleniumbase` pins `selenium` and
  `pytest` exactly (pytest 9 on Python 3.11+); bump them together, and note pytest 9 attaches
  its capture handlers to non-propagating loggers during a test.
  Tests stub it with `sys.modules["modules.open_chrome"] = types.ModuleType(...)` before
  importing `runAiBot` (see `tests/test_runaibot_fixes.py`).
- `modules/helpers.py` calls `setup_logging()` at import.
- `modules/dialogs.py` is the **only** module allowed to import `pyautogui`, and it does so
  lazily on the first dialog. `pyautogui` opens the X display and imports `tkinter` at import
  time, so a bare import anywhere else breaks headless machines and the test suite
  (`tests/test_dialogs.py` enforces this). Call `dialogs.alert/confirm/press`; they degrade
  to a log line when there is no desktop or after `dialogs.set_enabled(False)`.
- Every `config/*.py` ends with `_overrides.apply(__name__, globals())`, which overlays
  `user_config.json` onto the module's globals.
- `app.py` builds `DEFAULTS` at import by temporarily disabling the override loader and
  reloading the config modules.

### Configuration layering

Four layers, lowest precedence first:

1. `config/{personals,questions,search,secrets,settings}.py`: shipped defaults, tracked in
   git, documented inline. `runAiBot.py` star-imports all five, so every setting is a bare
   module-level global there.
2. `user_config.json` (gitignored): written **only** by `app.py`. `config/_overrides.py`
   applies it per section (section name = config module name) and only for keys that already
   exist in the module, so JSON can never introduce a new name.
3. Environment / `.env` (gitignored), for the five secrets in `_overrides.SECRET_ENV_NAMES`
   only; a real variable beats `.env`. Applied last by `_overrides.apply`. The panel reports
   them as `_locked` in `GET /api/config`, disables the fields and refuses to save them.
4. `config_schema.py`: the single source of truth for what the control panel renders.
   Settings not in the schema are still usable by editing the `.py` file.

Adding a setting therefore means: the `config/*.py` file (comment + example values), a check
in `modules/validator.py` (`validate_config()` runs at bot start and raises on bad types), and
optionally an entry in `config_schema.py`. For settings that may be missing from an older
user's config, `runAiBot.py` reads them defensively with `globals().get("name", default)`.

### Control panel (`app.py` + `templates/`)

- Runs the bot as a subprocess of `runAiBot.py`, stdout to `.bot_run.log`, PID in
  `.bot_run.pid`; the UI polls `/api/logs?offset=` and `/api/status`.
- Security rules that must not be loosened: binds to `127.0.0.1` only, `debug=False`, **no
  CORS headers** (flask-cors was removed on purpose), a `before_request` hook that rejects
  non-loopback `Host` headers and any POST/PUT/DELETE without `X-Requested-With: control-panel`, and
  `_mask_secrets()` which replaces every schema `password`-type value with `SECRET_MASK` in
  responses. Sending the mask back on save means "keep the stored value". Templates hardcode
  the same header and mask string.
- `runAiBot.py` detects a non-interactive run (`run_in_background` or stdout not a TTY, which
  is the case under the panel) and calls `dialogs.set_enabled(False)`, because desktop
  dialogs are blocking Tk modals nobody can click there.
- Review queue: `GET/DELETE /api/answers?state=` and `POST/DELETE /api/answers/<id>` over a
  module-level `AnswerMemory`, rendered by the Answers tab (`buildAnswersPanel`/`loadAnswers`
  in `control_panel.html`). The memory reloads itself when the file's mtime/size changes, so
  the bot process and the panel share `answers_memory.json` without clobbering each other.
- Schedule windows: `modules/schedule.py` is pure (parse/validate windows, `window_is_active`,
  edge-triggered `decide`); `app.py` owns the clock and a daemon thread calling
  `scheduler_tick()` every `SCHEDULER_INTERVAL_SECONDS`, which uses the same
  `start_bot()`/`stop_bot()` as the Run buttons. `user_config.json` is written only through
  `_write_user_config()` (atomic replace) under `_user_config_lock`. Windows live in the `schedule` section of `user_config.json` via `/api/schedule`,
  outside the config schema. The thread starts only under `__main__`, never in tests.
- `modules/updater.py`: compares `VERSION` with the upstream raw file and offers
  `git pull --ff-only`; it refuses unless `origin` points at the upstream repo, so in this
  fork the update button does nothing.

### Bot flow (`runAiBot.py`)

`main()` → `validate_config()` → login (`login_LN`, credentials optional, falls back to the
browser profile or a manual-login dialog) → `run()` → `apply_to_jobs(search_terms)` per
search term: `apply_filters()`, iterate virtualised job cards (re-queried each loop because
LinkedIn re-renders them), `get_job_main_details` / `check_blacklist` /
`get_job_description` decide skips, then the Easy Apply modal loop: `answer_questions()` on
each page, resume upload, Review, submit (or `StoppedBeforeSubmit` when
`stop_before_submit` is on). Applied and failed jobs are appended to the CSVs in
`all excels/`, screenshots to `logs/screenshots/`.

LinkedIn selectors are fragile and intentionally centralised: `easy_apply_locators` is an
ordered fallback list, login locators are module constants near the top. `tests/fixtures/*.html`
are captured LinkedIn DOM snapshots and `tests/test_selectors_groundtruth.py` asserts the
locators used in code still match them; update both together when LinkedIn changes.

### Answer memory (`modules/answers_memory.py`)

`answers_memory.json` at the project root (gitignored) holds every answer given to an
unrecognised question: normalised label + control kind → answer, source (`ai`/`user`), state
(`pending`/`approved`), uses, last job link. `runAiBot.answer_from_memory_or_ai()` is the single
fallback the form branches call after the configured-answer heuristics fail: sensitive check
(`is_sensitive_question`, whole-word on `sensitive_terms`) → memory lookup (exact, then
`difflib` ≥ 0.92 within the same kind, logged) → AI, whose answer is remembered as pending.
Select and radio branches call `option_from_memory_or_ai()` only when there is no configured
answer (`not answer`): memory text snapped to this form's options via
`match_answer_to_option`, then the AI shown the non-placeholder options, accepted only
verbatim. Both fallbacks share `ask_ai()`. Checkboxes tick only from an `approved` entry; an
unrecognised unticked box is remembered as pending with source `form`. `pause_for_help()` is the
"Help Needed" pause: it snapshots the form with `read_form_state()` before and after the
dialog and `capture_manual_answers()` remembers what the user filled in as approved (source
`user`). Form locators and title readers (`form_question_xpath`, `select_title`,
`radio_title`, `text_title`, `textarea_title`, `checkbox_key`) are shared by both. Every public method reloads the file if another process changed it, and
`record_use` re-finds its entry by id, so entries are never trusted as current. The module
itself knows nothing about sensitivity; the bot gates before calling it. Tests wire a temp-file `AnswerMemory` in
with `monkeypatch.setattr(bot, "answers_memory", ...)`.

### AI layer (`modules/ai/`)

Provider-agnostic via LangChain `init_chat_model` + a small LangGraph pipeline. Only two
providers exist internally: `"gemini"` → `google_genai`, everything else (openai, deepseek,
ollama, lm studio, vllm) → `openai` with `llm_api_url` as `base_url`. `extract_skills` uses
structured output and falls back to plain JSON parsing. Prompts live in `prompts.py`.
`answer_question(..., options=[...], question_type="single_select")` returns the option the
model named exactly (case/quotes tolerated) or `""`; never a paraphrase. The applicant text
the AI sees is `profile.build_candidate_profile()`, assembled from the config modules
(never phone, street, zip, email, citizenship status or current salary) plus
`user_information_all`.

### Notifications (`modules/notify.py`)

`send_message(text, token, chat_id)` posts to the Telegram Bot API with the standard
library; it is a no-op when either setting is blank and returns False after one warning on any
failure, never raising. `runAiBot.main()` calls `notify_run_end()` (the run summary) in its
`finally` and `notify_error()` from the fatal handlers; both read the live secrets.

### Logging

One stdlib logger, `auto_job_applier`, configured in `modules/helpers.py` (bare message to
stdout, timestamped rotating `logs/log.txt`). `print_lg(...)` is a compatibility shim over it
and is used at ~130 call sites; new code should call `logger.warning/error` directly. The
logger does **not** propagate to root, so pytest's `caplog` sees nothing; use the
`log_records` fixture from `tests/conftest.py`.

## Conventions

- From `CONTRIBUTING.md`: functions are snake_case with a `'''docstring'''` and full type
  hints on parameters and return; local variables are camelCase, globals and config variables
  snake_case; every config variable gets a comment with valid-value examples and a validator.
- Comments starting with `ponytail:` mark a known compromise and its ceiling; keep the
  convention when adding one.
- Contributors may credit themselves with `##> ------ Name : id - change ------` / `##<`
  blocks; they are optional.
- `VERSION` holds a dotted date-like version string (`26.01.20.5.08`) that the updater parses
  with `_VERSION_RE`; keep that shape.

## Agent skills

### Issue tracker

Specs and tickets are GitHub Issues on this fork (`luizfreitas27/Auto_job_applier_linkedIn`), managed with `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default triage labels, unchanged: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` (glossary) and `docs/adr/` at the repo root. Read them before exploring and use their vocabulary. See `docs/agents/domain.md`.
