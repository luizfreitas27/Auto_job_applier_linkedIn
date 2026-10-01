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


def _text(value) -> str:
    '''A setting as prompt text, or "" when it is unset. Numbers are kept as typed (no quotes).'''
    if value is None:
        return ""
    return str(value).strip()


def build_candidate_profile(personals: ModuleType | None = None, questions: ModuleType | None = None) -> str:
    '''
    Plain-text block describing the applicant, one "Label: value" line per configured
    setting, followed by `user_information_all` verbatim. Blank settings are skipped.
    `personals` / `questions` default to the live config modules; tests pass stand-ins.
    '''
    if personals is None:
        import config.personals as personals
    if questions is None:
        import config.questions as questions

    get = lambda module, name: _text(getattr(module, name, ""))

    fullName = " ".join(part for part in (get(personals, "first_name"), get(personals, "middle_name"),
                                          get(personals, "last_name")) if part)
    location = ", ".join(part for part in (get(personals, "current_city"), get(personals, "state"),
                                           get(personals, "country")) if part)
    noticeDays = get(questions, "notice_period")

    rows = [
        ("Name", fullName),
        ("Location", location),
        ("Years of professional experience", get(questions, "years_of_experience")),
        ("Most recent employer", get(questions, "recent_employer")),
        ("Headline", get(questions, "linkedin_headline")),
        ("Desired annual salary", get(questions, "desired_salary")),
        ("Current annual salary", get(questions, "current_ctc")),
        ("Notice period", f"{noticeDays} days" if noticeDays else ""),
        ("Legally authorized to work in the country of the job", get(questions, "legally_authorized")),
        ("Will require visa sponsorship", get(questions, "require_visa")),
        ("Citizenship status", get(questions, "us_citizenship")),
        ("Portfolio or website", get(questions, "website")),
    ]
    lines = [f"{label}: {value}" for label, value in rows if value]

    summary = get(questions, "linkedin_summary")
    if summary:
        lines.append(f"Summary:\n{summary}")
    extra = get(questions, "user_information_all")
    if extra and extra.lower() != "user information":        # the shipped placeholder says nothing
        lines.append(f"Additional information:\n{extra}")
    return "\n".join(lines)
