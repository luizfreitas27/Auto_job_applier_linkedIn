'''
The AI answering dropdowns and radios through `answer_questions`, and the candidate profile
reaching it.

License: MIT  (https://opensource.org/license/mit)
'''

import types

import pytest

from modules.answers_memory import AnswerMemory
from tests.fakes import (FakeElement, FakeCheckbox, FakeMouse, import_bot, text_form, dropdown,
                         radio_group, checkbox_question)


@pytest.fixture(scope="module")
def bot():
    '''runAiBot with the browser session stubbed out.'''
    return import_bot()


@pytest.fixture
def memory(bot, tmp_path, monkeypatch):
    fresh = AnswerMemory(tmp_path / "answers_memory.json")
    monkeypatch.setattr(bot, "answers_memory", fresh)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    return fresh


@pytest.fixture
def ai(bot, monkeypatch):
    '''A fake AI recording every call (question, options, type, profile) and answering from `replies`.'''
    calls = []
    replies = {}

    def fake_answer_question(client, question, options=None, question_type="text", job_description=None,
                             about_company=None, user_information_all=None, stream=False):
        calls.append(types.SimpleNamespace(question=question, options=options, question_type=question_type,
                                           profile=user_information_all))
        return replies.get(question, "")

    monkeypatch.setattr(bot, "use_AI", True)
    monkeypatch.setattr(bot, "aiClient", object())
    monkeypatch.setattr(bot, "answer_question", fake_answer_question, raising=False)
    monkeypatch.setattr(bot, "human_type", lambda target, text: target.send_keys(text), raising=False)
    return types.SimpleNamespace(calls=calls, replies=replies)


JOB = "https://www.linkedin.com/jobs/view/444"


# ------------------------------------ select --------------------------------
def test_the_ai_fills_an_unrecognised_dropdown_when_it_names_an_option(bot, memory, ai, monkeypatch):
    ai.replies["Preferred work style"] = "Hybrid"
    modal, select = dropdown(bot, monkeypatch, "Preferred work style", ["Select an option", "Remote", "Hybrid", "On-site"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert select.picked == "Hybrid"
    assert not bot.unanswered_questions
    call = ai.calls[0]
    assert call.question_type == "single_select"
    assert call.options == ["Remote", "Hybrid", "On-site"]          # the placeholder is not a choice
    found, _ = memory.lookup("Preferred work style", "select")
    assert found.answer == "Hybrid" and found.state == "pending" and found.source == "ai" and found.uses == 1


def test_an_ai_answer_that_is_not_an_option_leaves_the_dropdown_alone(bot, memory, ai, monkeypatch):
    ai.replies["Preferred work style"] = "Mostly remote"
    modal, select = dropdown(bot, monkeypatch, "Preferred work style", ["Select an option", "Remote", "Hybrid"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert select.picked is None
    assert bot.unanswered_questions
    assert memory.entries == []                     # a rejected answer is not remembered


def test_memory_is_consulted_before_the_ai_for_a_dropdown(bot, memory, ai, monkeypatch):
    memory.remember("Preferred work style", "select", "Remote", source="user")
    ai.replies["Preferred work style"] = "Hybrid"
    modal, select = dropdown(bot, monkeypatch, "Preferred work style", ["Select an option", "Remote", "Hybrid"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert select.picked == "Remote"
    assert ai.calls == []


def test_a_sensitive_dropdown_is_never_sent_to_the_ai(bot, memory, ai, monkeypatch):
    monkeypatch.setattr(bot, "us_citizenship", "")
    ai.replies["What is your citizenship status?"] = "Other"
    modal, select = dropdown(bot, monkeypatch, "What is your citizenship status?", ["Select an option", "U.S. Citizen", "Other"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert select.picked is None
    assert ai.calls == []


def test_a_recognised_dropdown_with_a_configured_answer_does_not_ask_the_ai(bot, memory, ai, monkeypatch):
    monkeypatch.setattr(bot, "gender", "Nonbinary")
    modal, select = dropdown(bot, monkeypatch, "Gender", ["Select an option", "Male", "Female"])
    bot.answer_questions(modal, set(), "Remote", job_link=JOB)
    assert select.picked is None
    assert ai.calls == []


# ------------------------------------ radio ---------------------------------
def test_the_ai_clicks_an_unrecognised_radio_when_it_names_an_option(bot, memory, ai, monkeypatch):
    ai.replies["Do you have a driver's licence?"] = "Yes"
    modal, mouse, options = radio_group(bot, monkeypatch, "Do you have a driver's licence?", ["Yes", "No"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert mouse.clicked is options[0]
    assert ai.calls[0].options == ["Yes", "No"]
    assert memory.lookup("Do you have a driver's licence?", "radio")[0].state == "pending"


def test_an_ai_radio_answer_that_is_not_an_option_leaves_the_group_alone(bot, memory, ai, monkeypatch):
    ai.replies["Do you have a driver's licence?"] = "I do"
    modal, mouse, _ = radio_group(bot, monkeypatch, "Do you have a driver's licence?", ["Yes", "No"])
    bot.answer_questions(modal, set(), "Remote", job_link=JOB)
    assert mouse.clicked is None
    assert bot.unanswered_questions


# ------------------------------------ profile -------------------------------
def test_the_ai_receives_the_candidate_profile_not_the_bare_free_text(bot, memory, ai, monkeypatch):
    import config.personals as personals
    import config.questions as questions
    monkeypatch.setattr(personals, "first_name", "Jane")
    monkeypatch.setattr(personals, "phone_number", "5550001234")
    monkeypatch.setattr(personals, "street", "42 Hidden Lane")
    monkeypatch.setattr(questions, "years_of_experience", "6")
    monkeypatch.setattr(questions, "user_information_all", "Key skills: Go.")
    ai.replies["What is your favourite programming language?"] = "Go"
    modal, _ = text_form("What is your favourite programming language?")

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    profile = ai.calls[0].profile
    assert "Name: Jane" in profile
    assert "Years of professional experience: 6" in profile
    assert "Key skills: Go." in profile
    assert "5550001234" not in profile and "42 Hidden Lane" not in profile
