'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Markets: the values that differ between applying in Brazil and abroad. Pick one with `market`
before a run; the whole run uses it. A blank value falls back to the general setting of the same
meaning (desired_salary / current_ctc in questions.py, search_terms / search_location in
search.py), so an existing configuration keeps working unchanged.

NOTE: keep your LinkedIn INTERFACE in English whatever the market. The tool finds LinkedIn's own
buttons ("Next", "Review", "Submit application") by their English text; only the company's form
questions may be in Portuguese, and those the tool understands.
'''

###################################################### CONFIGURE YOUR TOOLS HERE ######################################################

# Which market this run applies in. Changing it takes effect on the next run.
market = "internacional"            # "brasil" or "internacional", lowercase, in quotes


## Brasil: salaries are MONTHLY, in reais.
# Currency code the Brazilian salaries below are in. Shown to the AI with the salary.
br_currency = "BRL"                 # Eg: "BRL". In quotes
# Pretensão salarial MENSAL. Typed into salary questions when the market is brasil; "anual" questions get it x12.
br_desired_salary_monthly = 0       # Eg: 8000, 12000. 0 = use desired_salary (questions.py, annual) divided by 12. No quotes
# Salário atual MENSAL, for "salário atual" questions.
br_current_salary_monthly = 0       # Eg: 6500. 0 = use current_ctc (questions.py, annual) divided by 12. No quotes
# What to type into LinkedIn's "City, state, or zip code" search box when the market is brasil.
br_search_location = "Brasil"       # Eg: "Brasil", "São Paulo, SP", "Remoto". "" = use search_location (search.py)
# Job titles to search for when the market is brasil, one search per title.
br_search_terms = []                # Eg: ["Desenvolvedor Python", "Engenheiro de Software"]. [] = use search_terms (search.py)


## Internacional: salaries are ANNUAL, in the currency you choose.
# Currency code the international salaries below are in. Shown to the AI with the salary.
intl_currency = "USD"               # Eg: "USD", "EUR", "GBP". In quotes
# Expected ANNUAL salary. Typed into salary questions when the market is internacional; "monthly" questions get it /12.
intl_desired_salary_annual = 0      # Eg: 90000. 0 = use desired_salary (questions.py) as-is. No quotes
# Current ANNUAL salary, for "current compensation" questions.
intl_current_salary_annual = 0      # Eg: 70000. 0 = use current_ctc (questions.py) as-is. No quotes
# What to type into LinkedIn's "City, state, or zip code" search box when the market is internacional.
intl_search_location = ""           # Eg: "United States", "Portugal", "European Union". "" = use search_location (search.py)
# Job titles to search for when the market is internacional, one search per title.
intl_search_terms = []              # Eg: ["Software Engineer", "Backend Developer"]. [] = use search_terms (search.py)

############################################################################################################

# --- Load user settings saved by the local control panel (user_config.json).
# --- No-op if that file is absent: values fall back to the defaults above.
from config import _overrides as _o
_o.apply(__name__, globals())
############################################################################################################
