from datetime import date
from pathlib import Path
import sys

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core import analysis_task_state


class _FakeRow:
    def __init__(self, status="idle"):
        self.status = status
        self.status_message = ""
        self.run_mode = ""
        self.started_at = None
        self.finished_at = None
        self.updated_at = None


class _FakeQuery:
    def __init__(self, session):
        self.session = session
        self.predicates = []

    def filter(self, *predicates):
        self.predicates.extend(predicates)
        return self

    def first(self):
        return self.session.row


class _FakeSession:
    def __init__(self, row=None):
        self.row = row
        self.queries = []
        self.added = []
        self.commits = 0
        self.refreshed = []

    def query(self, model):
        self.queries.append(model)
        return _FakeQuery(self)

    def add(self, row):
        self.added.append(row)
        self.row = row

    def commit(self):
        self.commits += 1

    def refresh(self, row):
        self.refreshed.append(row)


def test_get_task_status_does_not_clear_stale_rows(monkeypatch):
    session = _FakeSession(row=_FakeRow(status="running"))
    monkeypatch.setattr(
        analysis_task_state,
        "_delete_stale_task_states",
        lambda *args, **kwargs: pytest.fail("should not delete stale rows on status lookup"),
    )
    monkeypatch.setattr(analysis_task_state, "shanghai_today", lambda now=None: date(2026, 6, 15))

    status, status_date = analysis_task_state.get_task_status_for_code(session, "600089")

    assert status == "running"
    assert status_date == date(2026, 6, 15)
    assert session.commits == 0


def test_upsert_task_status_does_not_clear_stale_rows(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(
        analysis_task_state,
        "_delete_stale_task_states",
        lambda *args, **kwargs: pytest.fail("should not delete stale rows during upsert"),
    )
    monkeypatch.setattr(analysis_task_state, "shanghai_today", lambda now=None: date(2026, 6, 15))

    row = analysis_task_state.upsert_task_status(
        session,
        stock_code="600089",
        status="running",
        run_mode="interactive",
    )

    assert row.status == "running"
    assert row.run_mode == "interactive"
    assert session.commits == 1
    assert session.added == [row]
