"""
test_gate.py — verifier.py'nin `gate` komutu (TEK bağlayıcı merge kararı)
için regresyon testleri.

GEREKSİNİM: Yerel bir Postgres instance'ı çalışıyor olmalı (bkz. README
"Hızlı Kurulum"). Bu testler gerçek bir DB'ye yazıp okuyor — mock DEĞİL —
çünkü asıl risk (Codex review bulgusu) SQL/transaction sırasında ortaya
çıkan concurrency/staleness hatalarıydı, bunlar mock'lanmış bir DB ile
yakalanamazdı.

Her test kendi benzersiz repo adını kullanır ve sonunda kendi verisini
temizler (append-only ledger'a rağmen, TEST verisi için DELETE yapmak
meşrudur — gerçek üretim verisi için asla).

NOT: cmd_gate kontrol sırası breaker -> secret_leak -> trufflehog -> risk
-> codex şeklindedir (bkz. verifier.py cmd_gate docstring'i). PASS
beklenen her test bu yüzden bir `trufflehog_result: OK` olayı da eklemek
zorunda — yoksa gate, testin asıl amaçlamadığı bir adımda (trufflehog)
FAIL verir.
"""

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import circuit_breaker  # noqa: E402
import ledger  # noqa: E402
import verifier  # noqa: E402


@pytest.fixture
def repo():
    """Her test için benzersiz bir repo adı — testler birbirine karışmasın."""
    name = f"test/gate-{uuid.uuid4().hex[:8]}"
    yield name
    with ledger._connect() as conn:  # noqa: SLF001 — test temizliği için doğrudan erişim
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ledger_entries WHERE repo = %s", (name,))
            cur.execute("DELETE FROM circuit_breaker_state WHERE repo = %s", (name,))
        conn.commit()


def _gate_args(repo_name: str, pr: int, head_sha: str):
    import argparse
    return argparse.Namespace(repo=repo_name, pr=pr, head_sha=head_sha)


def _add(repo_name: str, pr: int, event: str, data: dict, head_sha: str):
    ledger.append_entry(ledger.LedgerEntry(repo=repo_name, pr=pr, event=event, data=data, head_sha=head_sha))


def _add_clean_trufflehog(repo_name: str, pr: int, head_sha: str):
    _add(repo_name, pr, "trufflehog_result", {"status": "OK", "verified_secrets_found": 0}, head_sha)


def test_gate_fails_when_nothing_computed_yet(repo):
    """Ne risk ne trufflehog hesaplanmış — Fast CI hiç çalışmamış/bitmemiş demektir."""
    result = verifier.cmd_gate(_gate_args(repo, 1, "sha1"))
    assert result == 1  # FAIL


def test_gate_passes_low_risk_without_codex(repo):
    _add_clean_trufflehog(repo, 2, "sha2")
    _add(repo, 2, "risk_computed", {"risk_level": "LOW"}, "sha2")
    result = verifier.cmd_gate(_gate_args(repo, 2, "sha2"))
    assert result == 0  # PASS


def test_gate_fails_high_risk_without_codex_result(repo):
    _add_clean_trufflehog(repo, 3, "sha3")
    _add(repo, 3, "risk_computed", {"risk_level": "HIGH"}, "sha3")
    result = verifier.cmd_gate(_gate_args(repo, 3, "sha3"))
    assert result == 1  # FAIL — Codex sonucu yok


def test_gate_passes_high_risk_with_clean_codex(repo):
    _add_clean_trufflehog(repo, 4, "sha4")
    _add(repo, 4, "risk_computed", {"risk_level": "HIGH"}, "sha4")
    _add(repo, 4, "codex_result", {"status": "PASS", "findings": {"blocking": 0}}, "sha4")
    result = verifier.cmd_gate(_gate_args(repo, 4, "sha4"))
    assert result == 0  # PASS


def test_gate_fails_on_blocking_codex_finding(repo):
    _add_clean_trufflehog(repo, 5, "sha5")
    _add(repo, 5, "risk_computed", {"risk_level": "HIGH"}, "sha5")
    _add(repo, 5, "codex_result", {"status": "PASS", "findings": {"blocking": 2}}, "sha5")
    result = verifier.cmd_gate(_gate_args(repo, 5, "sha5"))
    assert result == 1  # FAIL


def test_stale_commit_result_does_not_leak_to_new_commit(repo):
    """
    En kritik regresyon testi: eski bir commit'in PASS sonucu yeni bir
    commit'in kararını ETKİLEMEMELİ (Codex review bulgusu — ledger'ın
    repo/commit kimliği eklenmeden önceki hâli bunu garanti etmiyordu).
    """
    _add_clean_trufflehog(repo, 6, "sha6-old")
    _add(repo, 6, "risk_computed", {"risk_level": "HIGH"}, "sha6-old")
    _add(repo, 6, "codex_result", {"status": "PASS", "findings": {"blocking": 0}}, "sha6-old")
    _add(repo, 6, "risk_computed", {"risk_level": "HIGH"}, "sha6-new")
    # NOT: sha6-new için bilerek trufflehog/codex eklemedik — yeni commit
    # için hiçbir şey hesaplanmamış olmalı.
    result = verifier.cmd_gate(_gate_args(repo, 6, "sha6-new"))
    assert result == 1  # FAIL — yeni commit için trufflehog/codex sonucu yok


def test_gate_fails_when_breaker_tripped(repo):
    circuit_breaker.record_attempt(repo, 7, "aynı hata")
    circuit_breaker.record_attempt(repo, 7, "aynı hata")  # MAX_SAME_FAILURE=2 varsayılan
    _add_clean_trufflehog(repo, 7, "sha7")
    _add(repo, 7, "risk_computed", {"risk_level": "LOW"}, "sha7")
    result = verifier.cmd_gate(_gate_args(repo, 7, "sha7"))
    assert result == 1  # FAIL — breaker tripped, risk LOW olsa bile


def test_gate_fails_on_unrotated_secret_leak(repo):
    _add_clean_trufflehog(repo, 8, "sha8")
    _add(repo, 8, "risk_computed", {"risk_level": "LOW"}, "sha8")
    _add(repo, 8, "secret_alert_triggered", {"findings": []}, "sha8")
    result = verifier.cmd_gate(_gate_args(repo, 8, "sha8"))
    assert result == 1  # FAIL — risk LOW olsa bile secret leak bloklar


def test_gate_fails_when_trufflehog_never_ran(repo):
    """Codex review bulgusu: TruffleHog wiring'i olmadan gate PASS vermemeli."""
    _add(repo, 9, "risk_computed", {"risk_level": "LOW"}, "sha9")
    result = verifier.cmd_gate(_gate_args(repo, 9, "sha9"))
    assert result == 1  # FAIL — trufflehog_result event'i hiç yok


def test_gate_fails_when_trufflehog_errored(repo):
    _add(repo, 10, "trufflehog_result", {"status": "ERROR", "reason": "scan crashed"}, "sha10")
    _add(repo, 10, "risk_computed", {"risk_level": "LOW"}, "sha10")
    result = verifier.cmd_gate(_gate_args(repo, 10, "sha10"))
    assert result == 1  # FAIL
