'''
Captured answers: what the user types into the form during a "Help Needed" pause becomes an
approved remembered answer. Driven through `read_form_state` + `capture_manual_answers` with
a fake modal whose controls change between the two snapshots.

License: MIT  (https://opensource.org/license/mit)
'''

import pytest

from modules.answers_memory import AnswerMemory
from tests.fakes import (FakeElement, FakeSelect, FakeRadio, FakeCheckbox, import_bot, modal_with)


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


JOB = "https://www.linkedin.com/jobs/view/555"


def text_question(label, value=""):
    control = FakeElement(value=value)
    return FakeElement(children={".//input[@type='text']": control, ".//label[@for]": FakeElement(text=label)}), control


def textarea_question(label, value=""):
    control = FakeElement(value=value)
    return FakeElement(children={".//textarea": control, ".//label[@for]": FakeElement(text=label)}), control


def select_question(bot, monkeypatch, label, options, selected="Select an option"):
    fake_select = FakeSelect(options, selected=selected)
    monkeypatch.setattr(bot, "Select", lambda element: fake_select)
    question = FakeElement(children={".//select": FakeElement(),
                                     "label": FakeElement(children={"span": FakeElement(text=label)})})
    return question, fake_select


def radio_question(label, option_labels):
    options = [FakeRadio(f"opt{i}", text) for i, text in enumerate(option_labels)]
    children = {'.//span[@data-test-form-builder-radio-button-form-component__title]':
                    FakeElement(children={"visually-hidden": FakeElement(text=label)}),
                'input': options}
    for option in options:
        children[f'.//label[@for="{option.id}"]'] = FakeElement(text=option.label)
    fieldset = FakeElement(children=children)
    return FakeElement(children={'.//fieldset[@data-test-form-builder-radio-button-form-component="true"]': fieldset}), options


def checkbox_question(visible, hidden=None):
    box = FakeCheckbox()
    children = {".//input[@type='checkbox']": box, ".//label[@for]": FakeElement(text=visible)}
    if hidden is not None:
        children[".//span[@class='visually-hidden']"] = FakeElement(text=hidden)
    return FakeElement(children=children), box


# ------------------------------------ read_form_state ------------------------
def test_read_form_state_reports_empty_controls_as_none(bot, monkeypatch):
    text, _ = text_question("Favourite language")
    select, _ = select_question(bot, monkeypatch, "Work style", ["Select an option", "Remote"])
    modal = FakeElement(children={".//div[@data-test-form-element]": [text, select]})
    assert bot.read_form_state(modal) == {("Favourite language", "text"): None, ("Work style", "select"): None}


def test_read_form_state_reads_values_and_the_selected_radio_label(bot, monkeypatch):
    text, _ = text_question("Favourite language", value="Go")
    radio, options = radio_question("Driver's licence?", ["Yes", "No"])
    options[1].selected = True
    checkbox, box = checkbox_question("Subscribe to alerts")
    box.selected = True
    modal = FakeElement(children={".//div[@data-test-form-element]": [text, radio, checkbox]})
    assert bot.read_form_state(modal) == {
        ("Favourite language", "text"): "Go",
        ("Driver's licence?", "radio"): "No",
        ("Subscribe to alerts", "checkbox"): "checked",
    }


# ------------------------------------ capture --------------------------------
def test_what_the_user_typed_during_the_pause_is_remembered_as_approved(bot, memory, monkeypatch):
    text, control = text_question("Favourite language")
    modal = modal_with(text)
    before = bot.read_form_state(modal)
    control.value = "Go"                                  # the user types during the pause

    captured = bot.capture_manual_answers(before, bot.read_form_state(modal), JOB)

    assert captured == 1
    found, _ = memory.lookup("Favourite language", "text")
    assert found.answer == "Go" and found.state == "approved" and found.source == "user"
    assert found.last_job_link == JOB


