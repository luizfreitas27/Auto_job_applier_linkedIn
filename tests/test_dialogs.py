'''
Tests for modules/dialogs.py, the shim over pyautogui's desktop dialogs.

pyautogui opens an X display connection and imports tkinter the moment it is imported,
so a bare `import pyautogui` at module scope made the bot, the AI layer and every test
that imports them fail on a headless machine, a Wayland desktop without ~/.Xauthority,
or any Python without tkinter. The shim imports it lazily, on the first dialog, and when
that fails it degrades to the same "[Dialog suppressed ...]" log line that non-interactive
runs already use. On a desktop nothing changes.

License: MIT  (https://opensource.org/license/mit)
'''

import ast
import pathlib
import sys
import types

import pytest

import modules.dialogs as dialogs


ROOT = pathlib.Path(__file__).resolve().parent.parent


class FakePyautogui(types.SimpleNamespace):
    '''Records every dialog call and answers with a canned button.'''

    def __init__(self, answer="OK"):
        super().__init__(FAILSAFE=True, calls=[], answer=answer)

    def alert(self, text="", title="", button="OK", **kwargs):
        self.calls.append(("alert", text, title, button))
        return self.answer

    def confirm(self, text="", title="", buttons=("OK", "Cancel"), **kwargs):
        self.calls.append(("confirm", text, title, tuple(buttons)))
        return self.answer

    def press(self, key):
        self.calls.append(("press", key))


@pytest.fixture(autouse=True)
def fresh_shim():
    '''Every test starts with no backend loaded and dialogs enabled.'''
    dialogs.reset()
    yield
    dialogs.reset()


def messages(records):
    return [r.getMessage() for r in records]


# ------------------------------- import hygiene -----------------------------
def _module_level_pyautogui_imports(path: pathlib.Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in tree.body:                     # module scope only; nested imports are lazy
        if isinstance(node, ast.Import) and any(a.name == "pyautogui" for a in node.names):
            hits.append(node.lineno)
        if isinstance(node, ast.ImportFrom) and node.module == "pyautogui":
            hits.append(node.lineno)
        if isinstance(node, ast.Try):
            for inner in node.body:
                if isinstance(inner, (ast.Import, ast.ImportFrom)) and "pyautogui" in ast.dump(inner):
                    hits.append(inner.lineno)
    return hits


def test_nothing_imports_pyautogui_at_module_load():
    '''The whole point: importing the bot must never touch the display.'''
    offenders = {}
    for path in [ROOT / "runAiBot.py", ROOT / "app.py", *ROOT.glob("modules/**/*.py")]:
        if path.name == "dialogs.py":
            continue                            # the shim is the one place allowed to know about pyautogui
        lines = _module_level_pyautogui_imports(path)
        if lines:
            offenders[str(path.relative_to(ROOT))] = lines
    assert offenders == {}


def test_the_shim_itself_imports_pyautogui_lazily():
    assert _module_level_pyautogui_imports(ROOT / "modules" / "dialogs.py") == []


# ------------------------------- unavailable backend ------------------------
def test_alert_degrades_to_a_log_line_when_pyautogui_cannot_be_imported(monkeypatch, log_records):
    monkeypatch.setitem(sys.modules, "pyautogui", None)       # makes `import pyautogui` raise ImportError

    assert dialogs.alert("Please log in", "Login Required", "OK") is None
    assert dialogs.confirm("Continue?", "Check", ["Yes", "No"]) is None

    text = "\n".join(messages(log_records))
    assert "[Dialog suppressed" in text
    assert "Login Required: Please log in" in text
    assert "Check: Continue?" in text


def test_the_unavailable_warning_is_logged_once_not_per_dialog(monkeypatch, log_records):
    monkeypatch.setitem(sys.modules, "pyautogui", None)
    for _ in range(3):
        dialogs.alert("x", "T")
    warnings = [r for r in log_records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "pyautogui" in warnings[0].getMessage().lower() or "dialog" in warnings[0].getMessage().lower()


def test_a_sys_exit_from_the_import_is_survived(monkeypatch, log_records):
    '''mouseinfo (imported by pyautogui) calls sys.exit() when tkinter is missing.'''
    def exploding_import():
        raise SystemExit("NOTE: You must install tkinter on Linux to use MouseInfo.")
    monkeypatch.setattr(dialogs, "_import_pyautogui", exploding_import)

    assert dialogs.alert("x", "T") is None
    assert any("[Dialog suppressed" in m for m in messages(log_records))


def test_press_is_a_silent_no_op_without_a_backend(monkeypatch, log_records):
    monkeypatch.setitem(sys.modules, "pyautogui", None)
    dialogs.press("shiftright")                                 # must not raise
    assert not any("[Dialog suppressed" in m for m in messages(log_records))


# ------------------------------- available backend --------------------------
def test_dialogs_are_delegated_when_pyautogui_works(monkeypatch):
    fake = FakePyautogui(answer="Submit Application")
    monkeypatch.setattr(dialogs, "_import_pyautogui", lambda: fake)

    assert dialogs.alert("Missing resume", "Missing Resume", "OK") == "Submit Application"
    assert dialogs.confirm("Verify", "Confirm", ["Disable Pause", "Submit Application"]) == "Submit Application"
    dialogs.press("shiftright")

    assert fake.calls == [
        ("alert", "Missing resume", "Missing Resume", "OK"),
        ("confirm", "Verify", "Confirm", ("Disable Pause", "Submit Application")),
        ("press", "shiftright"),
    ]


def test_keyword_arguments_reach_the_backend(monkeypatch):
    fake = FakePyautogui()
    monkeypatch.setattr(dialogs, "_import_pyautogui", lambda: fake)
    dialogs.alert(text="t", title="T", button="Okay")
    assert fake.calls == [("alert", "t", "T", "Okay")]


def test_the_failsafe_corner_abort_is_turned_off(monkeypatch):
    '''The bot moves the mouse; pyautogui's default aborts the run if it reaches a corner.'''
    fake = FakePyautogui()
    monkeypatch.setattr(dialogs, "_import_pyautogui", lambda: fake)
    dialogs.alert("x", "T")
    assert fake.FAILSAFE is False


def test_a_backend_that_crashes_mid_dialog_degrades_instead_of_raising(monkeypatch, log_records):
    fake = FakePyautogui()
    def broken(*args, **kwargs):
        raise RuntimeError("no display name and no $DISPLAY environment variable")
    fake.alert = broken
    monkeypatch.setattr(dialogs, "_import_pyautogui", lambda: fake)

    assert dialogs.alert("x", "T") is None
    assert any("[Dialog suppressed" in m for m in messages(log_records))


# ------------------------------- explicit suppression -----------------------
def test_set_enabled_false_suppresses_even_with_a_working_backend(monkeypatch, log_records):
    '''Non-interactive runs (panel subprocess, run_in_background) must never block on a modal.'''
    fake = FakePyautogui()
    monkeypatch.setattr(dialogs, "_import_pyautogui", lambda: fake)
    dialogs.set_enabled(False)

    assert dialogs.alert("x", "Title") is None
    assert dialogs.confirm("y", "Title2", ["a", "b"]) is None
    dialogs.press("shiftright")

    assert fake.calls == []
    text = "\n".join(messages(log_records))
    assert "non-interactive" in text
    assert "Title: x" in text and "Title2: y" in text
