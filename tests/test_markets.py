'''
Markets: resolving the active market with its fallbacks, the bot answering salary and other
questions in Portuguese, Sim/Não option snapping, and the Markets tab round trip.

License: MIT  (https://opensource.org/license/mit)
'''

import json
from types import SimpleNamespace

import pytest

from modules.markets import resolve_market, Market, MARKETS
from tests.fakes import import_bot, text_form, dropdown, radio_group

PANEL = {"X-Requested-With": "control-panel"}


def markets(**overrides):
    base = dict(market="internacional", br_currency="BRL", br_desired_salary_monthly=0, br_current_salary_monthly=0,
                br_search_location="Brasil", br_search_terms=[], intl_currency="USD", intl_desired_salary_annual=0,
                intl_current_salary_annual=0, intl_search_location="", intl_search_terms=[])
    base.update(overrides)
    return SimpleNamespace(**base)


LEGACY_Q = SimpleNamespace(desired_salary=120000, current_ctc=96000)
LEGACY_S = SimpleNamespace(search_terms=["Software Engineer"], search_location="United States")


# ------------------------------------ resolve ---------------------------------
def test_the_default_market_reproduces_the_legacy_settings_exactly():
    m = resolve_market(markets(), LEGACY_Q, LEGACY_S)
    assert m.name == "internacional" and m.currency == "USD" and m.salary_period == "annual"
    assert m.desired_salary_annual == 120000 and m.desired_salary_monthly == 10000
    assert m.current_salary_annual == 96000 and m.current_salary_monthly == 8000
    assert m.search_terms == ("Software Engineer",) and m.search_location == "United States"


def test_brazil_salaries_are_monthly_in_reais_and_carried_both_ways():
    m = resolve_market(markets(market="brasil", br_desired_salary_monthly=8000, br_current_salary_monthly=6500), LEGACY_Q, LEGACY_S)
    assert m.currency == "BRL" and m.salary_period == "monthly"
    assert m.desired_salary_monthly == 8000 and m.desired_salary_annual == 96000
    assert m.current_salary_monthly == 6500 and m.current_salary_annual == 78000
    assert m.desired_salary_as_entered == 8000


def test_international_values_win_over_the_legacy_ones_when_set():
    m = resolve_market(markets(intl_currency="EUR", intl_desired_salary_annual=90000, intl_search_location="Portugal",
                               intl_search_terms=["Backend Developer"]), LEGACY_Q, LEGACY_S)
    assert m.currency == "EUR" and m.desired_salary_annual == 90000 and m.desired_salary_monthly == 7500
    assert m.current_salary_annual == 96000                         # blank -> legacy
    assert m.search_location == "Portugal" and m.search_terms == ("Backend Developer",)


def test_blank_brazilian_values_fall_back_to_the_legacy_settings():
    m = resolve_market(markets(market="brasil", br_search_location="", br_search_terms=[]), LEGACY_Q, LEGACY_S)
    assert m.desired_salary_monthly == 120000                       # the legacy number, taken as monthly
    assert m.search_location == "United States" and m.search_terms == ("Software Engineer",)


def test_the_market_name_is_case_insensitive_and_unknown_names_are_rejected():
    assert resolve_market(markets(market=" Brasil "), LEGACY_Q, LEGACY_S).name == "brasil"
    with pytest.raises(ValueError, match="market must be one of"):
        resolve_market(markets(market="europa"), LEGACY_Q, LEGACY_S)
    assert MARKETS == ("brasil", "internacional")


