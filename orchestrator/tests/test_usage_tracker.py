import sys
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import usage_tracker as ut
import ledger


@pytest.fixture
def repo():
    name = f"test/usage-{uuid.uuid4().hex[:8]}"
    yield name
    conn = ledger._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usage_daily WHERE repo = %s", (name,))
        conn.commit()
    finally:
        conn.close()


def test_record_usage_increments(repo):
    assert ut.record_usage(repo, "codex_review") == 1
    assert ut.record_usage(repo, "codex_review") == 2
    assert ut.get_today_count(repo, "codex_review") == 2


def test_below_threshold_no_notification(repo, monkeypatch):
    monkeypatch.setenv("CODEX_DAILY_WARN_THRESHOLD", "10")
    monkeypatch.setenv("CODEX_DAILY_CRITICAL_THRESHOLD", "20")
    with patch("usage_tracker.notifier.send_telegram_message") as mock_send:
        triggered = ut.check_and_notify_thresholds(repo, "codex_review", count=5)
    assert triggered == []
    mock_send.assert_not_called()


def test_warn_threshold_notifies_once(repo, monkeypatch):
    monkeypatch.setenv("CODEX_DAILY_WARN_THRESHOLD", "10")
    monkeypatch.setenv("CODEX_DAILY_CRITICAL_THRESHOLD", "20")
    with patch("usage_tracker.notifier.send_telegram_message") as mock_send:
        first = ut.check_and_notify_thresholds(repo, "codex_review", count=10)
        second = ut.check_and_notify_thresholds(repo, "codex_review", count=12)
    assert first == ["warn"]
    assert second == []  # aynı gün, aynı tier — tekrar bildirmemeli
    mock_send.assert_called_once()


def test_critical_threshold_notifies_both_tiers_first_time(repo, monkeypatch):
    monkeypatch.setenv("CODEX_DAILY_WARN_THRESHOLD", "10")
    monkeypatch.setenv("CODEX_DAILY_CRITICAL_THRESHOLD", "20")
    with patch("usage_tracker.notifier.send_telegram_message") as mock_send:
        triggered = ut.check_and_notify_thresholds(repo, "codex_review", count=25)
    assert set(triggered) == {"warn", "critical"}
    assert mock_send.call_count == 2


def test_empty_env_falls_back_to_default(repo, monkeypatch):
    monkeypatch.setenv("CODEX_DAILY_WARN_THRESHOLD", "")
    monkeypatch.delenv("CODEX_DAILY_CRITICAL_THRESHOLD", raising=False)
    assert ut._warn_threshold() == ut.DEFAULT_WARN_THRESHOLD
    assert ut._critical_threshold() == ut.DEFAULT_CRITICAL_THRESHOLD
