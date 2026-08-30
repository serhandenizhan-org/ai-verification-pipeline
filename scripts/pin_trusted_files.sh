#!/usr/bin/env bash
#
# pin_trusted_files.sh — CI, bir PR'ın checkout edilmiş kopyası üzerinde
# orchestrator script'lerini VE agent davranışını kontrol eden dosyaları
# (AGENTS.md, severity_rules.md) çalıştırmadan/okumadan ÖNCE bu script
# çağrılmalıdır.
#
# NEDEN: Bu dosyalar da PR'ın bir parçası olduğu için, kötü niyetli bir PR
# şunları yapabilir:
#   - orchestrator/verifier.py'ı değiştirip runner'ın GITHUB_TOKEN'ını/
#     Postgres erişimini/Codex kimlik bilgilerini kötüye kullanmak
#   - orchestrator/requirements.txt'e zararlı bir paket ekleyip pip install
#     sırasında host'ta kod çalıştırmak (Codex review bulgusu — P1)
#   - AGENTS.md'yi değiştirip Codex'e "bulguları gizle" gibi prompt
#     injection talimatları vermek (Codex review bulgusu — P1, authenticated
#     ChatGPT kimlik bilgisiyle çalışan bir agent'a karşı özellikle ciddi)
#
# ÇÖZÜM: PR'ın diğer her şeyi (gerçek kod değişiklikleri) normal şekilde
# checkout edilip incelenir — ama bu listedeki dosyalar HER ZAMAN origin/main
# üzerindeki güvenilir versiyonla ezilir, PR ne yazarsa yazsın.
#
# Kullanım (checkout'tan hemen sonra, herhangi bir orchestrator script'i
# veya `codex` çağrılmadan önce):
#   bash scripts/pin_trusted_files.sh

set -euo pipefail

TRUSTED_FILES=(
  "orchestrator/router.py"
  "orchestrator/verifier.py"
  "orchestrator/ledger.py"
  "orchestrator/circuit_breaker.py"
  "orchestrator/notifier.py"
  "orchestrator/alert_and_rotate.py"
  "orchestrator/trufflehog_result.py"
  "orchestrator/requirements.txt"
  "orchestrator/schema.sql"
  "scripts/check_new_dependencies.py"
  "scripts/lock_ac.sh"
  "scripts/verify_ac_lock.sh"
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
