#!/usr/bin/env bash
#
# pin_trusted_files.sh — CI, PR'ın checkout edilmiş kopyasında Codex'in
# OKUYACAĞI (çalıştırmayacağı — çalıştırılanlar artık ayrı, bkz. aşağı)
# davranış dosyalarını (AGENTS.md, severity_rules.md) ezmek için kullanılır.
#
# KAPSAM DEĞİŞTİ: orchestrator/*.py ve scripts/*.py artık burada EZİLMİYOR.
# Codex review bulgusu: aynı dizinde çalıştırılan Python script'leri için
# dosya bazlı "ezme" yeterli değil — Python, çalıştırılan script'in kendi
# dizinini sys.path'in başına koyduğundan, PR yeni bir sibling modül
# ekleyerek (ör. orchestrator/argparse.py) ezilmiş/pinlenmiş dosyaların
# import ettiği modülleri gölgeleyebilir (gerçek saldırı ile test edildi).
# Bu risk artık scripts/stage_trusted_orchestrator.sh ile çözülüyor —
# Python KODU PR checkout'unun tamamen DIŞINDAN çalıştırılıyor.
#
# BU SCRIPT yalnızca Codex'in DOĞRUDAN OKUDUĞU (çalıştırmadığı) doğal dil
# dosyaları için kalıyor — çünkü sys.path shadowing riski yalnızca
# ÇALIŞTIRILAN Python koduna özgü, AGENTS.md gibi metin dosyaları için
# risk farklı (prompt injection) ve in-place ezme bunun için yeterli.
#
# Kullanım (checkout'tan hemen sonra, `codex` çağrılmadan önce):
#   bash scripts/pin_trusted_files.sh

set -euo pipefail

TRUSTED_FILES=(
  "AGENTS.md"
  "verification/codex/severity_rules.md"
)

for f in "${TRUSTED_FILES[@]}"; do
  if git show "origin/main:${f}" > "${f}.trusted_tmp" 2>/dev/null; then
    mv "${f}.trusted_tmp" "$f"
    echo "pinned: $f <- origin/main"
  else
    rm -f "${f}.trusted_tmp"
    echo "uyarı: origin/main'de bulunamadı, atlandı: $f" >&2
  fi
done
