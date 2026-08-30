#!/usr/bin/env python3
"""
router.py

Bir PR'in değişen dosyalarına bakarak statik kurallarla risk seviyesi
hesaplar. Risk seviyesi hiçbir zaman denetimi AZALTMAK için kullanılmaz,
yalnızca ARTIRMAK için bir taban (minimum) belirler.

Fail-closed kural: risk hesaplanamazsa (path tanınamaz, git komutu
başarısız olur, beklenmedik hata olur) varsayılan seviye CRITICAL'dir.
LOW asla varsayılan değildir.

ÖNEMLİ (Codex review bulgusu — P1): Eskiden tanınmayan bir dosya (hiçbir
PATH_RULES deseniyle eşleşmeyen) sessizce 0 puan alıp LOW'a düşüyordu —
`.github/workflows/ci.yml`, `scripts/verify_ac_lock.sh`,
`src/middleware.ts` gibi kritik dosyalar bile. Artık yalnızca AÇIKÇA
"düşük riskli" sayılan dosya kalıpları (dokümantasyon, lisans vb.) sıfır
puan alıyor — geri kalan HER dosya en az NORMAL'e zorlayan bir taban puan
alır. Ayrıca pipeline'ın KENDİSİNİ kontrol eden dosyalar (.github/workflows/,
orchestrator/, scripts/, AC dosyaları) artık açıkça HIGH/CRITICAL puanlanıyor.

Bağımlılık dosyası tespiti de artık yalnızca kök dizindeki tam yol eşitliğine
değil, HERHANGİ bir alt dizindeki dosya adına bakıyor (monorepo'da
`backend/requirements.txt` gibi yollar eskiden kaçırılıyordu).

Kullanım:
    python3 router.py --base origin/main --head HEAD
    python3 router.py --files file1.py file2.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

# Risk seviyeleri, artan sırada
RISK_LEVELS = ["LOW", "NORMAL", "HIGH", "CRITICAL"]

# Path bazlı puanlama kuralları — (path parçası, puan)
PATH_RULES: list[tuple[str, int]] = [
    ("auth/", 50),
    ("payment/", 50),
    ("webhook/", 40),
    ("migrations/", 35),
    ("database/", 30),
    ("security/", 30),
    # Pipeline'ın KENDİSİNİ kontrol eden dosyalar — bunlar tanınmayan bir
    # dosyadan daha da riskli, çünkü denetim mekanizmasının ta kendisi.
    (".github/workflows/", 40),
    ("orchestrator/", 50),
    ("scripts/", 35),
    ("acceptance_criteria.yaml", 30),
]

# Puan eşikleri -> risk seviyesi
SCORE_THRESHOLDS: list[tuple[int, str]] = [
    (50, "CRITICAL"),
    (30, "HIGH"),
    (10, "NORMAL"),
    (0, "LOW"),
]

DEPENDENCY_FILES = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "requirements.txt", "pyproject.toml", "poetry.lock", "Pipfile.lock",
}

# Yalnızca bu kalıplarla eşleşen dosyalar "gerçekten düşük riskli" sayılır
# ve taban puan (BASELINE_UNKNOWN_FILE_SCORE) almaz. Her şey burada
# DEĞİLSE (tanınmayan bir dosya dahil) en az NORMAL'e zorlanır —
# "LOW'u yalnızca açıkça izin verilen dosyalara ver" ilkesi (Codex review
# bulgusu). Bilinçli olarak dar tutuldu: specs/dod.md gibi politika
# dosyaları burada YOK çünkü onlar da önemli.
LOW_RISK_ALLOWLIST_PATTERNS = [
    re.compile(r"\.md$", re.IGNORECASE),
    re.compile(r"^LICENSE(\.[a-z]+)?$", re.IGNORECASE),
    re.compile(r"^\.gitignore$"),
    re.compile(r"^\.editorconfig$"),
    re.compile(r"^docs/"),
]

# Tanınmayan/allowlist dışı her dosya için taban puan — tek başına NORMAL
# eşiğine (10) ulaştırır, birden fazla tanınmayan dosya birikirse HIGH'a
# doğru iter (kasıtlı: "sessizce LOW'a düşme" riskini kapatmak için).
BASELINE_UNKNOWN_FILE_SCORE = 10


@dataclass
class RiskResult:
    level: str
    score: int
    reasons: list[str] = field(default_factory=list)
    fail_closed: bool = False


def get_changed_files(base: str, head: str) -> list[str]:
    """git diff ile değişen dosya listesini döndürür."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        capture_output=True, text=True, check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def get_diff_stats(base: str, head: str) -> int:
    """Toplam değişen satır sayısını döndürür (ekleme + silme)."""
    result = subprocess.run(
        ["git", "diff", "--shortstat", f"{base}...{head}"],
        capture_output=True, text=True, check=True,
    )
    total = 0
    for token in result.stdout.replace(",", "").split():
        if token.isdigit():
            total += int(token)
    return total


