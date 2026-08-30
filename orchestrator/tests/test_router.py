"""
test_router.py — router.py'nin risk sınıflandırma mantığı için regresyon
testleri.

Bu testler, Codex'in P1 review bulgusunu ("tanınmayan/kritik dosyalar
yanlışlıkla LOW oluyor") kanıtlamak için bu oturumda elle çalıştırılan
senaryoların otomatikleştirilmiş halidir — DoD'nin "pipeline'ın kendi
kodu için test takımı yok" (P2) maddesini kapatmanın ilk adımı.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import router  # noqa: E402


def test_unrecognized_file_is_not_low():
    """Codex review bulgusu: eskiden tanınmayan dosyalar sessizce LOW'a düşüyordu."""
    result = router.score_files(["src/middleware.ts"], total_changed_lines=0)
    assert result.level != "LOW"
    assert result.level == "NORMAL"


def test_pipeline_control_files_are_high_or_above():
    """Pipeline'ın kendi kontrol yüzeyi (.github/workflows, orchestrator/, scripts/)."""
    for f, expected_min_level in [
        (".github/workflows/ci.yml", "HIGH"),
        ("scripts/verify_ac_lock.sh", "HIGH"),
        ("orchestrator/requirements.txt", "CRITICAL"),
    ]:
        result = router.score_files([f], total_changed_lines=0)
        assert result.level in ("HIGH", "CRITICAL"), f"{f} -> {result.level} (en az {expected_min_level} olmalıydı)"


def test_nested_dependency_file_detected():
    """Codex review bulgusu: bağımlılık dosyası tespiti tam yol eşitliği kullanıyordu, alt dizinleri kaçırıyordu."""
    result = router.score_files(["backend/requirements.txt"], total_changed_lines=0)
    assert result.score >= 20  # BASELINE_UNKNOWN_FILE_SCORE (10) + dependency (20) -- backend/ prefix engellemez


def test_genuinely_low_risk_file_stays_low():
    """Allowlist doğru çalışıyor mu — regresyonu önlemek için."""
    result = router.score_files(["README.md"], total_changed_lines=0)
    assert result.level == "LOW"
    assert result.score == 0


def test_known_critical_path_still_critical():
    result = router.score_files(["auth/login.py"], total_changed_lines=0)
    assert result.level == "CRITICAL"


def test_git_error_fails_closed_to_critical():
    result = router.compute_risk("nonexistent-base-ref-xyz", "HEAD", None)
    assert result.level == "CRITICAL"
    assert result.fail_closed is True
