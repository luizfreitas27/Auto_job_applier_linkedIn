'''
`answer_questions` and the answer memory for dropdowns, radios and checkboxes.

A remembered select or radio answer is text and is snapped to whatever options THIS form
offers. A checkbox is ticked only from an approved remembered answer; an unrecognised
unticked box is offered for review as a pending "checked" entry, unless it is sensitive.

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

    def __init__(self, text="", children=None):
        self.text = text
        self.children = children or {}

    def find_element(self, by, locator):
        if locator in self.children:
            return self.children[locator]
        raise NoSuchElementException(locator)

    def find_elements(self, by, locator):
        found = self.children.get(locator)
        if isinstance(found, list):
            return found
        return [found] if found else []

    def click(self):
        pass


class FakeSelect:
    '''Enough of selenium's `Select` to drive the dropdown branch.'''

    def __init__(self, option_texts, selected="Select an option"):
        self.options = [FakeElement(text=text) for text in option_texts]
        self.selected = selected
        self.picked = None

    @property
    def first_selected_option(self):
        return FakeElement(text=self.selected)

    def select_by_visible_text(self, text):
        for option in self.options:
            if option.text == text:
                self.picked = self.selected = text
                return
        raise NoSuchElementException(text)


class FakeRadio(FakeElement):
    '''One <input type="radio">.'''

    def __init__(self, id, label, selected=False):
        super().__init__(text=label)
        self.id, self.label, self.selected = id, label, selected

    def get_attribute(self, name):
        return {"id": self.id, "value": self.label}[name]

    def is_selected(self):
        return self.selected


class FakeCheckbox(FakeElement):
    '''One <input type="checkbox">.'''

    def __init__(self, id=None, selected=False):
        super().__init__()
        self.id, self.selected = id, selected

    def get_attribute(self, name):
        return {"id": self.id}[name]

    def is_selected(self):
        return self.selected


class FakeMouse:
    '''`actions.move_to_element(x).click().perform()`: records what x was.'''

    def __init__(self): self.clicked = None
    def move_to_element(self, element): self.clicked = element; return self
    def click(self): return self
    def perform(self): pass


def dropdown(bot, monkeypatch, question_text, option_texts):
    '''A modal holding one <select>; returns (modal, FakeSelect).'''
    fake_select = FakeSelect(option_texts)
    monkeypatch.setattr(bot, "Select", lambda element: fake_select)
    question = FakeElement(children={
        ".//select": FakeElement(),
        "label": FakeElement(children={"span": FakeElement(text=question_text)}),
    })
    return FakeElement(children={".//div[@data-test-form-element]": [question]}), fake_select


def radio_group(bot, monkeypatch, question_text, option_labels):
    '''A modal holding one radio fieldset; returns (modal, FakeMouse, options).'''
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


def checkbox_question(bot, monkeypatch, visible_label, hidden_label=None):
    '''A modal holding one checkbox; returns (modal, FakeMouse, checkbox).'''
    mouse = FakeMouse()
    monkeypatch.setattr(bot, "actions", mouse)
    box = FakeCheckbox()
    children = {".//input[@type='checkbox']": box, ".//label[@for]": FakeElement(text=visible_label)}
    if hidden_label is not None:
        children[".//span[@class='visually-hidden']"] = FakeElement(text=hidden_label)
    question = FakeElement(children=children)
    return FakeElement(children={".//div[@data-test-form-element]": [question]}), mouse, box


@pytest.fixture
def memory(bot, tmp_path, monkeypatch):
    '''A fresh answer memory in a temp file, wired into the bot, with the AI off.'''
    fresh = AnswerMemory(tmp_path / "answers_memory.json")
    monkeypatch.setattr(bot, "answers_memory", fresh)
    monkeypatch.setattr(bot, "use_AI", False)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    return fresh


JOB = "https://www.linkedin.com/jobs/view/333"


