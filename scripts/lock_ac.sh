#!/usr/bin/env bash
#
# lock_ac.sh — Acceptance Criteria dosyasını kilitler.
#
# Şef onayından SONRA çalıştırılmalıdır. Dosyanın SHA-256 hash'ini alır,
# dosyanın içine "locked_hash" alanına yazar ve "status: locked" yapar.
# Bu noktadan sonra CI, dosyanın hash'i değişirse otomatik BLOCK eder
# (bkz. scripts/verify_ac_lock.sh).
#
# Kullanım:
#   bash scripts/lock_ac.sh specs/features/<feature-adi>/acceptance_criteria.yaml

set -euo pipefail

AC_FILE="${1:-}"

if [[ -z "$AC_FILE" ]]; then
  echo "Kullanım: $0 <acceptance_criteria.yaml yolu>" >&2
  exit 1
fi

if [[ ! -f "$AC_FILE" ]]; then
  echo "HATA: Dosya bulunamadı: $AC_FILE" >&2
  exit 1
fi

# Önce status'u "locked" yap, SONRA hash'i bu nihai içerik üzerinden hesapla
# (locked_hash satırı hariç) — verify_ac_lock.sh de aynı nihai içeriği
# hashleyeceği için ikisi birbirini tutmalı.
sed -i.bak -e "s/^status: .*/status: \"locked\"/" "$AC_FILE"
rm -f "${AC_FILE}.bak"

TMP_FILE=$(mktemp)
grep -v '^locked_hash:' "$AC_FILE" > "$TMP_FILE"

HASH=$(sha256sum "$TMP_FILE" | awk '{print $1}')
rm -f "$TMP_FILE"

sed -i.bak -e "s/^locked_hash: .*/locked_hash: \"${HASH}\"/" "$AC_FILE"
rm -f "${AC_FILE}.bak"

echo "Kilitlendi: $AC_FILE"
echo "Hash: $HASH"
echo ""
echo "Bu dosyayı commit'leyin. Bundan sonra herhangi bir değişiklik"
echo "(locked_hash hariç) CI tarafından otomatik reddedilecektir."
