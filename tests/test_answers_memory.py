'''
Unit tests for modules/answers_memory.py against a temporary file.

What is under test is the memory's contract as the bot and the control panel see it:
remember, look up (exact and approximate), count uses, review, and survive a bad file.

License: MIT  (https://opensource.org/license/mit)
'''

import json

import pytest

from modules.answers_memory import AnswerMemory, RememberedAnswer, normalise, SIMILARITY_THRESHOLD


@pytest.fixture
def memory(tmp_path):
    return AnswerMemory(tmp_path / "answers_memory.json")


# ------------------------------------ normalise ------------------------------
@pytest.mark.parametrize("raw, expected", [
    ("How many years of experience do you have with Python?", "how many years of experience do you have with python"),
    ("  Notice   period (in days)  ", "notice period in days"),
    ("What's your GitHub URL?", "what s your github url"),
    ("", ""),
    (None, ""),
])
def test_normalise_lowercases_strips_punctuation_and_collapses_spaces(raw, expected):
    assert normalise(raw) == expected


# ------------------------------------ remember / lookup ----------------------
def test_an_ai_answer_is_remembered_as_pending(memory):
    entry = memory.remember("Years of experience with Python?", "text", "4", source="ai",
                            job_link="https://www.linkedin.com/jobs/view/1")
    assert entry.state == "pending" and entry.source == "ai"
    assert entry.uses == 0 and entry.last_job_link.endswith("/1")      # remembering is not using

    found, approximate = memory.lookup("Years of experience with Python?", "text")
    assert found is entry and approximate is False


def test_a_user_answer_is_remembered_as_approved(memory):
    entry = memory.remember("Preferred pronouns", "text", "they/them", source="user")
    assert entry.state == "approved" and entry.source == "user"


def test_lookup_ignores_case_punctuation_and_spacing(memory):
    memory.remember("Years of experience with Python?", "text", "4", source="ai")
    found, approximate = memory.lookup("  years OF experience, with python ", "text")
    assert found is not None and approximate is False


def test_a_reworded_question_matches_approximately_and_is_logged(memory, log_records):
    memory.remember("How many years of experience do you have with Python?", "text", "4", source="ai")
    found, approximate = memory.lookup("How many years experience do you have with Python?", "text")
    assert found is not None and approximate is True
    assert any("approximate" in record.getMessage() for record in log_records)


def test_approximate_matching_can_be_turned_off(memory):
    memory.remember("How many years of experience do you have with Python?", "text", "4", source="ai")
    assert memory.lookup("How many years experience do you have with Python?", "text", approximate=False) == (None, False)
    assert memory.lookup("How many years of experience do you have with Python?", "text", approximate=False)[0] is not None


def test_a_different_question_below_the_threshold_does_not_match(memory):
    memory.remember("How many years of experience do you have with Python?", "text", "4", source="ai")
    found, _ = memory.lookup("How many years of experience do you have with Kubernetes?", "text")
    assert found is None


def test_matching_never_crosses_control_kinds(memory):
    memory.remember("Are you willing to relocate?", "select", "Yes", source="ai")
    assert memory.lookup("Are you willing to relocate?", "text") == (None, False)
    assert memory.lookup("Are you willing to relocate?", "radio") == (None, False)
    assert memory.lookup("Are you willing to relocate?", "select")[0] is not None


def test_an_empty_label_never_matches(memory):
    memory.remember("x", "text", "1", source="ai")
    assert memory.lookup("", "text") == (None, False)
    assert memory.lookup("   ?!", "text") == (None, False)


def test_remembering_the_same_question_again_updates_instead_of_duplicating(memory):
    first = memory.remember("Desired start date", "text", "ASAP", source="ai")
    second = memory.remember("Desired start date?", "text", "In two weeks", source="user")
    assert second is first
    assert len(memory.entries) == 1
    assert first.answer == "In two weeks" and first.state == "approved" and first.source == "user"


def test_an_ai_answer_never_overrides_an_approved_user_answer(memory):
    approved = memory.remember("Desired start date", "text", "In two weeks", source="user")
    again = memory.remember("Desired start date", "text", "ASAP", source="ai")
    assert again is approved
    assert approved.answer == "In two weeks" and approved.state == "approved" and approved.source == "user"


def test_a_user_answer_replaces_a_pending_ai_answer_and_approves_it(memory):
    pending = memory.remember("Desired start date", "text", "ASAP", source="ai")
    corrected = memory.remember("Desired start date", "text", "In two weeks", source="user")
    assert corrected is pending
    assert pending.answer == "In two weeks" and pending.state == "approved" and pending.source == "user"