def test_an_old_config_without_the_markets_module_values_still_resolves():
    m = resolve_market(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
    assert m.name == "internacional" and m.desired_salary_annual == 0 and m.search_terms == ()


# ------------------------------------ the bot ---------------------------------
@pytest.fixture(scope="module")
def bot():
    return import_bot()


@pytest.fixture
def quiet(bot, monkeypatch):
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    monkeypatch.setattr(bot, "human_type", lambda target, text: target.send_keys(text), raising=False)
    monkeypatch.setattr(bot, "use_AI", False)


def set_market(bot, monkeypatch, m: Market):
    '''Point the bot at a market the way its import-time code does.'''
    monkeypatch.setattr(bot, "active_market", m)
    monkeypatch.setattr(bot, "desired_salary", str(m.desired_salary_annual))
    monkeypatch.setattr(bot, "desired_salary_monthly", str(m.desired_salary_monthly))
    monkeypatch.setattr(bot, "current_ctc", str(m.current_salary_annual))
    monkeypatch.setattr(bot, "current_ctc_monthly", str(m.current_salary_monthly))


BR = resolve_market(markets(market="brasil", br_desired_salary_monthly=8000, br_current_salary_monthly=6500), LEGACY_Q, LEGACY_S)
INTL = resolve_market(markets(intl_desired_salary_annual=90000, intl_current_salary_annual=70000), LEGACY_Q, LEGACY_S)


@pytest.mark.parametrize("label, expected", [
    ("Pretensão salarial mensal", "8000"),
    ("Pretensão salarial", "8000"),                       # no period named: the market's own (monthly)
    ("Qual sua pretensão salarial anual?", "96000"),
    ("Salário atual", "6500"),
    ("Remuneração atual anual", "78000"),
])
def test_brazilian_salary_questions_get_the_monthly_figure_unless_annual_is_asked(bot, quiet, monkeypatch, label, expected):
    set_market(bot, monkeypatch, BR)
    modal, field = text_form(label)
    bot.answer_questions(modal, set(), "Remoto")
    assert field.value == expected


@pytest.mark.parametrize("label, expected", [
    ("Expected annual salary", "90000"),
    ("Expected salary", "90000"),                          # no period named: the market's own (annual)
    ("Expected monthly salary", "7500"),
    ("Current compensation", "70000"),
])
def test_international_salary_questions_get_the_annual_figure_unless_monthly_is_asked(bot, quiet, monkeypatch, label, expected):
    set_market(bot, monkeypatch, INTL)
    modal, field = text_form(label)
    bot.answer_questions(modal, set(), "Remote")
    assert field.value == expected


@pytest.mark.parametrize("label, attribute", [
    ("Anos de experiência", "years_of_experience"),
    ("Telefone", "phone_number"),
    ("Celular", "phone_number"),
    ("Nome completo", "full_name"),
    ("Sobrenome", "last_name"),
    ("CEP", "zipcode"),
    ("Estado", "state"),
    ("País", "country"),
    ("Aviso prévio (dias)", "notice_period"),
    ("Site ou portfólio", "website"),
])
def test_portuguese_text_questions_are_recognised_like_english_ones(bot, quiet, monkeypatch, label, attribute):
    set_market(bot, monkeypatch, BR)
    modal, field = text_form(label)
    bot.answer_questions(modal, set(), "Remoto")
    assert field.value == str(getattr(bot, attribute))
    assert field.value != ""


def test_a_city_question_in_portuguese_types_the_city(bot, quiet, monkeypatch):
    set_market(bot, monkeypatch, BR)
    monkeypatch.setattr(bot, "current_city", "Manaus")
    monkeypatch.setattr(bot, "actions", SimpleNamespace(send_keys=lambda *a: SimpleNamespace(perform=lambda: None)))
    monkeypatch.setattr(bot, "sleep", lambda s: None)
    modal, field = text_form("Cidade")
    bot.answer_questions(modal, set(), "Remoto")
    assert field.value == "Manaus"


def test_a_portuguese_visa_question_is_sensitive_and_answered_from_config(bot, quiet, monkeypatch):
    set_market(bot, monkeypatch, BR)
    monkeypatch.setattr(bot, "require_visa", "Não")
    modal, select = dropdown(bot, monkeypatch, "Você precisa de visto para trabalhar no país?", ["Select an option", "Sim", "Não"])
    bot.answer_questions(modal, set(), "Remoto")
    assert select.picked == "Não"
    assert bot.is_sensitive_question("Você precisa de visto?")
    assert bot.is_sensitive_question("Pretensão salarial")
    assert bot.is_sensitive_question("Você é PCD?")


def test_a_configured_yes_selects_sim_and_a_no_selects_nao(bot, quiet, monkeypatch):
    set_market(bot, monkeypatch, BR)
    monkeypatch.setattr(bot, "legally_authorized", "Yes")
    modal, select = dropdown(bot, monkeypatch, "Você está legalmente autorizado a trabalhar no Brasil?", ["Select an option", "Sim", "Não"])
    monkeypatch.setattr(bot, "authorization_terms", bot.authorization_terms + ["autorizado a trabalhar"])
    bot.answer_questions(modal, set(), "Remoto")
    assert select.picked == "Sim"

    monkeypatch.setattr(bot, "require_visa", "No")
    modal, mouse, options = radio_group(bot, monkeypatch, "Precisa de patrocínio de visto?", ["Sim, preciso", "Não, não preciso"])
    bot.answer_questions(modal, set(), "Remoto")
    assert mouse.clicked is options[1]


def test_polarity_a_no_never_lands_on_a_sim_option_that_contains_nao(bot, quiet, monkeypatch):
    '''"Não" as a whole word inside "Sim, mas não agora" must not make that option a No.'''
    assert bot.match_answer_to_option("No", ["Sim, mas não agora", "Não"]) == 1
    assert bot.match_answer_to_option("Yes", ["Sim", "Não"]) == 0
    assert bot.match_answer_to_option("Decline", ["Sim", "Não", "Prefiro não informar"]) == 2


def test_search_terms_and_location_follow_the_market(bot):
    import importlib, runAiBot
    assert bot.search_terms == list(bot.active_market.search_terms)
    assert bot.search_location == bot.active_market.search_location


# ------------------------------------ the panel -------------------------------
def test_the_markets_tab_exists_and_round_trips(client, tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    import config_schema
    cfg_path = tmp_path / "user_config.json"
    monkeypatch.setattr(app, "USER_CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", str(cfg_path))
    sections = [s["section"] for s in config_schema.SCHEMA]
    assert "Markets" in sections
    fields = {f["key"]: f for f in config_schema.iter_fields() if f["config_module"] == "markets"}
    assert fields["market"]["options"] == ["brasil", "internacional"]

    resp = client.post("/api/config", json={"markets": {"market": "brasil", "br_desired_salary_monthly": "8000",
                                                        "br_search_terms": "Desenvolvedor Python, Engenheiro de Software"}}, headers=PANEL)
    assert resp.status_code == 200
    saved = json.loads(cfg_path.read_text(encoding="utf-8"))["markets"]
    assert saved == {"market": "brasil", "br_desired_salary_monthly": 8000,
                     "br_search_terms": ["Desenvolvedor Python", "Engenheiro de Software"]}
    got = client.get("/api/config").get_json()["markets"]
    assert got["market"] == "brasil" and got["intl_currency"] == "USD"


def test_validation_rejects_an_unknown_market_and_a_negative_salary(monkeypatch):
    import modules.validator as validator
    monkeypatch.setattr(validator, "market", "europa")
    with pytest.raises(ValueError):
        validator.validate_markets()
    monkeypatch.setattr(validator, "market", "brasil")
    monkeypatch.setattr(validator, "br_desired_salary_monthly", -1)
    with pytest.raises(ValueError, match="negative"):
        validator.validate_markets()
    monkeypatch.setattr(validator, "br_desired_salary_monthly", "8000")
    with pytest.raises(TypeError):
        validator.validate_markets()
    monkeypatch.setattr(validator, "br_desired_salary_monthly", 8000)
    validator.validate_markets()