def test_a_dropdown_choice_is_captured_as_its_visible_text(bot, memory, monkeypatch):
    select, fake_select = select_question(bot, monkeypatch, "Work style", ["Select an option", "Remote", "Hybrid"])
    modal = modal_with(select)
    before = bot.read_form_state(modal)
    fake_select.selected = "Hybrid"

    bot.capture_manual_answers(before, bot.read_form_state(modal), JOB)

    assert memory.lookup("Work style", "select")[0].answer == "Hybrid"


def test_a_radio_choice_is_captured_as_its_label(bot, memory, monkeypatch):
    radio, options = radio_question("Driver's licence?", ["Yes", "No"])
    modal = modal_with(radio)
    before = bot.read_form_state(modal)
    options[0].selected = True

    bot.capture_manual_answers(before, bot.read_form_state(modal), JOB)

    found = memory.lookup("Driver's licence?", "radio")[0]
    assert found.answer == "Yes" and found.state == "approved"


def test_a_checkbox_ticked_during_the_pause_is_captured_as_checked(bot, memory, monkeypatch):
    checkbox, box = checkbox_question("Subscribe to alerts", hidden="Notifications")
    modal = modal_with(checkbox)
    before = bot.read_form_state(modal)
    box.selected = True

    bot.capture_manual_answers(before, bot.read_form_state(modal), JOB)

    found = memory.lookup("Notifications Subscribe to alerts", "checkbox", approximate=False)[0]
    assert found.answer == "checked" and found.state == "approved" and found.source == "user"


def test_a_textarea_is_captured_with_its_own_kind(bot, memory, monkeypatch):
    area, control = textarea_question("Why us?")
    modal = modal_with(area)
    before = bot.read_form_state(modal)
    control.value = "Because."
    bot.capture_manual_answers(before, bot.read_form_state(modal), JOB)
    assert memory.lookup("Why us?", "textarea")[0] is not None
    assert memory.lookup("Why us?", "text") == (None, False)


def test_controls_still_empty_after_the_pause_are_not_captured(bot, memory, monkeypatch):
    text, _ = text_question("Favourite language")
    modal = modal_with(text)
    before = bot.read_form_state(modal)
    assert bot.capture_manual_answers(before, bot.read_form_state(modal), JOB) == 0
    assert memory.entries == []


def test_controls_the_bot_had_already_filled_are_not_captured(bot, memory, monkeypatch):
    '''Only what changed during the pause is the user's; the bot's own answers stay out of memory.'''
    text, control = text_question("First name", value="Jane")
    modal = modal_with(text)
    before = bot.read_form_state(modal)
    assert bot.capture_manual_answers(before, bot.read_form_state(modal), JOB) == 0


def test_a_sensitive_answer_typed_during_the_pause_is_not_captured(bot, memory, monkeypatch):
    text, control = text_question("What are your salary expectations?")
    modal = modal_with(text)
    before = bot.read_form_state(modal)
    control.value = "90000"
    assert bot.capture_manual_answers(before, bot.read_form_state(modal), JOB) == 0
    assert memory.entries == []


def test_a_pending_ai_answer_corrected_by_hand_becomes_the_approved_one(bot, memory, monkeypatch):
    memory.remember("Favourite language", "text", "Python", source="ai")
    text, control = text_question("Favourite language")       # the user cleared and retyped it
    modal = modal_with(text)
    before = bot.read_form_state(modal)
    control.value = "Go"

    bot.capture_manual_answers(before, bot.read_form_state(modal), JOB)

    found = memory.lookup("Favourite language", "text")[0]
    assert found.answer == "Go" and found.state == "approved" and len(memory.entries) == 1


def test_the_help_needed_pause_captures_between_its_two_snapshots(bot):
    '''
    The wiring, read from the source of the Easy Apply loop: snapshot, show the dialog,
    snapshot again, capture the difference. The loop itself needs a live modal to run.
    '''
    import inspect
    source = inspect.getsource(bot.apply_to_jobs)
    assert "formBefore = read_form_state(modal)" in source
    assert "capture_manual_answers(formBefore, read_form_state(modal), job_link)" in source
    assert source.index("formBefore = read_form_state(modal)") < source.index('"Help Needed"') < source.index("capture_manual_answers(")
