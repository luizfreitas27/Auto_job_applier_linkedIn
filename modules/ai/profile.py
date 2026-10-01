'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

The **candidate profile**: the description of the applicant the bot hands to the AI when it
asks for an answer. Assembled from what the user already configured in `config/personals.py`
and `config/questions.py`, so nobody has to write their profile twice, with the free-text
`user_information_all` appended for anything the structured fields miss.

Deliberately left out: phone number, street address, zip code, email. No question that ever
reaches the AI should need them, and they stay off the wire.
'''

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.markets import Market


def _text(value: object | None) -> str:
    '''A setting as prompt text, or "" when it is unset. Numbers are kept as typed (no quotes).'''
    if value is None:
        return ""
    return str(value).strip()


def build_candidate_profile(personals: ModuleType | None = None, questions: ModuleType | None = None,
                            market: "Market | None" = None) -> str:
    '''
    Plain-text block describing the applicant, one "Label: value" line per configured
    setting, followed by `user_information_all` verbatim. Blank settings are skipped.
    `personals` / `questions` default to the live config modules and `market` to the active
    market (modules/markets.py); tests pass stand-ins.
    '''
    if personals is None:
        import config.personals as personals
    if questions is None:
        import config.questions as questions
    if market is None:
        from modules.markets import active_market
        market = active_market()

    def setting(module: ModuleType, name: str) -> str:
        '''One config setting as prompt text, "" when missing or blank.'''
        return _text(getattr(module, name, ""))

    fullName = " ".join(part for part in (setting(personals, "first_name"), setting(personals, "middle_name"),
                                          setting(personals, "last_name")) if part)
    location = ", ".join(part for part in (setting(personals, "current_city"), setting(personals, "state"),
                                           setting(personals, "country")) if part)
    noticeDays = setting(questions, "notice_period")

    # Exactly the facts the spec lists. Citizenship status and current salary are deliberately
    # NOT here: they are sensitive, and the prompt tells the model to use applicant facts
    # "whenever relevant", so anything in this block can surface in a free-text answer.
    rows = [
        ("Name", fullName),
        ("Location", location),
        ("Years of professional experience", setting(questions, "years_of_experience")),
        ("Most recent employer", setting(questions, "recent_employer")),
        ("Headline", setting(questions, "linkedin_headline")),
        (f"Desired {market.salary_period} salary", f"{_text(market.desired_salary_as_entered)} {market.currency}".strip()
            if market.desired_salary_as_entered else ""),
        ("Notice period", f"{noticeDays} days" if noticeDays else ""),
        ("Legally authorized to work in the country of the job", setting(questions, "legally_authorized")),
        ("Will require visa sponsorship", setting(questions, "require_visa")),
    ]
    lines = [f"{label}: {value}" for label, value in rows if value]

    summary = setting(questions, "linkedin_summary")
    if summary:
        lines.append(f"Summary:\n{summary}")
    extra = setting(questions, "user_information_all")
    # ponytail: "User Information" is the text config/questions.py ships in user_information_all;
    # compare against the module default instead if that placeholder ever changes.
    if extra and extra.lower() != "user information":
        lines.append(f"Additional information:\n{extra}")
    return "\n".join(lines)
