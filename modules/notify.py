'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Telegram notifications: the **run summary** when a run ends and a message when the bot dies
with an error. Lives in the bot, not the control panel, so a run started from a terminal
notifies exactly like one started from the panel.

Off until both `telegram_bot_token` and `telegram_chat_id` are set in `config/secrets.py`
(or the Account tab). A failed send is logged at warning level and never affects the
application in progress.
'''

from __future__ import annotations

import json
import urllib.error
import urllib.request

from modules.helpers import logger

SEND_MESSAGE_URL = "https://api.telegram.org/bot%s/sendMessage"
MAX_MESSAGE_LENGTH = 4096          # Telegram's limit per message
_half_configured_warned = False


def is_configured(token: str | None, chat_id: str | None) -> bool:
    '''True when both settings are filled in, i.e. the user opted in.'''
    return bool((token or "").strip()) and bool(str(chat_id or "").strip())


def send_message(text: str, token: str | None, chat_id: str | None, timeout: float = 10) -> bool:
    '''
    Send `text` to the Telegram chat. Returns True on success. Returns False, after one
    warning in the log, when notifications are not configured, the network fails, Telegram
    answers with an error, or anything else goes wrong: a notification must never stop a run.
    '''
    if not is_configured(token, chat_id):
        global _half_configured_warned
        if (token or "").strip() or str(chat_id or "").strip():
            # One of the two is filled in: the user meant to turn this on. Say so once, as a
            # warning, and stay off; never abort a run over a notification setting.
            if not _half_configured_warned:
                logger.warning("Telegram notifications are off: set BOTH telegram_bot_token and telegram_chat_id "
                               "in config/secrets.py (or the Account tab) to turn them on.")
                _half_configured_warned = True
        return False
    body = json.dumps({"chat_id": str(chat_id).strip(), "text": (text or "")[:MAX_MESSAGE_LENGTH],
                       "disable_web_page_preview": True}).encode("utf-8")
    request = urllib.request.Request(SEND_MESSAGE_URL % token.strip(), data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if 200 <= response.status < 300:
                return True
            logger.warning("Telegram did not accept the notification (HTTP %s).", response.status)
    except urllib.error.HTTPError as error:
        # The token is in the URL of this request; log the status and Telegram's own
        # description, never the URL.
        detail = ""
        try: detail = json.loads(error.read().decode("utf-8", "replace")).get("description", "")
        except Exception: pass
        logger.warning("Telegram rejected the notification (HTTP %s%s).", error.code, f": {detail}" if detail else "")
    except Exception as error:
        logger.warning("Could not send the Telegram notification (%s: %s).", type(error).__name__, error)
    return False