# ------------------------------------ select --------------------------------
def test_a_remembered_dropdown_answer_picks_the_matching_option(bot, memory, monkeypatch):
    entry = memory.remember("Are you willing to relocate?", "select", "Yes", source="user")
    modal, select = dropdown(bot, monkeypatch, "Are you willing to relocate?", ["Select an option", "Yes", "No"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert select.picked == "Yes"
    assert entry.uses == 1 and entry.last_job_link == JOB
    assert not bot.unanswered_questions


def test_a_remembered_answer_is_snapped_to_differently_worded_options(bot, memory, monkeypatch):
    memory.remember("Are you willing to relocate?", "select", "Yes", source="ai")
    modal, select = dropdown(bot, monkeypatch, "Are you willing to relocate?",
                             ["Select an option", "Yes, I am", "No, I am not"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert select.picked == "Yes, I am"


def test_a_pending_remembered_dropdown_answer_is_used_too(bot, memory, monkeypatch):
    memory.remember("Preferred work style", "select", "Hybrid", source="ai")
    modal, select = dropdown(bot, monkeypatch, "Preferred work style", ["Select an option", "Remote", "Hybrid", "On-site"])
    bot.answer_questions(modal, set(), "Remote", job_link=JOB)
    assert select.picked == "Hybrid"


def test_when_no_option_matches_the_remembered_text_the_dropdown_is_left_alone(bot, memory, monkeypatch):
    entry = memory.remember("Preferred work style", "select", "Hybrid", source="user")
    modal, select = dropdown(bot, monkeypatch, "Preferred work style", ["Select an option", "Remote", "On-site"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert select.picked is None
    assert bot.unanswered_questions                 # reported, so the stall guard can skip the job
    assert entry.uses == 0


def test_memory_is_not_consulted_for_a_recognised_dropdown_question(bot, memory, monkeypatch):
    '''Configured answers rule. A gender question is recognised even when its answer fits no option.'''
    monkeypatch.setattr(bot, "gender", "Nonbinary")
    entry = memory.remember("Gender", "select", "Male", source="user")
    modal, select = dropdown(bot, monkeypatch, "Gender", ["Select an option", "Male", "Female"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert select.picked is None
    assert entry.uses == 0


def test_a_blank_configured_answer_lets_memory_answer_the_dropdown(bot, memory, monkeypatch):
    '''`gender = ""` means "nothing configured", the same as an unrecognised question in the text branch.'''
    monkeypatch.setattr(bot, "gender", "")
    memory.remember("Gender", "select", "Male", source="user")
    modal, select = dropdown(bot, monkeypatch, "Gender", ["Select an option", "Male", "Female"])
    bot.answer_questions(modal, set(), "Remote", job_link=JOB)
    assert select.picked == "Male"


def test_a_sensitive_dropdown_question_never_uses_memory(bot, memory, monkeypatch):
    monkeypatch.setattr(bot, "require_visa", "")
    entry = memory.remember("Will you require visa sponsorship?", "select", "No", source="user")
    modal, select = dropdown(bot, monkeypatch, "Will you require visa sponsorship?", ["Select an option", "Yes", "No"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert select.picked is None
    assert entry.uses == 0


def test_a_remembered_dropdown_answer_never_fills_a_text_question(bot, memory, monkeypatch):
    memory.remember("Are you willing to relocate?", "text", "Yes", source="user")
    modal, select = dropdown(bot, monkeypatch, "Are you willing to relocate?", ["Select an option", "Yes", "No"])
    bot.answer_questions(modal, set(), "Remote", job_link=JOB)
    assert select.picked is None


# ------------------------------------ radio ---------------------------------
def test_a_remembered_radio_answer_clicks_the_matching_option(bot, memory, monkeypatch):
    entry = memory.remember("Do you have a driver's licence?", "radio", "No", source="user")
    modal, mouse, options = radio_group(bot, monkeypatch, "Do you have a driver's licence?", ["Yes", "No"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert mouse.clicked is options[1]
    assert entry.uses == 1


def test_a_remembered_radio_answer_respects_yes_no_polarity(bot, memory, monkeypatch):
    memory.remember("Do you have a driver's licence?", "radio", "No", source="ai")
    modal, mouse, options = radio_group(bot, monkeypatch, "Do you have a driver's licence?",
                                        ["Yes, I do", "No, I do not"])
    bot.answer_questions(modal, set(), "Remote", job_link=JOB)
    assert mouse.clicked is options[1]


def test_when_no_radio_option_matches_the_remembered_text_the_group_is_left_alone(bot, memory, monkeypatch):
    entry = memory.remember("Preferred shift", "radio", "Night", source="user")
    modal, mouse, _ = radio_group(bot, monkeypatch, "Preferred shift", ["Morning", "Afternoon"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert mouse.clicked is None
    assert bot.unanswered_questions
    assert entry.uses == 0


def test_a_sensitive_radio_question_never_uses_memory(bot, memory, monkeypatch):
    monkeypatch.setattr(bot, "veteran_status", "")
    entry = memory.remember("Are you a protected veteran?", "radio", "Yes", source="user")
    modal, mouse, _ = radio_group(bot, monkeypatch, "Are you a protected veteran?", ["Yes", "No"])

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert mouse.clicked is None
    assert entry.uses == 0


# ------------------------------------ checkbox ------------------------------
def test_an_approved_checkbox_answer_ticks_the_box(bot, memory, monkeypatch):
    entry = memory.remember("Subscribe to job alerts", "checkbox", "checked", source="user")
    modal, mouse, box = checkbox_question(bot, monkeypatch, "Subscribe to job alerts")

    questions_list = bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert mouse.clicked is box
    assert not bot.unanswered_questions
    assert entry.uses == 1
    assert {checked for _, checked, kind, _ in questions_list if kind == "checkbox"} == {True}


def test_a_pending_checkbox_answer_never_ticks_the_box(bot, memory, monkeypatch):
    memory.remember("Subscribe to job alerts", "checkbox", "checked", source="form")
    modal, mouse, box = checkbox_question(bot, monkeypatch, "Subscribe to job alerts")

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert mouse.clicked is None
    assert bot.unanswered_questions


def test_an_unrecognised_unticked_checkbox_is_offered_for_review(bot, memory, monkeypatch):
    modal, mouse, box = checkbox_question(bot, monkeypatch, "Subscribe to job alerts")

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert mouse.clicked is None
    found, _ = memory.lookup("Subscribe to job alerts", "checkbox")
    assert found is not None
    assert found.answer == "checked" and found.state == "pending" and found.source == "form"
    assert found.last_job_link == JOB


def test_a_checkbox_with_no_text_at_all_is_never_remembered_or_ticked(bot, memory, monkeypatch):
    '''An approved "Unknown" would tick every unlabeled box on every form.'''
    memory.remember("Unknown", "checkbox", "checked", source="user")
    mouse = FakeMouse()
    monkeypatch.setattr(bot, "actions", mouse)
    question = FakeElement(children={".//input[@type='checkbox']": FakeCheckbox()})   # no label of any kind
    modal = FakeElement(children={".//div[@data-test-form-element]": [question]})

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert mouse.clicked is None
    assert len(memory.entries) == 1                 # nothing new remembered


def test_checkbox_matching_is_exact_never_approximate(bot, memory, monkeypatch):
    '''A near-identical attestation at another employer is a different legal text.'''
    memory.remember("I agree to the terms and conditions of Acme", "checkbox", "checked", source="user")
    modal, mouse, _ = checkbox_question(bot, monkeypatch, "I agree to the terms and conditions of Acme Inc")

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert mouse.clicked is None


def test_the_group_title_is_part_of_the_checkbox_question(bot, memory, monkeypatch):
    modal, _, _ = checkbox_question(bot, monkeypatch, "Email", hidden_label="How may we contact you?")
    bot.answer_questions(modal, set(), "Remote", job_link=JOB)
    assert memory.lookup("How may we contact you? Email", "checkbox")[0] is not None


@pytest.mark.parametrize("attestation", [
    "I certify that I am a U.S. citizen",
    "I confirm I do not require visa sponsorship",
    "I hold an active security clearance",
])
def test_a_sensitive_checkbox_is_neither_ticked_nor_offered_for_review(bot, memory, monkeypatch, attestation):
    memory.remember(attestation, "checkbox", "checked", source="user")   # even an approved one
    modal, mouse, _ = checkbox_question(bot, monkeypatch, attestation)

    bot.answer_questions(modal, set(), "Remote", job_link=JOB)

    assert mouse.clicked is None
    assert len(memory.entries) == 1                 # nothing new remembered either


def test_a_non_sensitive_attestation_is_offered_but_not_ticked(bot, memory, monkeypatch):
    '''"I agree to the terms" is the user's call; approving it in the review queue is how it gets ticked.'''
    modal, mouse, _ = checkbox_question(bot, monkeypatch, "I agree to the terms and conditions")
    bot.answer_questions(modal, set(), "Remote", job_link=JOB)
    assert mouse.clicked is None
    found, _ = memory.lookup("I agree to the terms and conditions", "checkbox")
    assert found is not None and found.state == "pending"
