import sys
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import telegram_commands as tc
import pipeline_control as pc
import finding_triage as ft
import ledger


@pytest.fixture
def repo():
    name = f"test/telegram-{uuid.uuid4().hex[:8]}"
    yield name
    conn = ledger._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pipeline_control WHERE repo = %s", (name,))
            cur.execute("DELETE FROM finding_history WHERE repo = %s", (name,))
        conn.commit()
    finally:
        conn.close()


def test_durdur_command_stops_pipeline(repo):
    with patch("telegram_commands._reply") as mock_reply:
        tc._handle_command("tok", "chat1", f"/durdur {repo} kritik sızıntı")
    stopped, reason = pc.is_stopped(repo)
    assert stopped is True
    assert reason == "kritik sızıntı"
    mock_reply.assert_called_once()


def test_devam_command_resumes_pipeline(repo):
    pc.set_stopped(repo, "sef", "test")
    with patch("telegram_commands._reply"):
        tc._handle_command("tok", "chat1", f"/devam {repo}")
    stopped, _ = pc.is_stopped(repo)
    assert stopped is False


def test_kabul_command_accepts_finding_with_expiry(repo):
    findings = ft.parse_findings("- [P1] Test finding — a.py:1")
    ft.record_findings(repo, findings)
    fp = findings[0].fingerprint
    with patch("telegram_commands._reply"):
        tc._handle_command("tok", "chat1", f"/kabul {repo} {fp} 5 gecici istisna")
    assert ft.unaccepted_blocking_count(repo, findings) == 0


def test_kabul_command_permanent(repo):
    findings = ft.parse_findings("- [P1] Test finding — a.py:1")
    ft.record_findings(repo, findings)
    fp = findings[0].fingerprint
    with patch("telegram_commands._reply"):
        tc._handle_command("tok", "chat1", f"/kabul {repo} {fp} kalici yanlis pozitif")
    assert ft.unaccepted_blocking_count(repo, findings) == 0


def test_unknown_command_replies_with_usage(repo):
    with patch("telegram_commands._reply") as mock_reply:
        tc._handle_command("tok", "chat1", "/bilinmeyen foo")
    args = mock_reply.call_args[0]
    assert "Bilinmeyen komut" in args[2]


def test_unauthorized_chat_id_ignored_in_poll_once(monkeypatch, repo):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "faketoken")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    fake_updates = {
        "result": [
            {
                "update_id": 1,
                "message": {"chat": {"id": 99999}, "text": f"/durdur {repo} saldiri"},
            }
        ]
    }
    with patch("telegram_commands._api_call", return_value=fake_updates), \
         patch("telegram_commands._reply") as mock_reply:
        tc.poll_once()

    stopped, _ = pc.is_stopped(repo)
    assert stopped is False
    mock_reply.assert_not_called()


def test_authorized_chat_id_processed_in_poll_once(monkeypatch, repo):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "faketoken")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    fake_updates = {
        "result": [
            {
                "update_id": 1,
                "message": {"chat": {"id": 12345}, "text": f"/durdur {repo} saldiri"},
            }
        ]
    }
    with patch("telegram_commands._api_call", return_value=fake_updates), \
         patch("telegram_commands._reply") as mock_reply:
        tc.poll_once()

    stopped, reason = pc.is_stopped(repo)
    assert stopped is True
    assert reason == "saldiri"
    mock_reply.assert_called_once()


def test_missing_token_is_noop(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with patch("telegram_commands._api_call") as mock_api:
        assert tc.poll_once() == 0
    mock_api.assert_not_called()
