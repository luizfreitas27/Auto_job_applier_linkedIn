'''
`answer_questions` and the answer memory, driven through a fake Easy Apply form.

Covers the text and textarea branches: an AI answer is remembered as pending, the next
job with the same question is answered from memory without the AI, approximate matches
are logged, and sensitive questions never reach memory or the AI.

License: MIT  (https://opensource.org/license/mit)
'''

import sys
import types

import pytest
from selenium.common.exceptions import NoSuchElementException

from modules.answers_memory import AnswerMemory


@pytest.fixture(scope="module")
def bot():
    '''Import runAiBot with a stubbed browser session, so importing it never opens Chrome.'''
    fake_chrome = types.ModuleType("modules.open_chrome")
    fake_chrome.options = fake_chrome.driver = fake_chrome.actions = fake_chrome.wait = None
    sys.modules["modules.open_chrome"] = fake_chrome
    import runAiBot
    return runAiBot


class FakeElement:
    '''Stand-in for a WebElement: `children` maps an XPath/class to what it resolves to.'''

    def __init__(self, text="", value="", children=None):
        self.text = text
        self.value = value
        self.children = children or {}

    def clear(self):
        self.value = ""

    def send_keys(self, keys):
        self.value += str(keys)

    def get_attribute(self, name):
        return self.value if name == "value" else None

    def find_element(self, by, locator):
        if locator in self.children:
            return self.children[locator]
        raise NoSuchElementException(locator)

    def find_elements(self, by, locator):
        found = self.children.get(locator)
        if isinstance(found, list):
            return found
        return [found] if found else []


def text_form(label_text, kind="text"):
    '''A modal with one text input (or textarea) under `label_text`. Returns (modal, control).'''
    control = FakeElement()
    xpath = ".//textarea" if kind == "textarea" else ".//input[@type='text']"
    question = FakeElement(children={xpath: control, ".//label[@for]": FakeElement(text=label_text)})
    modal = FakeElement(children={".//div[@data-test-form-element]": [question]})
    return modal, control


@pytest.fixture
def memory(bot, tmp_path, monkeypatch):
    '''A fresh answer memory in a temp file, wired into the bot.'''
    fresh = AnswerMemory(tmp_path / "answers_memory.json")
    monkeypatch.setattr(bot, "answers_memory", fresh)
    return fresh


@pytest.fixture
def ai(bot, monkeypatch):
    '''A fake AI that records every question it is asked and answers from `replies`.'''
    calls = []
    replies = {}

    def fake_answer_question(client, question, options=None, question_type="text", job_description=None,
                             about_company=None, user_information_all=None, stream=False):
        calls.append((question, question_type))
        return replies.get(question, "")

    monkeypatch.setattr(bot, "use_AI", True)
    monkeypatch.setattr(bot, "aiClient", object())
    monkeypatch.setattr(bot, "answer_question", fake_answer_question, raising=False)
    monkeypatch.setattr(bot, "human_type", lambda target, text: target.send_keys(text), raising=False)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    return types.SimpleNamespace(calls=calls, replies=replies)


JOB_A = "https://www.linkedin.com/jobs/view/111"
JOB_B = "https://www.linkedin.com/jobs/view/222"


# ------------------------------------ text ----------------------------------
def test_an_ai_answer_to_a_text_question_is_remembered_as_pending(bot, memory, ai):
    ai.replies["What is your favourite programming language?"] = "Python"
    modal, field = text_form("What is your favourite programming language?")

    bot.answer_questions(modal, set(), "Remote", job_link=JOB_A)

    assert field.value == "Python"
    found, _ = memory.lookup("What is your favourite programming language?", "text")
    assert found is not None
    assert found.answer == "Python" and found.state == "pending" and found.source == "ai"
    assert found.last_job_link == JOB_A
    assert found.uses == 1                          # used on this very job


def test_the_next_job_with_the_same_question_is_answered_from_memory(bot, memory, ai):
    ai.replies["What is your favourite programming language?"] = "Python"
    first_modal, _ = text_form("What is your favourite programming language?")
    bot.answer_questions(first_modal, set(), "Remote", job_link=JOB_A)
    assert len(ai.calls) == 1

    second_modal, field = text_form("What is your favourite programming language?")
    bot.answer_questions(second_modal, set(), "Remote", job_link=JOB_B)

    assert field.value == "Python"
    assert len(ai.calls) == 1                       # the AI was not asked again
    found, _ = memory.lookup("What is your favourite programming language?", "text")
    assert found.uses == 2 and found.last_job_link == JOB_B


