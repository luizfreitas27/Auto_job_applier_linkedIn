'''
Captured answers: what the user types into the form during a "Help Needed" pause becomes an
approved remembered answer. Driven through `pause_for_help` (with a dialog stub that fills
the fake form while it is "open") and through `read_form_state` + `capture_manual_answers`.

License: MIT  (https://opensource.org/license/mit)
'''

import pytest

from modules.answers_memory import AnswerMemory
from tests.fakes import (FakeElement, import_bot, modal_with, text_question, select_question,
                         radio_question, checkbox_block)


@pytest.fixture(scope="module")
def bot():
    '''runAiBot with the browser session stubbed out.'''
    return import_bot()


@pytest.fixture
def memory(bot, tmp_path, monkeypatch):
    fresh = AnswerMemory(tmp_path / "answers_memory.json")
    monkeypatch.setattr(bot, "answers_memory", fresh)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    monkeypatch.setattr(bot, "screenshot", lambda *a, **k: "shot.png")
    return fresh


JOB = "https://www.linkedin.com/jobs/view/555"


def textarea_question(label, value=""):
    return text_question(label, value=value, kind="textarea")


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
    checkbox, box = checkbox_block("Subscribe to alerts")
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
    checkbox, box = checkbox_block("Subscribe to alerts", hidden_label="Notifications")
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


def test_filling_an_empty_field_that_has_a_pending_memory_entry_approves_the_typed_answer(bot, memory, monkeypatch):
    '''The stale pending entry (the AI's) gives way to what the user typed. A field the bot had
    already filled is never captured, so correcting a bot answer in place is out of scope.'''
    memory.remember("Favourite language", "text", "Python", source="ai")
    text, control = text_question("Favourite language")
    modal = modal_with(text)
    before = bot.read_form_state(modal)
    control.value = "Go"

    bot.capture_manual_answers(before, bot.read_form_state(modal), JOB)

    found = memory.lookup("Favourite language", "text")[0]
    assert found.answer == "Go" and found.state == "approved" and len(memory.entries) == 1


def test_the_pause_captures_what_was_filled_while_the_dialog_was_open(bot, memory, monkeypatch):
    '''The real wiring: snapshot, dialog, snapshot, capture. The dialog stub plays the user.'''
    question, control = text_question("Favourite language")
    modal = modal_with(question)
    shown = []

    def user_fills_the_form(text, title, button="OK"):
        shown.append(title)
        control.value = "Go"
        return button
    monkeypatch.setattr(bot.dialogs, "alert", user_fills_the_form)

    assert bot.pause_for_help(modal, "job-1", JOB) == 1
    assert shown == ["Help Needed"]
    assert memory.lookup("Favourite language", "text")[0].answer == "Go"


def test_controls_that_appear_only_after_the_pause_are_not_captured(bot, memory, monkeypatch):
    '''The user clicked Next despite the warning: the new page's LinkedIn prefills are not their answers.'''
    first, _ = text_question("Favourite language")
    modal = modal_with(first)
    before = bot.read_form_state(modal)
    prefilled, _ = text_question("Mobile phone number", value="5550001234")
    after = bot.read_form_state(modal_with(prefilled))

    assert bot.capture_manual_answers(before, after, JOB) == 0
    assert memory.entries == []


def test_whitespace_only_input_is_not_an_answer(bot, memory, monkeypatch):
    question, control = text_question("Favourite language")
    modal = modal_with(question)
    before = bot.read_form_state(modal)
    control.value = "   "
    assert bot.capture_manual_answers(before, bot.read_form_state(modal), JOB) == 0


def test_a_form_that_cannot_be_re_read_captures_nothing_and_does_not_raise(bot, memory, monkeypatch):
    question, _ = text_question("Favourite language")
    modal = modal_with(question)
    reads = []

    def flaky_read(target):
        reads.append(target)
        if len(reads) == 2:
            raise RuntimeError("stale element reference")
        return {}
    monkeypatch.setattr(bot, "read_form_state", flaky_read)
    monkeypatch.setattr(bot.dialogs, "alert", lambda *a, **k: "Continue")

    assert bot.pause_for_help(modal, "job-1", JOB) == 0
