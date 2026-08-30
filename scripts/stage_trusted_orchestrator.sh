#!/usr/bin/env bash
#
# stage_trusted_orchestrator.sh — güvenilir orchestrator/script kodunu PR
# checkout'unun DIŞINDA, ayrı bir dizine kopyalar ve Python bu koddan HER
# ZAMAN o ayrı dizinden çalıştırılır.
#
# NEDEN (Codex review bulgusu): Önceki yaklaşım (pin_trusted_files.sh),
# orchestrator/*.py dosyalarını PR'ın kendi checkout'u İÇİNDE origin/main
# içeriğiyle ezip aynı yerden çalıştırıyordu. Ama bu yeterli değil — Python,
# çalıştırılan script'in kendi dizinini sys.path'in başına koyar. Yani PR,
# aynı dizine `orchestrator/argparse.py` gibi masum görünen ama stdlib'i
# gölgeleyen ya da `router.py`'nin import ettiği bir modülü taklit eden
# YENİ bir dosya eklerse, pinlenmiş/ezilmiş dosyalar bile o kötü niyetli
# sibling modülü import edebilir. Dosya bazlı "ezme" bunu kapatamaz —
# çalışma dizininin KENDİSİ PR'ın kontrolü altında olmamalı.
#
# ÇÖZÜM: Güvenilir kodu PR checkout'unun tamamen dışına (ör. $RUNNER_TEMP
# altına) kopyala, Python'u SADECE oradan çalıştır. Böylece sys.path[0]
# hiçbir zaman PR'ın kontrol ettiği bir dizin olmaz.
#
# Kullanım:
#   TRUSTED_DIR=$(git show origin/main:scripts/stage_trusted_orchestrator.sh | bash -s -- "$RUNNER_TEMP/trusted-orchestrator")
#   python3 "$TRUSTED_DIR/orchestrator/router.py" --base origin/main --head HEAD
#
# ÖNEMLİ: Bu script'in KENDİSİ de PR checkout'undan değil, doğrudan
# `git show origin/main:...` ile main'den çalıştırılmalıdır — yoksa PR bu
# script'i no-op'a çevirip izolasyonu tamamen etkisiz kılabilir.

set -euo pipefail

TARGET_DIR="${1:?Kullanım: stage_trusted_orchestrator.sh <hedef-dizin>}"

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR/orchestrator" "$TARGET_DIR/scripts"

ORCHESTRATOR_FILES=(
  "router.py"
  "verifier.py"
  "ledger.py"
  "circuit_breaker.py"
  "notifier.py"
  "alert_and_rotate.py"
  "trufflehog_result.py"
  "ac_lock.py"
  "finding_triage.py"
  "usage_tracker.py"
  "requirements.txt"
  "schema.sql"
)

SCRIPT_FILES=(
  "check_new_dependencies.py"
  "verify_ac_lock.py"
  "check_ac_traceability.py"
)

for f in "${ORCHESTRATOR_FILES[@]}"; do
  if git show "origin/main:orchestrator/${f}" > "$TARGET_DIR/orchestrator/${f}" 2>/dev/null; then
    echo "staged: orchestrator/${f}" >&2
  else
    echo "uyarı: origin/main'de bulunamadı, atlandı: orchestrator/${f}" >&2
  fi
done

for f in "${SCRIPT_FILES[@]}"; do
  if git show "origin/main:scripts/${f}" > "$TARGET_DIR/scripts/${f}" 2>/dev/null; then
    chmod +x "$TARGET_DIR/scripts/${f}" 2>/dev/null || true
    echo "staged: scripts/${f}" >&2
  else
    echo "uyarı: origin/main'de bulunamadı, atlandı: scripts/${f}" >&2
  fi
done

# Çağıran script'in $(...) ile yakalayabilmesi için TEK stdout satırı bu
# olmalı — bilgi mesajlarının tamamı yukarıda >&2 ile stderr'e yönlendirildi.
echo "$TARGET_DIR"
