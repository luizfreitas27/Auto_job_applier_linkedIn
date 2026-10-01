---
status: accepted
---

# SeleniumBase UC Mode replaces undetected-chromedriver

`undetected-chromedriver` is unmaintained since early 2024 and ships no Apple Silicon
driver, which `modules/open_chrome.py` papers over with a Selenium Manager shim. Its
author's successor, `nodriver`, is async and speaks CDP directly, so adopting it means
rewriting every Selenium call in `runAiBot.py` and `clickers_and_finders.py` and throwing
away the selector ground-truth tests. We chose **SeleniumBase in UC Mode** instead: it is
actively maintained, applies the same anti-detection patch, resolves the driver itself, and
keeps the Selenium WebDriver API, so the change stays inside `open_chrome.py`.

## Considered options

- **nodriver**: best stealth, but a full rewrite of the bot and loss of the Selenium test
  fixtures. Revisit only if LinkedIn starts detecting WebDriver itself.
- **Playwright + stealth**: same rewrite cost, different ecosystem.
- **Plain Selenium with Selenium Manager**: no maintenance burden, but no anti-detection at
  all; already available as the `auto_manage_driver = False` fallback.
