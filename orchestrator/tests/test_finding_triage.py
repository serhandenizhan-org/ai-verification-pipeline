import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import finding_triage as ft
import ledger


@pytest.fixture
def repo():
    name = f"test/finding-triage-{uuid.uuid4().hex[:8]}"
    yield name
    conn = ledger._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM finding_history WHERE repo = %s", (name,))
        conn.commit()
    finally:
        conn.close()


REPORT_V1 = """
- [P1] SQL injection risk — db.py:42
- [P2] Missing docstring — utils.py:10
"""

REPORT_V2 = """
- [P1] SQL injection risk — db.py:42
- [P1] New unrelated finding — auth.py:7
"""


def test_new_finding_recorded_as_new(repo):
    findings = ft.parse_findings(REPORT_V1)
    result = ft.record_findings(repo, findings)
    assert all(v["is_new"] for v in result.values())
    assert all(v["occurrence_count"] == 1 for v in result.values())


def test_repeated_finding_increments_occurrence(repo):
    findings = ft.parse_findings(REPORT_V1)
    ft.record_findings(repo, findings)
    result = ft.record_findings(repo, findings)
    assert all(not v["is_new"] for v in result.values())
    assert all(v["occurrence_count"] == 2 for v in result.values())


def test_unaccepted_blocking_counts_p1_only(repo):
    findings = ft.parse_findings(REPORT_V2)
    ft.record_findings(repo, findings)
    assert ft.unaccepted_blocking_count(repo, findings) == 2


def test_accepted_finding_excluded_from_unaccepted_blocking(repo):
    findings = ft.parse_findings(REPORT_V2)
    ft.record_findings(repo, findings)
    target = findings[0]
    ok = ft.accept_finding(repo, target.fingerprint, "sef", "yanlış pozitif, kod incelendi")
    assert ok
    assert ft.unaccepted_blocking_count(repo, findings) == 1


def test_accept_unknown_fingerprint_returns_false(repo):
    assert ft.accept_finding(repo, "deadbeefcafef00d", "sef", "test") is False


def test_accept_requires_non_empty_accepted_by(repo):
    with pytest.raises(ValueError):
        ft.accept_finding(repo, "deadbeefcafef00d", "", "test")
