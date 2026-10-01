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

# Which market this run applies in.
market = "internacional"            # "brasil" or "internacional" (case-sensitive)


## Brasil: salaries are MONTHLY, in reais.
br_currency = "BRL"                 # Currency code, Eg: "BRL"
br_desired_salary_monthly = 0       # Pretensão salarial mensal, Eg: 8000, 12000. 0 = use desired_salary (questions.py) as-is. No quotes
br_current_salary_monthly = 0       # Salário atual mensal, Eg: 6500. 0 = use current_ctc (questions.py) as-is. No quotes
br_search_location = "Brasil"       # Filled in LinkedIn's location box, Eg: "Brasil", "São Paulo, SP", "Remoto". "" = use search_location (search.py)
br_search_terms = []                # Eg: ["Desenvolvedor Python", "Engenheiro de Software"]. [] = use search_terms (search.py)


## Internacional: salaries are ANNUAL, in the currency you choose.
intl_currency = "USD"               # Currency code, Eg: "USD", "EUR", "GBP"
intl_desired_salary_annual = 0      # Expected annual salary, Eg: 90000. 0 = use desired_salary (questions.py). No quotes
intl_current_salary_annual = 0      # Current annual salary, Eg: 70000. 0 = use current_ctc (questions.py). No quotes
intl_search_location = ""           # Eg: "United States", "Portugal", "European Union". "" = use search_location (search.py)
intl_search_terms = []              # Eg: ["Software Engineer", "Backend Developer"]. [] = use search_terms (search.py)

############################################################################################################

# --- Load user settings saved by the local control panel (user_config.json).
# --- No-op if that file is absent: values fall back to the defaults above.
from config import _overrides as _o
_o.apply(__name__, globals())
############################################################################################################
