'''
The review queue: the control panel's /api/answers routes over the answer memory, and the
memory's behaviour when two processes (the bot and the panel) share the file.

License: MIT  (https://opensource.org/license/mit)
'''

import pytest

from modules.answers_memory import AnswerMemory

PANEL = {"X-Requested-With": "control-panel"}


@pytest.fixture
def panel_memory(tmp_path, monkeypatch):
    '''A fresh answer memory in a temp file, wired into the panel.'''
    import app
    fresh = AnswerMemory(tmp_path / "answers_memory.json")
    monkeypatch.setattr(app, "answers_memory", fresh)
    return fresh


def seed(memory):
    a = memory.remember("Preferred work style", "select", "Hybrid", source="ai", job_link="https://www.linkedin.com/jobs/view/1")
    b = memory.remember("Why do you want to work here?", "textarea", "Mission.", source="ai")
    c = memory.remember("Subscribe to job alerts", "checkbox", "checked", source="form")
    d = memory.remember("Favourite language", "text", "Go", source="user")
    return a, b, c, d


# ------------------------------------ list ----------------------------------
def test_listing_returns_every_field_the_tab_shows_and_the_pending_count(client, panel_memory):
    a, _, _, _ = seed(panel_memory)
    data = client.get("/api/answers").get_json()
    assert data["pending_count"] == 3
    row = next(r for r in data["answers"] if r["id"] == a.id)
    assert row == {"id": a.id, "question": "Preferred work style", "kind": "select", "answer": "Hybrid",
                   "source": "ai", "state": "pending", "uses": 0,
                   "last_job_link": "https://www.linkedin.com/jobs/view/1", "updated_at": a.updated_at}


def test_listing_filters_by_state(client, panel_memory):
    a, b, c, d = seed(panel_memory)
    pending = client.get("/api/answers?state=pending").get_json()["answers"]
    approved = client.get("/api/answers?state=approved").get_json()["answers"]
    assert {r["id"] for r in pending} == {a.id, b.id, c.id}
    assert {r["id"] for r in approved} == {d.id}
    assert len(client.get("/api/answers?state=all").get_json()["answers"]) == 4


def test_listing_rejects_an_unknown_state(client, panel_memory):
    assert client.get("/api/answers?state=maybe").status_code == 400


def test_an_empty_memory_lists_nothing(client, panel_memory):
    assert client.get("/api/answers").get_json() == {"answers": [], "pending_count": 0}


# ------------------------------------ approve -------------------------------
def test_approving_as_is_marks_the_answer_approved_and_keeps_its_author(client, panel_memory):
    '''The AI stays the author of an answer the user merely vetted; "From" keeps telling the story.'''
    a, _, _, _ = seed(panel_memory)
    resp = client.post(f"/api/answers/{a.id}", json={}, headers=PANEL)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["answer"]["state"] == "approved" and body["answer"]["source"] == "ai"
    assert body["answer"]["answer"] == "Hybrid"
    assert body["pending_count"] == 2
    assert AnswerMemory(panel_memory.path).get(a.id).state == "approved"      # persisted


def test_editing_and_approving_replaces_the_text_and_makes_it_yours(client, panel_memory):
    a, _, _, _ = seed(panel_memory)
    resp = client.post(f"/api/answers/{a.id}", json={"answer": "  Remote  "}, headers=PANEL)
    assert resp.get_json()["answer"]["answer"] == "Remote"
    assert resp.get_json()["answer"]["source"] == "user"
    assert AnswerMemory(panel_memory.path).get(a.id).answer == "Remote"


def test_an_empty_edit_is_rejected(client, panel_memory):
    a, _, _, _ = seed(panel_memory)
    assert client.post(f"/api/answers/{a.id}", json={"answer": "   "}, headers=PANEL).status_code == 400
    assert panel_memory.get(a.id).state == "pending"


def test_approving_an_unknown_id_is_a_404(client, panel_memory):
    assert client.post("/api/answers/nope", json={}, headers=PANEL).status_code == 404


# ------------------------------------ delete --------------------------------
def test_deleting_forgets_the_answer(client, panel_memory):
    a, _, _, _ = seed(panel_memory)
    resp = client.delete(f"/api/answers/{a.id}", headers=PANEL)
    assert resp.status_code == 200 and resp.get_json()["pending_count"] == 2
    assert panel_memory.get(a.id) is None
    assert client.delete(f"/api/answers/{a.id}", headers=PANEL).status_code == 404


