# `config/markets.py` — Brazil and abroad

A **market** is the set of values that differ between applying in Brazil and applying abroad:
currency, desired and current salary, search location and search terms. Two markets ship,
`brasil` and `internacional`. Pick one with `market` before a run (or in the **Markets** tab of
the control panel); the whole run uses it.

| Setting | What it is |
|---|---|
| `market` | `"brasil"` or `"internacional"` |
| `br_currency` | Currency code for Brazil, normally `"BRL"` |
| `br_desired_salary_monthly` | Pretensão salarial **mensal**, in reais, Eg: `8000`. `0` = use `desired_salary` from `questions.py` as-is |
| `br_current_salary_monthly` | Salário atual mensal. `0` = use `current_ctc` as-is |
| `br_search_location` | Typed into LinkedIn's location box, Eg: `"Brasil"`, `"São Paulo, SP"`, `"Remoto"`. `""` = use `search_location` |
| `br_search_terms` | Eg: `["Desenvolvedor Python", "Engenheiro de Software"]`. `[]` = use `search_terms` |
| `intl_currency` | Currency your international salaries are in, Eg: `"USD"`, `"EUR"` |
| `intl_desired_salary_annual` | Expected **annual** salary in that currency, Eg: `90000`. `0` = use `desired_salary` |
| `intl_current_salary_annual` | Current annual salary. `0` = use `current_ctc` |
| `intl_search_location` | Eg: `"United States"`, `"Portugal"`. `""` = use `search_location` |
| `intl_search_terms` | Eg: `["Software Engineer"]`. `[]` = use `search_terms` |

## How salaries are answered

Each market carries its salary both monthly and annually. A question that names a period
("mensal", "anual", "monthly", "per year") gets that figure; a question that names none gets the
market's own period: monthly in Brazil ("Pretensão salarial" → `8000`), annual abroad
("Expected salary" → `90000`). Salary questions are **sensitive**: they are answered only from
these settings, never by the AI or the answer memory.

## Portuguese forms

The tool recognises company form questions in Portuguese alongside English: salário, pretensão,
experiência, telefone, celular, cidade, estado, CEP, país, nome, sobrenome, aviso prévio, site,
visto, autorização de trabalho, cidadania, gênero, deficiência/PCD, and attestations such as
"declaro" and "concordo". A configured "Yes"/"No"/"Decline" selects "Sim"/"Não"/"Prefiro não"
options, respecting polarity.

## Keep LinkedIn's interface in English

Whatever the market, the **LinkedIn interface language** of your account must stay English. The
tool finds LinkedIn's own buttons ("Next", "Review", "Submit application", "Sign in") by their
English text. Only the company's questions inside the form may be in Portuguese. Change it at
LinkedIn → Settings → Language, if needed.

---

[← Back to docs index](README.md) · [Configuration overview](configuration.md)
