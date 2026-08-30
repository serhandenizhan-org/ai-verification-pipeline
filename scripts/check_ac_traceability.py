#!/usr/bin/env python3
"""
check_ac_traceability.py — Codex'in önerdiği özellik: hangi AC'nin hangi
test/kanıtla karşılandığını izler. "Testler yeşil ama özellik eksik"
sorununu azaltmak için.

NASIL ÇALIŞIR: `acceptance_criteria.yaml` kilitli bir dosyadır (hash'i
Postgres'te, bkz. ac_lock.py) — Builder implementasyon SIRASINDA/SONRASINDA
hangi testin hangi AC'yi kanıtladığını bu dosyaya YAZAMAZ (hash'i bozar).
Bu yüzden kanıt eşlemesi AYRI, kilitlenmeyen bir dosyada tutulur:

    specs/features/<feature>/evidence.yaml
    AC-01: "tests/test_admin.py::test_delete_removes_r2_object"
    AC-02: "tests/test_admin.py::test_duplicate_rejected"

Bu script HER İKİ dosyayı okuyup hangi AC'lerin kanıtsız kaldığını
raporlar. **ADVISORY'dir, asla FAIL/exit 1 vermez** — verification-gate'i
bloklamaz, yalnızca bir sinyal/hatırlatmadır (DoD'nin "AC-test eşlemesi"
maddesine kanıt sağlar).

Kullanım:
    python3 scripts/check_ac_traceability.py
"""

from __future__ import annotations

import glob
import re
import sys
from pathlib import Path


def extract_ac_ids(ac_file: Path) -> list[str]:
    ids = []
    for line in ac_file.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*-\s*id:\s*(AC-\S+)", line)
        if m:
            ids.append(m.group(1))
    return ids


def extract_evidence(evidence_file: Path) -> dict[str, str]:
    if not evidence_file.exists():
        return {}
    data: dict[str, str] = {}
    for line in evidence_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^(AC-\S+):\s*"?([^"\n]+?)"?\s*$', line)
        if m:
            data[m.group(1)] = m.group(2)
    return data


def main() -> int:
    ac_files = sorted(glob.glob("specs/features/*/acceptance_criteria.yaml"))
    if not ac_files:
        print("Hiç acceptance_criteria.yaml bulunamadı.")
        return 0

    any_missing = False
    for ac_path in ac_files:
        ac_file = Path(ac_path)
        feature_dir = ac_file.parent
        ids = extract_ac_ids(ac_file)
        evidence = extract_evidence(feature_dir / "evidence.yaml")
        missing = [i for i in ids if not evidence.get(i, "").strip()]

        if not ids:
            continue

        if missing:
            any_missing = True
            print(f"⚠️  {feature_dir.name}: {len(ids) - len(missing)}/{len(ids)} AC kanıtlı — eksik: {', '.join(missing)}")
        else:
            print(f"✅ {feature_dir.name}: tüm {len(ids)} AC'nin kanıtı var")

    if any_missing:
        print("\n(Bu bir ADVISORY sinyaldir — merge'ü bloklamaz. "
              "specs/features/<feature>/evidence.yaml'a AC->test eşlemesi ekleyin.)")
    return 0  # ADVISORY — her zaman 0


if __name__ == "__main__":
    sys.exit(main())