def test_deleting_all_pending_clears_the_queue_and_keeps_approved(client, panel_memory):
    a, b, c, d = seed(panel_memory)
    resp = client.delete("/api/answers?state=pending", headers=PANEL)
    assert resp.get_json() == {"deleted": 3, "pending_count": 0}
    assert [entry.id for entry in panel_memory.entries] == [d.id]
    assert client.delete("/api/answers", headers=PANEL).status_code == 400
    assert client.delete("/api/answers?state=all", headers=PANEL).status_code == 400


# ------------------------------------ protections ---------------------------
def test_state_changing_answer_routes_need_the_panel_header(client, panel_memory):
    a, _, _, _ = seed(panel_memory)
    assert client.post(f"/api/answers/{a.id}", json={}).status_code == 403
    assert client.delete(f"/api/answers/{a.id}").status_code == 403
    assert client.delete("/api/answers?state=pending").status_code == 403
    assert client.post(f"/api/answers/{a.id}", json={}, headers=dict(PANEL, Origin="http://evil.example")).status_code == 403
    assert client.get("/api/answers", base_url="http://evil.example/").status_code == 403
    assert panel_memory.get(a.id).state == "pending" and len(panel_memory.entries) == 4


# ------------------------------------ two processes -------------------------
def test_the_panel_sees_what_the_bot_wrote_after_loading(tmp_path):
    '''Separate instances over one file stand in for the bot and the panel.'''
    path = tmp_path / "answers_memory.json"
    panel, bot = AnswerMemory(path), AnswerMemory(path)
    assert panel.pending_count() == 0                    # the panel has loaded an empty file
    bot.remember("Preferred work style", "select", "Hybrid", source="ai")
    assert panel.pending_count() == 1                    # ...and notices the bot's write


def test_a_bot_use_does_not_undo_an_approval_made_meanwhile(tmp_path):
    path = tmp_path / "answers_memory.json"
    bot, panel = AnswerMemory(path), AnswerMemory(path)
    entry = bot.remember("Preferred work style", "select", "Hybrid", source="ai")
    panel.approve(entry.id, answer="Remote")              # the user approves while the bot runs
    bot.record_use(entry, "https://www.linkedin.com/jobs/view/9")   # the bot holds the old object

    live = AnswerMemory(path).get(entry.id)
    assert live.state == "approved" and live.answer == "Remote" and live.uses == 1


def test_a_bot_use_of_an_answer_deleted_meanwhile_does_not_resurrect_it(tmp_path):
    path = tmp_path / "answers_memory.json"
    bot, panel = AnswerMemory(path), AnswerMemory(path)
    entry = bot.remember("Preferred work style", "select", "Hybrid", source="ai")
    panel.delete(entry.id)
    bot.record_use(entry)
    assert AnswerMemory(path).entries == []


def test_a_panel_approval_survives_a_bot_write_that_lands_between_read_and_save(tmp_path, monkeypatch):
    '''
    save() must persist what this instance holds, not re-read the file first: the re-read
    would silently drop the approval while the route still reports success.
    '''
    path = tmp_path / "answers_memory.json"
    bot, panel = AnswerMemory(path), AnswerMemory(path)
    entry = bot.remember("Q1", "text", "A1", source="ai")
    target = panel.get(entry.id)                          # the panel has read the file...
    bot.remember("Q2", "text", "A2", source="ai")         # ...and the bot writes before the panel saves
    target.state = "approved"
    panel.save()
    assert AnswerMemory(path).get(entry.id).state == "approved"


def test_a_bot_remember_does_not_clobber_panel_edits_to_other_entries(tmp_path):
    path = tmp_path / "answers_memory.json"
    bot, panel = AnswerMemory(path), AnswerMemory(path)
    first = bot.remember("Q1", "text", "A1", source="ai")
    panel.approve(first.id)
    bot.remember("Q2", "text", "A2", source="ai")
    live = AnswerMemory(path)
    assert live.get(first.id).state == "approved" and live.pending_count() == 1


# ------------------------------------ run summary ---------------------------
def test_the_run_summary_reports_pending_answers(tmp_path, monkeypatch):
    from tests.fakes import import_bot
    bot = import_bot()
    memory = AnswerMemory(tmp_path / "answers_memory.json")
    memory.remember("Q1", "text", "A1", source="ai")
    memory.remember("Q2", "text", "A2", source="ai")
    monkeypatch.setattr(bot, "answers_memory", memory)
    summary = bot.run_summary(total_runs=3)
    assert "Total runs: 3" in summary
    assert "Pending answers to review in the control panel: 2" in summary
    import inspect
    assert "Pending answers to review:" in inspect.getsource(bot.main)      # the aligned block the user reads