def test_a_reworded_question_reuses_the_answer_and_logs_the_approximation(bot, memory, ai, log_records):
    memory.remember("How many years of experience do you have with Python?", "text", "4", source="user")
    modal, field = text_form("How many years experience do you have with Python?")

    bot.answer_questions(modal, set(), "Remote", job_link=JOB_A)

    assert field.value == "4"
    assert ai.calls == []
    assert any("approximate" in record.getMessage() for record in log_records)


def test_an_unrelated_question_below_the_threshold_still_goes_to_the_ai(bot, memory, ai):
    memory.remember("How many years of experience do you have with Python?", "text", "4", source="user")
    ai.replies["How many years of experience do you have with Kubernetes?"] = "2"
    modal, field = text_form("How many years of experience do you have with Kubernetes?")

    bot.answer_questions(modal, set(), "Remote", job_link=JOB_A)

    assert field.value == "2"
    assert len(ai.calls) == 1
    assert len(memory.entries) == 2


def test_a_memory_hit_is_used_even_while_pending(bot, memory, ai):
    memory.remember("Desired start date", "text", "ASAP", source="ai")
    modal, field = text_form("Desired start date")
    bot.answer_questions(modal, set(), "Remote", job_link=JOB_A)
    assert field.value == "ASAP"
    assert ai.calls == []


def test_without_memory_or_ai_the_question_is_still_reported_unanswered(bot, memory, ai):
    modal, field = text_form("What is your favourite programming language?")
    bot.answer_questions(modal, set(), "Remote", job_link=JOB_A)
    assert field.value == ""
    assert "What is your favourite programming language?" in bot.unanswered_questions
    assert memory.entries == []                     # an empty answer is not remembered


# ------------------------------------ textarea ------------------------------
def test_textarea_answers_are_remembered_with_their_own_kind(bot, memory, ai):
    ai.replies["Why do you want to work here?"] = "Because of the mission."
    modal, field = text_form("Why do you want to work here?", kind="textarea")

    bot.answer_questions(modal, set(), "Remote", job_link=JOB_A)

    assert field.value == "Because of the mission."
    assert ai.calls == [("Why do you want to work here?", "textarea")]
    assert memory.lookup("Why do you want to work here?", "textarea")[0] is not None
    assert memory.lookup("Why do you want to work here?", "text") == (None, False)


# ------------------------------------ sensitive -----------------------------
@pytest.mark.parametrize("question", [
    "Do you have a disability?",
    "Are you a protected veteran?",
    "Do you hold an active security clearance?",
    "What are your salary expectations in USD?",
])
def test_sensitive_questions_never_reach_memory_or_the_ai(bot, memory, ai, monkeypatch, question):
    '''Configured answers only. When the heuristics have nothing, the field stays empty.'''
    # Make sure no configured heuristic answers these text questions, so the only way the
    # field could be filled is memory or the AI, which must both be bypassed.
    monkeypatch.setattr(bot, "desired_salary", "")
    memory.remember(question, "text", "leaked", source="user")
    ai.replies[question] = "guessed"
    modal, field = text_form(question)

    bot.answer_questions(modal, set(), "Remote", job_link=JOB_A)

    assert field.value == ""
    assert ai.calls == []


def test_the_email_question_is_never_guessed_or_remembered(bot, memory, ai):
    '''A made-up email would be remembered and replayed on every later application.'''
    ai.replies["Email address"] = "made.up@example.com"
    modal, field = text_form("Email address")

    bot.answer_questions(modal, set(), "Remote", job_link=JOB_A)

    assert field.value == ""
    assert ai.calls == []
    assert memory.entries == []


def test_pay_attention_is_not_a_salary_question(bot):
    assert not bot.is_sensitive_question("Do you pay attention to detail?")
    assert bot.is_sensitive_question("What is your expected pay range?")


def test_is_sensitive_question_matches_whole_words_only(bot):
    assert bot.is_sensitive_question("Will you require visa sponsorship?")
    assert bot.is_sensitive_question("Are you legally authorized to work in the US?")
    assert bot.is_sensitive_question("Expected compensation")
    assert not bot.is_sensitive_question("What is your favourite programming language?")
    assert not bot.is_sensitive_question("Secretary experience in years")     # "secret" is a whole word, "Secretary" is not
