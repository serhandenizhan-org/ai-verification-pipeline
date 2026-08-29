#!/usr/bin/env bash
#
# verify_ac_lock.sh — CI'da çalışır. Her "locked" statüsündeki
# acceptance_criteria.yaml dosyasının hash'ini yeniden hesaplar ve
# locked_hash ile karşılaştırır. Uyuşmuyorsa BUILD FAILS —
# "sınavı geçemedi, sınavı değiştirdi" senaryosunu teknik olarak engeller.
#
# Kullanım (CI içinde):
#   bash scripts/verify_ac_lock.sh

set -euo pipefail

FAILED=0

for AC_FILE in specs/features/*/acceptance_criteria.yaml; do
  [[ -f "$AC_FILE" ]] || continue

  STATUS=$(grep '^status:' "$AC_FILE" | sed 's/status: *"\(.*\)"/\1/')
  if [[ "$STATUS" != "locked" && "$STATUS" != "implemented" ]]; then
    continue  # henüz kilitlenmemiş dosyalar serbestçe düzenlenebilir
  fi

  EXPECTED_HASH=$(grep '^locked_hash:' "$AC_FILE" | sed 's/locked_hash: *"\(.*\)"/\1/')

  TMP_FILE=$(mktemp)
  grep -v '^locked_hash:' "$AC_FILE" > "$TMP_FILE"
  ACTUAL_HASH=$(sha256sum "$TMP_FILE" | awk '{print $1}')
  rm -f "$TMP_FILE"

  if [[ "$ACTUAL_HASH" != "$EXPECTED_HASH" ]]; then
    echo "HATA: $AC_FILE kilitlendikten sonra değiştirilmiş!" >&2
    echo "  Beklenen hash: $EXPECTED_HASH" >&2
    echo "  Bulunan hash:  $ACTUAL_HASH" >&2
    echo "  Bu dosya yalnızca Şef onayıyla ve lock_ac.sh ile değiştirilebilir." >&2
    FAILED=1
  fi
done

if [[ "$FAILED" -eq 1 ]]; then
  echo "" >&2
  echo "AC lock ihlali tespit edildi — build durduruldu, Şef'e escalate edilmeli." >&2
  exit 1
fi

echo "Tüm kilitli AC dosyaları bütün — değişiklik yok."
