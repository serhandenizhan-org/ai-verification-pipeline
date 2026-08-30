#!/usr/bin/env bash
#
# lock_ac.sh — Acceptance Criteria dosyasını kilitler.
#
# Şef onayından SONRA çalıştırılmalıdır. Dosyanın SHA-256 hash'ini alır,
# dosyanın içine "locked_hash" alanına yazar VE bu hash'i Postgres'e
# (dosyadan BAĞIMSIZ bir kayıt olarak) yazar — bkz. orchestrator/ac_lock.py
# için gerekçe. Bu noktadan sonra CI, dosyanın hash'i değişirse VEYA
# Postgres'teki bağımsız kayıtla uyuşmazsa otomatik BLOCK eder (bkz.
# scripts/verify_ac_lock.sh).
#
# Kullanım:
#   bash scripts/lock_ac.sh specs/features/<feature-adi>/acceptance_criteria.yaml ["Onaylayan Şef"]

set -euo pipefail

AC_FILE="${1:-}"
LOCKED_BY="${2:-${USER:-bilinmiyor}}"

if [[ -z "$AC_FILE" ]]; then
  echo "Kullanım: $0 <acceptance_criteria.yaml yolu> [\"onaylayan\"]" >&2
  exit 1
fi

if [[ ! -f "$AC_FILE" ]]; then
  echo "HATA: Dosya bulunamadı: $AC_FILE" >&2
  exit 1
fi

# specs/features/<feature-adi>/acceptance_criteria.yaml -> <feature-adi>
FEATURE=$(basename "$(dirname "$AC_FILE")")

# Önce status'u "locked" yap, SONRA hash'i bu nihai içerik üzerinden hesapla
# (locked_hash satırı hariç) — verify_ac_lock.py de aynı nihai içeriği
# hashleyeceği için ikisi birbirini tutmalı.
sed -i.bak -e "s/^status: .*/status: \"locked\"/" "$AC_FILE"
rm -f "${AC_FILE}.bak"

TMP_FILE=$(mktemp)
grep -v '^locked_hash:' "$AC_FILE" > "$TMP_FILE"

HASH=$(sha256sum "$TMP_FILE" | awk '{print $1}')
rm -f "$TMP_FILE"

sed -i.bak -e "s/^locked_hash: .*/locked_hash: \"${HASH}\"/" "$AC_FILE"
rm -f "${AC_FILE}.bak"

# Dosyadan BAĞIMSIZ, güvenilir kayıt — CI bunu (dosyanın kendi beyanını
# değil) referans alır. Postgres kurulu değilse (yerel ilk taslak
# aşamasında olabilir) uyarıp devam eder — ama bu durumda CI'da
# verify_ac_lock.py bu feature'ı "hiç kilitlenmemiş" sayıp BLOCK eder,
# yani Postgres'e yazamamak sessizce yutulmuyor.
if python3 "$(dirname "$0")/../orchestrator/ac_lock.py" record "$FEATURE" "$HASH" "$LOCKED_BY" 2>/tmp/ac_lock_err.txt; then
  echo "Postgres'e bağımsız kilit kaydı yazıldı: $FEATURE by $LOCKED_BY"
else
  echo "UYARI: Postgres'e kilit kaydı YAZILAMADI — CI bu feature'ı kilitli saymayacak:" >&2
  cat /tmp/ac_lock_err.txt >&2
fi
rm -f /tmp/ac_lock_err.txt

echo "Kilitlendi: $AC_FILE"
echo "Hash: $HASH"
echo ""
echo "Bu dosyayı commit'leyin. Bundan sonra herhangi bir değişiklik"
echo "(locked_hash hariç) CI tarafından otomatik reddedilecektir."
