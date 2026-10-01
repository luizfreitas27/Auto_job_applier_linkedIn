'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

The **market** a run applies in: the currency, salaries, search location and search terms that
differ between Brazil and abroad. `resolve_market` turns the flat settings in config/markets.py
(plus the general settings they fall back to) into one `Market` the bot and the AI profile read.
'''

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

MARKETS = ("brasil", "internacional")


@dataclass(frozen=True)
class Market:
    '''One market's values, salaries always carried both ways so a question may ask either.'''
    name: str
    currency: str
    salary_period: str                  # "monthly" (brasil) or "annual" (internacional): how the user entered it
    desired_salary_annual: float
    desired_salary_monthly: float
    current_salary_annual: float
    current_salary_monthly: float
    search_location: str
    search_terms: tuple[str, ...]

    @property
    def desired_salary_as_entered(self) -> float:
        '''The desired salary in the period the user typed it in, for the AI profile.'''
        return self.desired_salary_monthly if self.salary_period == "monthly" else self.desired_salary_annual

    @property
    def current_salary_as_entered(self) -> float:
        '''The current salary in the period the user typed it in.'''
        return self.current_salary_monthly if self.salary_period == "monthly" else self.current_salary_annual


def _number(value) -> float:
    '''A salary setting as a number; blank, None or junk count as 0 (meaning "fall back").'''
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _tidy(value: float) -> float:
    '''Whole amounts stay whole (8000, not 8000.0) so they type cleanly into a form.'''
    return int(value) if float(value).is_integer() else round(value, 2)


def resolve_market(markets: ModuleType, questions: ModuleType, search: ModuleType, name: str | None = None) -> Market:
    '''
    The active market (`name`, else `markets.market`) with every blank value replaced by the
    general setting it falls back to. Raises ValueError for an unknown market name.
    '''
    name = (name or getattr(markets, "market", "internacional") or "internacional").strip().lower()
    if name not in MARKETS:
        raise ValueError(f'market must be one of {list(MARKETS)}, got {name!r}')
    legacyDesired = _number(getattr(questions, "desired_salary", 0))
    legacyCurrent = _number(getattr(questions, "current_ctc", 0))
    legacyTerms = tuple(getattr(search, "search_terms", []) or [])
    legacyLocation = str(getattr(search, "search_location", "") or "")

    if name == "brasil":
        desiredMonthly = _number(getattr(markets, "br_desired_salary_monthly", 0)) or legacyDesired
        currentMonthly = _number(getattr(markets, "br_current_salary_monthly", 0)) or legacyCurrent
        return Market(
            name=name, currency=str(getattr(markets, "br_currency", "BRL") or "BRL"), salary_period="monthly",
            desired_salary_annual=_tidy(desiredMonthly * 12), desired_salary_monthly=_tidy(desiredMonthly),
            current_salary_annual=_tidy(currentMonthly * 12), current_salary_monthly=_tidy(currentMonthly),
            search_location=str(getattr(markets, "br_search_location", "") or legacyLocation),
            search_terms=tuple(getattr(markets, "br_search_terms", []) or legacyTerms),
        )
    desiredAnnual = _number(getattr(markets, "intl_desired_salary_annual", 0)) or legacyDesired
    currentAnnual = _number(getattr(markets, "intl_current_salary_annual", 0)) or legacyCurrent
    return Market(
        name=name, currency=str(getattr(markets, "intl_currency", "USD") or "USD"), salary_period="annual",
        desired_salary_annual=_tidy(desiredAnnual), desired_salary_monthly=_tidy(desiredAnnual / 12),
        current_salary_annual=_tidy(currentAnnual), current_salary_monthly=_tidy(currentAnnual / 12),
        search_location=str(getattr(markets, "intl_search_location", "") or legacyLocation),
        search_terms=tuple(getattr(markets, "intl_search_terms", []) or legacyTerms),
    )


def active_market() -> Market:
    '''The market configured right now, from the live config modules.'''
    import config.markets as markets
    import config.questions as questions
    import config.search as search
    return resolve_market(markets, questions, search)
