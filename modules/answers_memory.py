'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

The **answer memory**: every answer the bot gave to an unrecognised question, kept in
`answers_memory.json` at the project root (gitignored) so each question has to be resolved
once. See CONTEXT.md for the vocabulary (remembered answer, review state, review queue).

A remembered answer is keyed by the normalised question label plus the control kind. Lookup
is exact first, then approximate (`difflib` ratio >= SIMILARITY_THRESHOLD, same kind only),
and an approximate hit is logged with both labels so a wrong reuse can be audited.

This module knows nothing about which questions are sensitive; the bot decides that before
it ever consults the memory (see `is_sensitive_question` in runAiBot.py).

Two processes share the file: the bot during a run and the control panel's review queue.
Every public method first checks whether the file changed on disk since it was last read
(size and mtime) and reloads if so, and every change is saved at once, so each operation is
a read-modify-write on fresh data. Entries handed out earlier are looked up again by id
before being changed, never trusted as current.
ponytail: no lock. Two writes inside the same mtime tick with an unchanged file size go
unnoticed and the later one wins, so a bot use count or a panel approval can be lost in that
window; it self-heals on the next size-changing write. A file lock would close it.
'''

from __future__ import annotations

import difflib
import json
import os
import re
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

from modules.helpers import logger

ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = ROOT / "answers_memory.json"

KINDS = ("text", "textarea", "select", "radio", "checkbox")
# "form": not an answer anyone gave, but a control the bot saw and left alone (an unticked
# checkbox) recorded as pending so the user can approve it in the review queue.
SOURCES = ("ai", "user", "form")
STATES = ("pending", "approved")
SIMILARITY_THRESHOLD = 0.92

_NON_WORD = re.compile(r"[^a-z0-9\s]+")
_SPACES = re.compile(r"\s+")


def normalise(label: str | None) -> str:
    '''Lowercase, drop punctuation, collapse whitespace: the key half of a remembered answer.'''
    lowered = (label or "").lower()
    return _SPACES.sub(" ", _NON_WORD.sub(" ", lowered)).strip()


def _now() -> str:
    '''Local timestamp to the second, the format every entry's created_at/updated_at uses.'''
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class RememberedAnswer:
    '''One remembered answer. `answer` is the visible text; for a checkbox it is "checked".'''
    label: str
    kind: str
    answer: str
    source: str
    state: str
    normalised: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    uses: int = 0
    last_job_link: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        '''Derive the lookup key from the label unless one was loaded from disk.'''
        if not self.normalised:
            self.normalised = normalise(self.label)

    def as_row(self) -> dict:
        '''The entry as the control panel's Answers tab consumes it.'''
        return {
            "id": self.id, "question": self.label, "kind": self.kind, "answer": self.answer,
            "source": self.source, "state": self.state, "uses": self.uses,
            "last_job_link": self.last_job_link, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RememberedAnswer | None:
        '''Build an entry from a JSON object, or None when it is missing the fields that matter.'''
        try:
            if data["kind"] not in KINDS or data["source"] not in SOURCES or data["state"] not in STATES:
                return None
            known = {name for name in cls.__dataclass_fields__}
            return cls(**{key: value for key, value in data.items() if key in known})
        except (KeyError, TypeError):
            return None


class AnswerMemory:
    '''
    The answer memory behind one JSON file. Loads lazily on first use, saves after every
    change (atomically: write a sibling temp file, then replace), and treats a missing or
    corrupt file as empty: the bot must never fail because of this file.
    '''

    def __init__(self, path: str | os.PathLike = MEMORY_PATH) -> None:
        self.path = Path(path)
        self._entries: list[RememberedAnswer] | None = None
        self._loaded_stamp: tuple[int, int] | None = None     # (mtime_ns, size) of the file as last read

    # ------------------------------------------------------------------ storage
    def _stamp(self) -> tuple[int, int] | None:
        '''The file's (mtime_ns, size), or None when it does not exist.'''
        try:
            info = os.stat(self.path)
            return (info.st_mtime_ns, info.st_size)
        except OSError:
            return None

    @property
    def entries(self) -> list[RememberedAnswer]:
        '''All remembered answers, reloaded whenever another process changed the file.'''
        stamp = self._stamp()
        if self._entries is None or stamp != self._loaded_stamp:
            self._entries = self._load()
            self._loaded_stamp = stamp
        return self._entries

    def _load(self) -> list[RememberedAnswer]:
        '''Read the file. Missing: empty. Unreadable or not JSON: empty, with one warning.'''
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as error:
            logger.warning("Could not read the answer memory at %s (%s). Starting with an empty memory.",
                           self.path, error)
            return []
        rows = data.get("answers", []) if isinstance(data, dict) else []
        loaded = [RememberedAnswer.from_dict(row) for row in rows if isinstance(row, dict)]
        return [entry for entry in loaded if entry is not None]

    def save(self) -> None:
        '''Write the memory to disk atomically. Failures are logged, never raised.'''
        # `self._entries`, not the `entries` property: the property reloads from disk when the
        # file changed, which would throw away the very change this save is persisting.
        payload = {"version": 1, "answers": [asdict(entry) for entry in (self._entries or [])]}
        temporaryPath = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with open(temporaryPath, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2, ensure_ascii=False)
            os.replace(temporaryPath, self.path)
            self._loaded_stamp = self._stamp()
        except OSError as error:
            logger.warning("Could not save the answer memory to %s (%s).", self.path, error)

    # ------------------------------------------------------------------ queries
    def lookup(self, label: str, kind: str, approximate: bool = True) -> tuple[RememberedAnswer | None, bool]:
        '''
        The remembered answer for `label` in a control of `kind`, and whether the match was
        approximate. Exact match on the normalised label first; otherwise, if `approximate`,
        the most similar entry of the same kind at or above SIMILARITY_THRESHOLD.
        (None, False) when nothing fits.
        '''
        key = normalise(label)
        if not key:
            return None, False
        candidates = [entry for entry in self.entries if entry.kind == kind]
        for entry in candidates:
            if entry.normalised == key:
                return entry, False
        if not approximate:
            return None, False
        bestEntry, bestRatio = None, 0.0
        for entry in candidates:
            ratio = difflib.SequenceMatcher(None, key, entry.normalised).ratio()
            if ratio > bestRatio:
                bestEntry, bestRatio = entry, ratio
        if bestEntry is not None and bestRatio >= SIMILARITY_THRESHOLD:
            logger.info('Answer memory: approximate match (%.2f) "%s" ~ "%s"', bestRatio, label, bestEntry.label)
            return bestEntry, True
        return None, False

    def get(self, entry_id: str) -> RememberedAnswer | None:
        '''The entry with this id, or None.'''
        return next((entry for entry in self.entries if entry.id == entry_id), None)

    def list(self, state: str | None = None) -> list[RememberedAnswer]:
        '''All entries, or only those in `state`, newest first.'''
        selected = [entry for entry in self.entries if state is None or entry.state == state]
        return sorted(selected, key=lambda entry: entry.updated_at, reverse=True)

    def pending_count(self) -> int:
        '''How many remembered answers still await review.'''
        return sum(1 for entry in self.entries if entry.state == "pending")

    # ------------------------------------------------------------------ changes
    def _touch(self, entry: RememberedAnswer, job_link: str | None = None) -> None:
        '''Stamp an entry as changed (and used on `job_link`, if given), then persist.'''
        if job_link:
            entry.last_job_link = job_link
        entry.updated_at = _now()
        self.save()

    def remember(self, label: str, kind: str, answer: str, source: str, job_link: str | None = None) -> RememberedAnswer:
        '''
        Store an answer. An answer the user gave is `approved`; anything else is `pending`.
        If an exact entry already exists for this question it is updated instead of
        duplicated, except that only the user can replace an approved answer.
        '''
        if kind not in KINDS: raise ValueError(f"Unknown control kind {kind!r}")
        if source not in SOURCES: raise ValueError(f"Unknown answer source {source!r}")
        state = "approved" if source == "user" else "pending"
        key = normalise(label)
        existing = next((entry for entry in self.entries if entry.kind == kind and entry.normalised == key), None)
        if existing is not None:
            if source != "user" and existing.state == "approved":
                return existing             # the user's word stands; nothing else overrides it
            existing.answer = answer
            existing.source = source
            existing.state = state
            self._touch(existing, job_link)
            return existing
        # `uses` starts at 0: remembering is not using. Callers count a use with record_use().
        entry = RememberedAnswer(label=label, kind=kind, answer=answer, source=source, state=state,
                                 last_job_link=job_link or "")
        self.entries.append(entry)
        self.save()
        return entry

    def record_use(self, entry: RememberedAnswer, job_link: str | None = None) -> None:
        '''Count one more use of a remembered answer, on `job_link` if given.'''
        live = self.get(entry.id)           # the live copy: the file may have been reloaded since
        if live is None:                    # deleted in the review queue meanwhile; nothing to count
            return
        live.uses += 1
        self._touch(live, job_link)

    def approve(self, entry_id: str, answer: str | None = None) -> RememberedAnswer | None:
        '''
        Mark an entry approved, optionally replacing its answer first. Approving as-is keeps
        who gave the answer (the AI stays the author, vetted by the user); a corrected answer
        is the user's. None if the id is unknown.
        '''
        entry = self.get(entry_id)
        if entry is None:
            return None
        if answer is not None and answer != entry.answer:
            entry.answer = answer
            entry.source = "user"
        entry.state = "approved"
        self._touch(entry)
        return entry

    def delete(self, entry_id: str) -> bool:
        '''Forget an entry. True if something was removed.'''
        kept = [entry for entry in self.entries if entry.id != entry_id]
        removed = len(kept) != len(self.entries)
        if removed:
            self._entries = kept
            self.save()
        return removed

    def delete_all(self, state: str) -> int:
        '''Forget every entry in `state` (e.g. clear the whole pending queue). Returns how many.'''
        kept = [entry for entry in self.entries if entry.state != state]
        removed = len(self.entries) - len(kept)
        if removed:
            self._entries = kept
            self.save()
        return removed
