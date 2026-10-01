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
SOURCES = ("ai", "user")
STATES = ("pending", "approved")
SIMILARITY_THRESHOLD = 0.92

_NON_WORD = re.compile(r"[^a-z0-9\s]+")
_SPACES = re.compile(r"\s+")


def normalise(label: str) -> str:
    '''Lowercase, drop punctuation, collapse whitespace: the key half of a remembered answer.'''
    lowered = (label or "").lower()
    return _SPACES.sub(" ", _NON_WORD.sub(" ", lowered)).strip()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class RememberedAnswer:
    '''One entry in the answer memory. `answer` is the visible text; for a checkbox it is "checked".'''
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
        if not self.normalised:
            self.normalised = normalise(self.label)

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

    # ------------------------------------------------------------------ storage
    @property
    def entries(self) -> list[RememberedAnswer]:
        '''All remembered answers, loading the file on first access.'''
        if self._entries is None:
            self._entries = self._load()
        return self._entries

    def _load(self) -> list[RememberedAnswer]:
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
        payload = {"version": 1, "answers": [asdict(entry) for entry in self.entries]}
        temporaryPath = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with open(temporaryPath, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2, ensure_ascii=False)
            os.replace(temporaryPath, self.path)
        except OSError as error:
            logger.warning("Could not save the answer memory to %s (%s).", self.path, error)

    # ------------------------------------------------------------------ queries
    def lookup(self, label: str, kind: str) -> tuple[RememberedAnswer | None, bool]:
        '''
        The remembered answer for `label` in a control of `kind`, and whether the match was
        approximate. Exact match on the normalised label first; otherwise the most similar
        entry of the same kind at or above SIMILARITY_THRESHOLD. (None, False) when nothing fits.
        '''
        key = normalise(label)
        if not key:
            return None, False
        candidates = [entry for entry in self.entries if entry.kind == kind]
        for entry in candidates:
            if entry.normalised == key:
                return entry, False
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
    def remember(self, label: str, kind: str, answer: str, source: str, job_link: str | None = None) -> RememberedAnswer:
        '''
        Store an answer. An AI answer is `pending`; an answer the user gave is `approved`.
        If an exact entry already exists for this question, its answer is replaced instead of
        adding a duplicate; a user answer also approves it.
        '''
        if kind not in KINDS: raise ValueError(f"Unknown control kind {kind!r}")
        if source not in SOURCES: raise ValueError(f"Unknown answer source {source!r}")
        state = "approved" if source == "user" else "pending"
        key = normalise(label)
        existing = next((entry for entry in self.entries if entry.kind == kind and entry.normalised == key), None)
        if existing is not None:
            existing.answer = answer
            existing.source = source
            if source == "user":
                existing.state = "approved"
            existing.updated_at = _now()
            if job_link:
                existing.last_job_link = job_link
            self.save()
            return existing
        entry = RememberedAnswer(label=label, kind=kind, answer=answer, source=source, state=state,
                                 uses=1 if job_link else 0, last_job_link=job_link or "")
        self.entries.append(entry)
        self.save()
        return entry

    def record_use(self, entry: RememberedAnswer, job_link: str | None = None) -> None:
        '''Count one more use of a remembered answer, on `job_link` if given.'''
        entry.uses += 1
        if job_link:
            entry.last_job_link = job_link
        entry.updated_at = _now()
        self.save()

    def approve(self, entry_id: str, answer: str | None = None) -> RememberedAnswer | None:
        '''Mark an entry approved, optionally replacing its answer first. None if the id is unknown.'''
        entry = self.get(entry_id)
        if entry is None:
            return None
        if answer is not None:
            entry.answer = answer
        entry.state = "approved"
        entry.source = "user"
        entry.updated_at = _now()
        self.save()
        return entry

    def delete(self, entry_id: str) -> bool:
        '''Forget an entry. True if something was removed.'''
        before = len(self.entries)
        self._entries = [entry for entry in self.entries if entry.id != entry_id]
        removed = len(self._entries) != before
        if removed:
            self.save()
        return removed
