'''
Shared stand-ins for driving `answer_questions` without a browser: a fake DOM, fake Selenium
`Select`, fake radio/checkbox inputs, a fake mouse, and builders for one-question modals.

Import with `from tests.fakes import ...` (pytest.ini puts the repo root on the path).

License: MIT  (https://opensource.org/license/mit)
'''

import sys
import types

from selenium.common.exceptions import NoSuchElementException


def import_bot():
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
    '''Enough of selenium's `Select` to drive the dropdown branch.'''

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
    '''One <input type="radio">: the branch reads its id, value and selected state.'''

    def __init__(self, id, label, selected=False):
        super().__init__(text=label)
        self.id, self.label, self.selected = id, label, selected

    def get_attribute(self, name): return {"id": self.id, "value": self.label}[name]
    def is_selected(self): return self.selected


class FakeCheckbox(FakeElement):
    '''One <input type="checkbox">: the branch reads its id and its selected state.'''

    def __init__(self, id=None, selected=False):
        super().__init__()
        self.id, self.selected = id, selected

    def get_attribute(self, name): return {"id": self.id}[name]
    def is_selected(self): return self.selected


class FakeMouse:
    '''`actions.move_to_element(x).click().perform()`: records what x was, if anything.'''

    def __init__(self): self.clicked = None
    def move_to_element(self, element): self.clicked = element; return self
    def click(self): return self
    def perform(self): pass


def modal_with(question):
    '''A modal holding exactly one question block.'''
    return FakeElement(children={".//div[@data-test-form-element]": [question]})


def text_form(label_text, kind="text"):
    '''A modal with one text input (or textarea) under `label_text`. Returns (modal, control).'''
    control = FakeElement()
    xpath = ".//textarea" if kind == "textarea" else ".//input[@type='text']"
    question = FakeElement(children={xpath: control, ".//label[@for]": FakeElement(text=label_text)})
    return modal_with(question), control


def dropdown(bot, monkeypatch, question_text, option_texts):
    '''A modal holding one <select>; returns (modal, FakeSelect).'''
    fake_select = FakeSelect(option_texts)
    monkeypatch.setattr(bot, "Select", lambda element: fake_select)
    question = FakeElement(children={
        ".//select": FakeElement(),
        "label": FakeElement(children={"span": FakeElement(text=question_text)}),
    })
    return modal_with(question), fake_select


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
    return modal_with(question), mouse, options


def checkbox_question(bot, monkeypatch, visible_label, hidden_label=None):
    '''A modal holding one checkbox; returns (modal, FakeMouse, checkbox).'''
    mouse = FakeMouse()
    monkeypatch.setattr(bot, "actions", mouse)
    box = FakeCheckbox()
    children = {".//input[@type='checkbox']": box, ".//label[@for]": FakeElement(text=visible_label)}
    if hidden_label is not None:
        children[".//span[@class='visually-hidden']"] = FakeElement(text=hidden_label)
    return modal_with(FakeElement(children=children)), mouse, box
