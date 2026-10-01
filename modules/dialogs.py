'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Desktop dialogs (`alert`, `confirm`) and the keep-awake key press, as a thin shim over
pyautogui.

Why a shim: `import pyautogui` connects to the X display and imports tkinter the moment
it runs. A bare module-scope import therefore made the bot, the AI layer and every test
importing them fail on a headless box, on a Wayland desktop without ~/.Xauthority, and on
any Python built without tkinter (mouseinfo even calls sys.exit() there). This module is
the ONLY place allowed to import pyautogui, it does so lazily on the first dialog, and when
that fails it degrades to the "[Dialog suppressed ...]" log line that non-interactive runs
already use. On a working desktop the behaviour is identical to calling pyautogui directly.

`set_enabled(False)` is the explicit switch for runs nobody can click through (the control
panel's subprocess, `run_in_background`): every dialog becomes a log line and `press` does
nothing, whatever the display situation.
'''

from modules.helpers import logger, print_lg

_backend = None             # the imported pyautogui module, once it loaded successfully
_unavailable = False        # True after the import (or a call) failed for good
_enabled = True


def _import_pyautogui():
    '''Import pyautogui. Kept separate so tests can swap a fake backend in.'''
    import pyautogui
    return pyautogui


def _load_backend():
    '''The pyautogui module, or None when it cannot be used on this machine (warned once).'''
    global _backend, _unavailable
    if _backend is not None or _unavailable:
        return _backend
    try:
        _backend = _import_pyautogui()
        # The bot moves the mouse; pyautogui's default aborts the whole run the moment the
        # pointer touches a screen corner, which a user bumping the mouse triggers by accident.
        _backend.FAILSAFE = False
    # ImportError without the package; KeyError('DISPLAY') and Xlib errors with no display;
    # SystemExit from mouseinfo when tkinter is missing. All mean "no dialogs here".
    except (Exception, SystemExit) as e:
        _unavailable = True
        logger.warning("Desktop dialogs are unavailable on this machine (%s: %s). "
                       "Dialogs will be written to the log instead.", type(e).__name__, e)
    return _backend


def _suppressed(text: str, title: str, reason: str) -> None:
    '''Log the dialog the user would have seen, and return None like a dismissed dialog.'''
    print_lg(f'[Dialog suppressed, {reason}] {title}: {text}')
    return None


def set_enabled(enabled: bool) -> None:
    '''Turn desktop dialogs on or off. Off: every dialog is logged and `press` is a no-op.'''
    global _enabled
    _enabled = bool(enabled)


def alert(text: str = "", title: str = "", button: str = "OK", **kwargs) -> str | None:
    '''
    Show a one-button dialog and return the button text, like `pyautogui.alert`.
    Returns None when dialogs are disabled or unavailable; the message is logged instead.
    '''
    if not _enabled:
        return _suppressed(text, title, "non-interactive run")
    backend = _load_backend()
    if backend is None:
        return _suppressed(text, title, "no desktop display")
    try:
        return backend.alert(text, title, button, **kwargs)
    except Exception as e:
        logger.warning("Could not show a dialog (%s: %s).", type(e).__name__, e)
        return _suppressed(text, title, "dialog failed")


def confirm(text: str = "", title: str = "", buttons=("OK", "Cancel"), **kwargs) -> str | None:
    '''
    Show a multi-button dialog and return the chosen button text, like `pyautogui.confirm`.
    Returns None when dialogs are disabled or unavailable; the message is logged instead.
    '''
    if not _enabled:
        return _suppressed(text, title, "non-interactive run")
    backend = _load_backend()
    if backend is None:
        return _suppressed(text, title, "no desktop display")
    try:
        return backend.confirm(text, title, buttons, **kwargs)
    except Exception as e:
        logger.warning("Could not show a dialog (%s: %s).", type(e).__name__, e)
        return _suppressed(text, title, "dialog failed")


def press(key: str) -> None:
    '''Press one key (used to keep the screen awake). Silently does nothing without a desktop.'''
    if not _enabled:
        return
    backend = _load_backend()
    if backend is None:
        return
    try:
        backend.press(key)
    except Exception as e:
        logger.warning("Could not press %r (%s: %s).", key, type(e).__name__, e)


def reset() -> None:
    '''Forget the loaded backend and re-enable dialogs. For tests.'''
    global _backend, _unavailable, _enabled
    _backend = None
    _unavailable = False
    _enabled = True
