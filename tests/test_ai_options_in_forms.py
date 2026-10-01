'''
The AI answering dropdowns and radios through `answer_questions`, and the candidate profile
reaching it.

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
    '''Stand-in for a WebElement: `children` maps an XPath/tag/class to what it resolves to.'''

    def __init__(self, text="", value="", children=None):
        self.text = text
        self.value = value
        self.children = children or {}

    def clear(self): self.value = ""
    def send_keys(self, keys): self.value += str(keys)
    def get_attribute(self, name): return self.value if name == "value" else None
    def click(self): pass

    def find_element(self, by, locator):
        if locator in self.children:
            return self.children[locator]
        raise NoSuchElementException(locator)

    def find_elements(self, by, locator):
        found = self.children.get(locator)
        if isinstance(found, list):
            return found
        return [found] if found else []


class FakeSelect:
    def __init__(self, option_texts, selected="Select an option"):
        self.options = [FakeElement(text=text) for text in option_texts]
        self.selected = selected
        self.picked = None

    @property
    def first_selected_option(self): return FakeElement(text=self.selected)

    def select_by_visible_text(self, text):
        for option in self.options:
            if option.text == text:
                self.picked = self.selected = text
                return
        raise NoSuchElementException(text)


class FakeRadio(FakeElement):
    def __init__(self, id, label):
        super().__init__(text=label)
        self.id, self.label = id, label

    def get_attribute(self, name): return {"id": self.id, "value": self.label}[name]
    def is_selected(self): return False


class FakeMouse:
    def __init__(self): self.clicked = None
    def move_to_element(self, element): self.clicked = element; return self
    def click(self): return self
    def perform(self): pass


def dropdown(bot, monkeypatch, question_text, option_texts):
    fake_select = FakeSelect(option_texts)
    monkeypatch.setattr(bot, "Select", lambda element: fake_select)
    question = FakeElement(children={
        ".//select": FakeElement(),
        "label": FakeElement(children={"span": FakeElement(text=question_text)}),
    })
    return FakeElement(children={".//div[@data-test-form-element]": [question]}), fake_select


def radio_group(bot, monkeypatch, question_text, option_labels):
    mouse = FakeMouse()
    monkeypatch.setattr(bot, "actions", mouse)
    options = [FakeRadio(f"opt{i}", text) for i, text in enumerate(option_labels)]
    children = {
        './/span[@data-test-form-builder-radio-button-form-component__title]':
            FakeElement(children={"visually-hidden": FakeElement(text=question_text)}),
        'input': options,
    }
    for option in options:
        children[f'.//label[@for="{option.id}"]'] = FakeElement(text=option.label)
        children[f".//label[normalize-space()='{option.label}']"] = FakeElement(text=option.label)
    radio = FakeElement(children=children)
    question = FakeElement(children={
        './/fieldset[@data-test-form-builder-radio-button-form-component="true"]': radio})
    return FakeElement(children={".//div[@data-test-form-element]": [question]}), mouse, options


def text_form(label_text):
    control = FakeElement()
    question = FakeElement(children={".//input[@type='text']": control, ".//label[@for]": FakeElement(text=label_text)})
    return FakeElement(children={".//div[@data-test-form-element]": [question]}), control


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
