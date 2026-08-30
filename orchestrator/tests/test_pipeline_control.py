import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import pipeline_control as pc
import ledger


@pytest.fixture
def repo():
    name = f"test/pipeline-control-{uuid.uuid4().hex[:8]}"
    yield name
    conn = ledger._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pipeline_control WHERE repo = %s", (name,))
        conn.commit()
    finally:
        conn.close()


def test_not_stopped_by_default(repo):
    stopped, reason = pc.is_stopped(repo)
    assert stopped is False
    assert reason is None


def test_set_stopped(repo):
    pc.set_stopped(repo, "sef", "acil durum")
    stopped, reason = pc.is_stopped(repo)
    assert stopped is True
    assert reason == "acil durum"


def test_clear_stopped(repo):
    pc.set_stopped(repo, "sef", "acil durum")
    ok = pc.clear_stopped(repo, "sef")
    assert ok is True
    stopped, _ = pc.is_stopped(repo)
    assert stopped is False


def test_clear_stopped_when_not_stopped_returns_false(repo):
    assert pc.clear_stopped(repo, "sef") is False


def test_set_stopped_requires_non_empty_stopped_by(repo):
    with pytest.raises(ValueError):
        pc.set_stopped(repo, "", "acil durum")


def test_clear_stopped_requires_non_empty_resumed_by(repo):
    pc.set_stopped(repo, "sef", "acil durum")
    with pytest.raises(ValueError):
        pc.clear_stopped(repo, "")
