# `config/secrets.py` — login, AI and notifications

Your LinkedIn credentials, the optional AI setup and the optional Telegram notifications. Also
available in the **Account** tab of the control panel.

## Keeping secrets out of the config files: `.env`

The password, the AI key and the Telegram token can live in a `.env` file at the project root
instead of `config/secrets.py` or the control panel. Copy `.env.example` to `.env` and fill in
what you use; `.env` is ignored by git, `config/secrets.py` is **not**, so a password typed
there is one commit away from being published.

| Variable | Setting it replaces |
|---|---|
| `LINKEDIN_USERNAME` | `username` |
| `LINKEDIN_PASSWORD` | `password` |
| `LLM_API_KEY` | `llm_api_key` |
| `TELEGRAM_BOT_TOKEN` | `telegram_bot_token` |
| `TELEGRAM_CHAT_ID` | `telegram_chat_id` |

Precedence, highest first: a real environment variable, then `.env`, then what the control
panel saved (`user_config.json`), then the defaults in `config/secrets.py`. A field that comes
from the environment is shown disabled in the control panel with a note saying so; the password
and the tokens are masked there, the username and chat id are shown. The in-app updater never
copies these values into `user_config.json`. Only these five settings have an environment name;
everything else stays in the config files and the panel.

## LinkedIn login (optional)

| Setting | What it is |
|---|---|
| `username` | Your LinkedIn username/email |
| `password` | Your LinkedIn password |

**Both are optional.** If you leave them at their defaults, the tool logs in using the
browser's saved profile, or asks you to log in manually in the Chrome window it opens.

Nothing here leaves your computer. `config/secrets.py` and `user_config.json` stay on disk.

The control panel never shows a saved password or API key again: once stored, the field
displays `********`. Type a new value to replace it, or clear the field to remove it. The
panel also answers only to `127.0.0.1`/`localhost` and refuses requests that other web pages
open in your browser could send to it, so keep it that way (no CORS, no `0.0.0.0`).

## AI setup (optional)

AI is **off by default**. When it is on, it helps answer free-text application questions and
can read the required skills out of a job description. It needs either a paid API key or a
local model server, which is why it stays off.

The AI layer is provider-agnostic — it is built on **LangChain + LangGraph**, so one set of
options covers every provider.

| Setting | What it is |
|---|---|
| `use_AI` | Master switch. `True` or `False` |
| `ai_provider` | `"openai"`, `"gemini"`, or `"deepseek"`. Use `"openai"` for OpenAI **or any OpenAI-compatible server**, including local ones like [Ollama](https://ollama.com/), [LM Studio](https://lmstudio.ai/) and vLLM. `"deepseek"` also behaves like `"openai"`. `"gemini"` uses your Google API key and ignores `llm_api_url` |
| `llm_model` | The model name your provider offers. OpenAI: `"gpt-5.6-sol"`, `"gpt-5.5"`, `"gpt-4o-mini"`. Local: `"llama-3.2-3b-instruct"`, `"qwen2.5:latest"`. Gemini: `"gemini-2.5-flash"`, `"gemini-2.5-pro"` |
| `llm_api_key` | Your provider's API key. For local servers any placeholder works — leave it as `"not-needed"` |
| `llm_api_url` | Base URL of the server. Used by the `"openai"` provider family only. OpenAI: `"https://api.openai.com/v1/"`. LM Studio: `"http://localhost:1234/v1/"`. Ollama: `"http://localhost:11434/v1/"`. DeepSeek: `"https://api.deepseek.com/v1"` |
| `llm_temperature` | Sampling temperature. Leave as `None` to use the model's own default — **some newer models only allow their default**. Set a number like `0` or `0.3` to override |

What the AI actually uses to answer questions comes from the candidate profile built from
your settings plus `user_information_all` in
[`config/questions.py`](config-questions.md#experience-and-profile).

## Telegram notifications (optional)

Get a Telegram message with the **run summary** (applied, external links, failed, skipped,
pending answers) when a run ends, and right away if the tool stops because of an error. Works
the same whether you started the tool from the control panel or a terminal.

| Setting | What it is |
|---|---|
| `telegram_bot_token` | The token @BotFather gives you when you create a bot (`/newbot`). Treated like a password in the control panel |
| `telegram_chat_id` | Your chat id. Send your new bot any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the `"chat":{"id": ...}` number |

Both empty (the default) means off. With only one of them set, notifications stay off and the
log says so once. A failed send is written to the log and never interrupts an application.

To be told when an AI API connection fails, set `showAiErrorAlerts = True` in
[`config/settings.py`](config-settings.md).

---

[← Back to docs index](README.md) · [Configuration overview](configuration.md)