def _is_low_risk_allowlisted(f: str) -> bool:
    return any(p.search(f) for p in LOW_RISK_ALLOWLIST_PATTERNS)


def score_files(files: list[str], total_changed_lines: int) -> RiskResult:
    """Dosya listesine ve değişen satır sayısına göre risk puanı hesaplar."""
    score = 0
    reasons: list[str] = []

    for f in files:
        f_lower = f.lower()
        matched_specific_rule = False

        for pattern, points in PATH_RULES:
            if pattern in f_lower:
                score += points
                reasons.append(f"{f} -> +{points} ({pattern.rstrip('/')})")
                matched_specific_rule = True
        if f_lower.startswith("api/") or "/api/" in f_lower:
            score += 25
            reasons.append(f"{f} -> +25 (API sözleşmesi)")
            matched_specific_rule = True
        if os.path.basename(f) in DEPENDENCY_FILES:
            score += 20
            reasons.append(f"{f} -> +20 (dependency değişikliği)")
            matched_specific_rule = True

        if not matched_specific_rule and not _is_low_risk_allowlisted(f):
            score += BASELINE_UNKNOWN_FILE_SCORE
            reasons.append(
                f"{f} -> +{BASELINE_UNKNOWN_FILE_SCORE} (tanınmayan dosya, "
                "allowlist'te değil — fail-closed taban puan)"
            )

    if total_changed_lines > 500:
        score += 10
        reasons.append(f">500 satır değişikliği -> +10 ({total_changed_lines} satır)")
    elif total_changed_lines > 100:
        score += 10
        reasons.append(f">100 satır değişikliği -> +10 ({total_changed_lines} satır)")

    level = "LOW"
    for threshold, lvl in SCORE_THRESHOLDS:
        if score >= threshold:
            level = lvl
            break

    return RiskResult(level=level, score=score, reasons=reasons)


def fail_closed_result(reason: str) -> RiskResult:
    """Hata durumunda kullanılan güvenli varsayılan: CRITICAL."""
    return RiskResult(
        level="CRITICAL",
        score=-1,
        reasons=[f"FAIL-CLOSED: {reason}"],
        fail_closed=True,
    )


def compute_risk(base: str | None, head: str | None, files: list[str] | None) -> RiskResult:
    """
    Ana giriş noktası. base/head verilirse git diff kullanılır,
    files verilirse doğrudan o liste kullanılır (lokal test için).
    Herhangi bir hata durumunda fail-closed (CRITICAL) döner.
    """
    try:
        if files is not None:
            return score_files(files, total_changed_lines=0)

        if not base or not head:
            return fail_closed_result("base/head veya files parametresi eksik")

        changed_files = get_changed_files(base, head)
        if not changed_files:
            return fail_closed_result("değişen dosya listesi boş döndü (beklenmeyen durum)")

        total_lines = get_diff_stats(base, head)
        return score_files(changed_files, total_lines)

    except subprocess.CalledProcessError as e:
        return fail_closed_result(f"git komutu başarısız oldu: {e}")
    except Exception as e:  # noqa: BLE001 — kasıtlı olarak geniş: hiçbir hata LOW'a düşmemeli
        return fail_closed_result(f"beklenmeyen hata: {e}")


def required_checks_for(level: str) -> list[str]:
    """Risk seviyesine göre zorunlu denetim adımlarını döndürür."""
    mapping = {
        "LOW": ["ci"],
        "NORMAL": ["ci", "codex_review"],
        "HIGH": ["ci", "codex_review", "human_approval"],
        "CRITICAL": ["ci", "codex_review", "extra_security_scan", "human_approval"],
    }
    return mapping.get(level, mapping["CRITICAL"])  # tanınmayan seviye de CRITICAL davranır


def main() -> int:
    parser = argparse.ArgumentParser(description="PR risk seviyesi hesaplayıcı")
    parser.add_argument("--base", help="Karşılaştırma taban referansı (ör. origin/main)")
    parser.add_argument("--head", help="Karşılaştırma uç referansı (ör. HEAD)")
    parser.add_argument("--files", nargs="*", help="Doğrudan dosya listesi (git olmadan test için)")
    parser.add_argument("--json", action="store_true", help="Çıktıyı JSON olarak ver")
    args = parser.parse_args()

    result = compute_risk(args.base, args.head, args.files)
    required = required_checks_for(result.level)

    output = {
        "risk_level": result.level,
        "score": result.score,
        "fail_closed": result.fail_closed,
        "required_checks": required,
        "reasons": result.reasons,
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"RISK_LEVEL={result.level}")
        print(f"SCORE={result.score}")
        print(f"REQUIRED_CHECKS={','.join(required)}")
        if result.fail_closed:
            print("UYARI: fail-closed devreye girdi, seviye CRITICAL olarak zorlandı.")
        for r in result.reasons:
            print(f"  - {r}")

    # GitHub Actions çıktısı (varsa) — $GITHUB_OUTPUT dosyasına yazılır
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"risk_level={result.level}\n")
            f.write(f"required_checks={','.join(required)}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
