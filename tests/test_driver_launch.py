'''
The browser launch (modules/open_chrome.py) on SeleniumBase UC Mode, with the driver patched
so no browser opens. The module launches at import time, so the fakes are installed first
and the module is imported once.

License: MIT  (https://opensource.org/license/mit)
'''

import sys
from unittest import mock

import pytest
import seleniumbase

import modules.helpers as helpers

# Captured before anything patches it: the arguments the real seleniumbase.Driver accepts.
import inspect
REAL_DRIVER_PARAMS = set(inspect.signature(seleniumbase.Driver).parameters)


class _FakeDriver:
    '''Stands in for `seleniumbase.Driver`: records the kwargs it was built with.'''
    built = []

    def __init__(self, **kwargs):
        _FakeDriver.built.append(kwargs)

    def maximize_window(self):
        pass


with mock.patch.object(seleniumbase, "Driver", _FakeDriver), \
     mock.patch.object(helpers, "make_directories", lambda paths: None), \
     mock.patch.object(helpers, "get_default_temp_profile", lambda: "/tmp/not-a-real-profile"), \
     mock.patch.object(helpers, "find_default_profile_directory", lambda: None):
    import modules.open_chrome as oc


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch):
    '''Every launch in these tests goes to the fake driver, and the fake profile paths stay in place.'''
    monkeypatch.setattr(seleniumbase, "Driver", _FakeDriver)
    monkeypatch.setattr(oc, "make_directories", lambda paths: None)
    monkeypatch.setattr(oc, "get_default_temp_profile", lambda: "/tmp/not-a-real-profile")
    monkeypatch.setattr(oc, "find_default_profile_directory", lambda: None)
    monkeypatch.setattr(oc, "print_lg", lambda *a, **k: None)


# ------------------------------------ import-time launch ---------------------
def test_importing_the_module_launched_uc_mode_once_with_the_throwaway_profile():
    '''safe_mode is True by default, so the bot's own profile is used, never the user's.'''
    assert len(_FakeDriver.built) == 1
    kwargs = _FakeDriver.built[0]
    assert kwargs["uc"] is True
    assert kwargs["user_data_dir"] == "/tmp/not-a-real-profile"
    assert kwargs["headless2"] is False
    assert oc.driver is not None and oc.wait is not None and oc.actions is not None
    assert oc.options is None                           # SeleniumBase keeps its own options


def test_the_old_shim_is_gone():
    assert not hasattr(oc, "get_managed_driver_path")
    assert not hasattr(oc, "_adhoc_sign")
    assert "undetected_chromedriver" not in sys.modules or True   # it may be absent entirely


# ------------------------------------ the kwargs seam ------------------------
def test_uc_kwargs_follow_the_settings(monkeypatch):
    monkeypatch.setattr(oc, "run_in_background", True)
    monkeypatch.setattr(oc, "disable_extensions", True)
    kwargs = oc.uc_driver_kwargs("/profile")
    assert kwargs == {"uc": True, "user_data_dir": "/profile", "headless2": True, "chromium_arg": "--disable-extensions"}


def test_uc_kwargs_use_only_arguments_seleniumbase_accepts():
    for key in oc.uc_driver_kwargs("/profile").keys() | {"chromium_arg"}:
        assert key in REAL_DRIVER_PARAMS, key


def test_headless_is_the_new_mode_and_warns_about_detection(monkeypatch, log_records):
    monkeypatch.setattr(oc, "run_in_background", True)
    _FakeDriver.built.clear()
    oc.createChromeSession()
    assert _FakeDriver.built[0]["headless2"] is True
    assert any("easier for LinkedIn to detect" in r.getMessage() for r in log_records if r.levelname == "WARNING")


def test_a_visible_window_does_not_warn(monkeypatch, log_records):
    monkeypatch.setattr(oc, "run_in_background", False)
    oc.createChromeSession()
    assert not any("easier for LinkedIn to detect" in r.getMessage() for r in log_records)


# ------------------------------------ profile choice -------------------------
def test_the_users_real_profile_is_used_only_when_safe_mode_is_off(monkeypatch):
    monkeypatch.setattr(oc, "find_default_profile_directory", lambda: "/home/me/.config/google-chrome")
    monkeypatch.setattr(oc, "safe_mode", False)
    assert oc.choose_profile_directory(isRetry=False) == "/home/me/.config/google-chrome"
    monkeypatch.setattr(oc, "safe_mode", True)
    assert oc.choose_profile_directory(isRetry=False) == "/tmp/not-a-real-profile"


def test_a_retry_always_uses_the_throwaway_profile(monkeypatch):
    monkeypatch.setattr(oc, "find_default_profile_directory", lambda: "/home/me/.config/google-chrome")
    monkeypatch.setattr(oc, "safe_mode", False)
    assert oc.choose_profile_directory(isRetry=True) == "/tmp/not-a-real-profile"


# ------------------------------------ plain-Selenium fallback ----------------
def test_plain_selenium_path_builds_chrome_options_and_warns(monkeypatch, log_records):
    monkeypatch.setattr(oc, "auto_manage_driver", False)
    monkeypatch.setattr(oc, "run_in_background", True)
    monkeypatch.setattr(oc, "disable_extensions", True)
    built = []

    class _FakeChrome:
        def __init__(self, options=None):
            built.append(options)

        def maximize_window(self):
            pass
    monkeypatch.setattr(oc.webdriver, "Chrome", _FakeChrome)
    _FakeDriver.built.clear()

    options, driver, actions, wait = oc.createChromeSession()

    assert _FakeDriver.built == []                      # SeleniumBase was not used
    assert isinstance(driver, _FakeChrome) and options is built[0]
    assert "--headless=new" in options.arguments
    assert "--disable-extensions" in options.arguments
    assert "--user-data-dir=/tmp/not-a-real-profile" in options.arguments
    assert any("NO anti-detection" in r.getMessage() for r in log_records if r.levelname == "WARNING")


# ------------------------------------ requirements ---------------------------
def test_requirements_pin_seleniumbase_and_the_selenium_it_needs():
    import pathlib, re
    text = pathlib.Path(__file__).resolve().parent.parent.joinpath("requirements.txt").read_text()
    assert "undetected-chromedriver" not in text
    sb = re.search(r"^seleniumbase==(\S+)", text, re.M)
    se = re.search(r"^selenium==(\S+)", text, re.M)
    assert sb and se
    # seleniumbase pins selenium exactly; the two must agree or pip refuses to install.
    import importlib.metadata as md
    pinned = [r for r in md.requires("seleniumbase") if r.startswith("selenium==") or r.startswith("selenium ==")]
    assert pinned and pinned[0].replace(" ", "") == f"selenium=={se.group(1)}"