def test_invalid_kind_or_source_is_rejected(memory):
    with pytest.raises(ValueError):
        memory.remember("q", "slider", "1", source="ai")
    with pytest.raises(ValueError):
        memory.remember("q", "text", "1", source="oracle")


# ------------------------------------ uses -----------------------------------
def test_record_use_counts_and_tracks_the_last_job(memory):
    entry = memory.remember("Desired start date", "text", "ASAP", source="ai")
    memory.record_use(entry, "https://www.linkedin.com/jobs/view/7")
    memory.record_use(entry, "https://www.linkedin.com/jobs/view/8")
    assert entry.uses == 2
    assert entry.last_job_link.endswith("/8")


# ------------------------------------ review ---------------------------------
def test_pending_count_list_approve_and_delete(memory):
    a = memory.remember("Q1", "text", "A1", source="ai")
    b = memory.remember("Q2", "textarea", "A2", source="ai")
    c = memory.remember("Q3", "text", "A3", source="user")
    assert memory.pending_count() == 2
    assert {entry.id for entry in memory.list("pending")} == {a.id, b.id}
    assert {entry.id for entry in memory.list("approved")} == {c.id}
    assert len(memory.list()) == 3

    approved = memory.approve(a.id, answer="A1 corrected")
    assert approved.state == "approved" and approved.answer == "A1 corrected" and approved.source == "user"
    assert memory.pending_count() == 1

    assert memory.approve("nope") is None
    assert memory.delete(b.id) is True
    assert memory.delete(b.id) is False
    assert memory.pending_count() == 0
    assert memory.get(b.id) is None


# ------------------------------------ storage --------------------------------
def test_changes_are_persisted_and_reloaded(memory):
    entry = memory.remember("Desired start date", "text", "ASAP", source="ai",
                            job_link="https://www.linkedin.com/jobs/view/1")
    memory.record_use(entry, "https://www.linkedin.com/jobs/view/2")

    reloaded = AnswerMemory(memory.path)
    found, _ = reloaded.lookup("Desired start date", "text")
    assert found is not None
    assert found.id == entry.id and found.uses == 1 and found.last_job_link.endswith("/2")   # one record_use
    assert not memory.path.with_suffix(".json.tmp").exists()        # the temp file was replaced


def test_the_file_is_human_readable_json(memory):
    memory.remember("Desired start date", "text", "ASAP", source="ai")
    data = json.loads(memory.path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["answers"][0]["label"] == "Desired start date"
    assert data["answers"][0]["state"] == "pending"


def test_a_missing_file_is_an_empty_memory(memory):
    assert memory.entries == []
    assert memory.pending_count() == 0


def test_a_corrupt_file_is_an_empty_memory_and_warns(tmp_path, log_records):
    path = tmp_path / "answers_memory.json"
    path.write_text("{not json", encoding="utf-8")
    memory = AnswerMemory(path)
    assert memory.entries == []
    assert any(record.levelname == "WARNING" for record in log_records)


def test_rows_with_unknown_kinds_or_missing_fields_are_dropped_not_fatal(tmp_path):
    path = tmp_path / "answers_memory.json"
    path.write_text(json.dumps({"version": 1, "answers": [
        {"label": "ok", "kind": "text", "answer": "1", "source": "ai", "state": "pending"},
        {"label": "bad kind", "kind": "slider", "answer": "1", "source": "ai", "state": "pending"},
        {"label": "missing answer", "kind": "text", "source": "ai", "state": "pending"},
        "not even an object",
    ]}), encoding="utf-8")
    memory = AnswerMemory(path)
    assert [entry.label for entry in memory.entries] == ["ok"]


def test_an_unwritable_path_is_logged_not_raised(tmp_path, log_records):
    memory = AnswerMemory(tmp_path / "no-such-dir" / "answers_memory.json")
    memory.remember("q", "text", "a", source="ai")                   # save fails inside
    assert any("Could not save" in record.getMessage() for record in log_records)
    assert memory.pending_count() == 1                               # still usable in memory


def test_from_dict_ignores_unknown_keys():
    entry = RememberedAnswer.from_dict({"label": "q", "kind": "text", "answer": "a", "source": "ai",
                                        "state": "pending", "future_field": 42})
    assert entry is not None and entry.normalised == "q"
