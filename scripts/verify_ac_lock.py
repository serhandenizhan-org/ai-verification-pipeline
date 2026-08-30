#!/usr/bin/env python3
"""
verify_ac_lock.py — CI'da çalışır. Her "locked"/"implemented" statüsündeki
acceptance_criteria.yaml dosyasının hash'ini yeniden hesaplar ve Postgres'teki
BAĞIMSIZ kilit kaydıyla (dosyanın kendi beyanıyla DEĞİL) karşılaştırır.

NEDEN dosyanın kendi `locked_hash` alanına değil Postgres'e bakıyoruz
(Codex review bulgusu): Dosyanın içindeki `locked_hash` alanı, dosyanın
kendisiyle birlikte değiştirilebilir — bu "onaylandı" kanıtı değildir.
Ayrıca şunları da kontrol ediyoruz (eski script bunları YAKALAMIYORDU):

  - `status`'u `locked`'dan `draft`'a çevirmek: Postgres'te kilit kaydı
    olan bir feature'ın dosyası artık locked/implemented değilse BLOCKING.
  - Dosyayı tamamen silmek: Postgres'te kilit kaydı olan bir feature'ın
    dosyası hiç yoksa BLOCKING.

Kullanım (CI içinde):
    python3 scripts/verify_ac_lock.py
"""

from __future__ import annotations

import glob
import hashlib
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
import ac_lock  # noqa: E402


def _compute_hash(ac_file: Path) -> str:
    lines = [
        line for line in ac_file.read_text(encoding="utf-8").splitlines(keepends=True)
        if not line.startswith("locked_hash:")
    ]
    content = "".join(lines).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _extract_status(ac_file: Path) -> str | None:
    for line in ac_file.read_text(encoding="utf-8").splitlines():
        m = re.match(r'^status:\s*"?([^"\n]*)"?\s*$', line)
        if m:
            return m.group(1)
    return None


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print("HATA: GITHUB_REPOSITORY tanımlı değil — repo bilinmeden AC lock "
              "doğrulanamaz (fail-closed).", file=sys.stderr)
        return 1

    failed = False

    on_disk: dict[str, Path] = {}
    for path_str in glob.glob("specs/features/*/acceptance_criteria.yaml"):
        ac_file = Path(path_str)
        feature = ac_file.parent.name
        on_disk[feature] = ac_file

        status = _extract_status(ac_file)
        if status not in ("locked", "implemented"):
            continue  # henüz kilitlenmemiş dosyalar serbestçe düzenlenebilir

        record = ac_lock.get_latest_lock(repo, feature)
        if record is None:
            print(f"HATA: {ac_file} statüsü '{status}' ama Postgres'te HİÇ kilit kaydı yok!", file=sys.stderr)
            print("  Bu dosya lock_ac.sh üzerinden DEĞİL, elle 'locked' yapılmış olabilir.", file=sys.stderr)
            failed = True
            continue

        actual_hash = _compute_hash(ac_file)
        if actual_hash != record.locked_hash:
            print(f"HATA: {ac_file} kilitlendikten sonra değiştirilmiş!", file=sys.stderr)
            print(f"  Beklenen hash (Postgres, {record.locked_by}): {record.locked_hash}", file=sys.stderr)
            print(f"  Bulunan hash (dosya):                        {actual_hash}", file=sys.stderr)
            print("  Bu dosya yalnızca Şef onayıyla ve lock_ac.sh ile değiştirilebilir.", file=sys.stderr)
            failed = True

    # Postgres'te kilitli olduğu bilinen ama artık dosya sisteminde ya
    # locked/implemented olmayan ya da hiç bulunmayan feature'lar
    for feature in ac_lock.list_locked_features(repo):
        ac_file = on_disk.get(feature)
        if ac_file is None:
            print(f"HATA: '{feature}' Postgres'te kilitli görünüyor ama "
                  f"specs/features/{feature}/acceptance_criteria.yaml artık YOK (silinmiş)!", file=sys.stderr)
            failed = True
            continue
        status = _extract_status(ac_file)
        if status not in ("locked", "implemented"):
            print(f"HATA: '{feature}' Postgres'te kilitli ama dosyanın status'u "
                  f"'{status}' — kilit sonrası status değiştirilmiş olabilir!", file=sys.stderr)
            failed = True

    if failed:
        print("", file=sys.stderr)
        print("AC lock ihlali tespit edildi — build durduruldu, Şef'e escalate edilmeli.", file=sys.stderr)
        return 1

    print("Tüm kilitli AC dosyaları bütün — değişiklik yok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
