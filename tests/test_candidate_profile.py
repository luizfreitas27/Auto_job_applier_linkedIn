'''
Tests for modules/ai/profile.py: the candidate profile the AI is given.

License: MIT  (https://opensource.org/license/mit)
'''

from types import SimpleNamespace

from modules.ai.profile import build_candidate_profile


def personals(**overrides):
    base = dict(first_name="Jane", middle_name="Q", last_name="Applicant", phone_number="9876543210",
                current_city="Lisbon", street="123 Main Street", state="Lisboa", zipcode="1000-001",
                country="Portugal", ethnicity="Decline", gender="Decline", disability_status="Decline",
                veteran_status="Decline")
    base.update(overrides)
    return SimpleNamespace(**base)


def questions(**overrides):
    base = dict(years_of_experience="6", require_visa="No", website="https://jane.dev", linkedIn="https://linkedin.com/in/jane",
                legally_authorized="Yes", us_citizenship="Other", desired_salary=90000, current_ctc=70000,
                notice_period=30, linkedin_headline="Backend engineer", linkedin_summary="I build APIs.",
                cover_letter="Dear hiring manager", user_information_all="\nUser Information\n",
                recent_employer="Acme", confidence_level="8")
    base.update(overrides)
    return SimpleNamespace(**base)


def test_the_profile_carries_the_configured_facts():
    profile = build_candidate_profile(personals(), questions())
    assert "Name: Jane Q Applicant" in profile
    assert "Location: Lisbon, Lisboa, Portugal" in profile
    assert "Years of professional experience: 6" in profile
    assert "Most recent employer: Acme" in profile
    assert "Headline: Backend engineer" in profile
    assert "Desired annual salary: 90000" in profile
    assert "Notice period: 30 days" in profile
    assert "Legally authorized to work in the country of the job: Yes" in profile
    assert "Will require visa sponsorship: No" in profile
    assert "Summary:\nI build APIs." in profile


def test_citizenship_current_salary_and_links_stay_out_of_the_profile():
    '''Not in the spec's list, and citizenship and current pay are sensitive facts the model
    is told to use "whenever relevant", so they could surface in a free-text answer.'''
    profile = build_candidate_profile(personals(), questions())
    for absent in ("Other", "70000", "https://jane.dev", "linkedin.com/in/jane", "Citizenship", "Current annual"):
        assert absent not in profile


def test_contact_details_never_reach_the_profile():
    profile = build_candidate_profile(personals(), questions())
    for secret in ("9876543210", "123 Main Street", "1000-001"):
        assert secret not in profile
    assert "mail" not in profile.lower()


def test_protected_characteristics_and_the_cover_letter_are_not_included():
    profile = build_candidate_profile(personals(gender="Female", ethnicity="Asian", disability_status="No",
                                                veteran_status="No"), questions())
    for word in ("Female", "Asian", "Dear hiring manager", "Decline"):
        assert word not in profile


def test_blank_settings_are_skipped_not_printed_as_empty():
    profile = build_candidate_profile(personals(middle_name="", current_city=""),
                                      questions(recent_employer="", linkedin_summary=""))
    assert "Name: Jane Applicant" in profile
    assert "Location: Lisboa, Portugal" in profile
    assert "Most recent employer" not in profile
    assert "Summary" not in profile
    assert ": \n" not in profile and not profile.endswith(":")


def test_the_free_text_addition_is_appended_verbatim():
    profile = build_candidate_profile(personals(), questions(user_information_all="Key skills: Python, Go, Kubernetes."))
    assert profile.endswith("Additional information:\nKey skills: Python, Go, Kubernetes.")


def test_the_shipped_placeholder_free_text_is_ignored():
    profile = build_candidate_profile(personals(), questions(user_information_all="\nUser Information\n"))
    assert "Additional information" not in profile
    assert "User Information" not in profile


def test_missing_settings_in_an_old_config_do_not_break_the_profile():
    profile = build_candidate_profile(SimpleNamespace(first_name="Jane"), SimpleNamespace())
    assert profile == "Name: Jane"


def test_the_live_config_modules_are_the_default_source(monkeypatch):
    import config.personals as personals
    monkeypatch.setattr(personals, "first_name", "Livewire")
    assert "Name: Livewire" in build_candidate_profile()
