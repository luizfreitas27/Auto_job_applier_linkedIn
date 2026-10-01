'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit
            
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Support me: https://github.com/sponsors/GodsScion

version:    26.01.20.5.08

Opens the Chrome session the bot drives. IMPORTED FOR ITS SIDE EFFECT: importing this module
launches the browser and binds `driver`, `wait`, `actions` and `options` as module globals,
which runAiBot.py star-imports.

Two stacks (see docs/adr/0001):
  * `auto_manage_driver = True` (default): SeleniumBase in UC Mode. It resolves and patches
    a matching chromedriver itself, on every platform, and returns a plain Selenium
    WebDriver, so nothing downstream changes.
  * `auto_manage_driver = False`: plain Selenium through Selenium Manager, with no
    anti-detection at all. For people who manage the driver themselves.
'''

from modules.helpers import get_default_temp_profile, make_directories
from config.settings import run_in_background, auto_manage_driver, disable_extensions, safe_mode, file_name, failed_file_name, logs_folder_path, generated_resume_path
from config.questions import default_resume_path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from modules.helpers import find_default_profile_directory, critical_error_log, logger, print_lg
from selenium.common.exceptions import SessionNotCreatedException


def choose_profile_directory(isRetry: bool) -> str:
    '''
    The Chrome user-data directory for this session: the user's real Chrome profile when
    `safe_mode` is off and one was found, else the bot's own throwaway profile. A retry
    after a failed launch always uses the throwaway profile.
    '''
    profileDir = find_default_profile_directory()
    if isRetry:
        print_lg("Will login with a guest profile, browsing history will not be saved in the browser!")
    elif profileDir and not safe_mode:
        return profileDir
    else:
        print_lg("Logging in with a guest profile, Web history will not be saved!")
    return get_default_temp_profile()


def uc_driver_kwargs(profile_dir: str) -> dict:
    '''
    The arguments for `seleniumbase.Driver` in UC Mode. Kept as data so the launch can be
    tested without a browser. `headless2` is Chrome's new headless mode, the only one UC Mode
    supports; the legacy `--headless` is trivially detectable.
    '''
    kwargs = {"uc": True, "user_data_dir": profile_dir, "headless2": bool(run_in_background)}
    if disable_extensions:
        kwargs["chromium_arg"] = "--disable-extensions"
    return kwargs


def plain_selenium_options(profile_dir: str) -> Options:
    '''Chrome options for the plain-Selenium fallback (`auto_manage_driver = False`).'''
    options = Options()
    if run_in_background: options.add_argument("--headless=new")
    if disable_extensions:  options.add_argument("--disable-extensions")
    options.add_argument(f"--user-data-dir={profile_dir}")
    return options


def createChromeSession(isRetry: bool = False):
    '''
    Launch Chrome and return (options, driver, actions, wait). `options` is None on the UC
    path: SeleniumBase builds its own and does not hand them back.
    '''
    make_directories([file_name,failed_file_name,logs_folder_path+"/screenshots",default_resume_path,generated_resume_path+"/temp"])
    print_lg("IF YOU HAVE MORE THAN 10 TABS OPENED, PLEASE CLOSE OR BOOKMARK THEM! Or it's highly likely that application will just open browser and not do anything!")
    profileDir = choose_profile_directory(isRetry)
    options = None
    if auto_manage_driver:
        if run_in_background:
            logger.warning("run_in_background is True: headless Chrome is easier for LinkedIn to detect, so the risk of your session being flagged or blocked is higher. Prefer a visible window when you can.")
        print_lg("Setting up the matching Chrome driver... This may take a moment the first time.")
        import seleniumbase                      # lazy: importing it is slow and only needed on this path
        driver = seleniumbase.Driver(**uc_driver_kwargs(profileDir))
    else:
        # ponytail: warning only, no stealth patching here. Set auto_manage_driver = True if LinkedIn starts blocking.
        logger.warning("auto_manage_driver is False, so we're using plain Selenium with NO anti-detection at all. LinkedIn may flag or block this session, set auto_manage_driver = True in config/settings.py if that happens.")
        options = plain_selenium_options(profileDir)
        driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    wait = WebDriverWait(driver, 5)
    actions = ActionChains(driver)
    return options, driver, actions, wait

try:
    options, driver, actions, wait = None, None, None, None
    options, driver, actions, wait = createChromeSession()
except SessionNotCreatedException as e:
    # Recoverable: the guest-profile retry below usually succeeds, so this is not an ERROR.
    logger.warning("Failed to create Chrome Session, retrying with guest profile", exc_info=e)
    options, driver, actions, wait = createChromeSession(True)
except Exception as e:
    msg = 'Seems like Google Chrome is out dated. Update browser and try again! \n\n\nIf issue persists, try Safe Mode. Set, safe_mode = True in config.py \n\nPlease check GitHub discussions/support for solutions https://github.com/GodsScion/Auto_job_applier_linkedIn \n                                   OR \nReach out in discord ( https://discord.gg/fFp7uUzWCY )'
    if isinstance(e,TimeoutError): msg = "Couldn't download Chrome-driver. Set auto_manage_driver = False in config!"
    logger.error(msg)
    critical_error_log("In Opening Chrome", e)
    from modules.dialogs import alert
    alert(msg, "Error in opening chrome")
    try: driver.quit()
    except (NameError, AttributeError): exit()
