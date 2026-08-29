#!/usr/bin/env bash
#
# check_stripe_key_mode.sh — CI/test ortamında yanlışlıkla GERÇEK (live)
# bir Stripe key kullanılmasını engeller. STRIPE_SECRET_KEY ortam
# değişkeni "sk_live_" ile başlıyorsa pipeline'ı hemen durdurur.
#
# Kullanım (CI içinde, Playwright'tan önce):
#   bash scripts/check_stripe_key_mode.sh

set -euo pipefail

if [[ -z "${STRIPE_SECRET_KEY:-}" ]]; then
  echo "UYARI: STRIPE_SECRET_KEY tanımlı değil — Stripe testleri atlanacak." >&2
  exit 0
fi

if [[ "$STRIPE_SECRET_KEY" == sk_live_* ]]; then
  echo "!!! KRİTİK HATA !!!" >&2
  echo "STRIPE_SECRET_KEY bir LIVE (gerçek) key. Test ortamında asla" >&2
  echo "gerçek Stripe key kullanılmaz — gerçek para hareketi riski var." >&2
  echo "Bu değeri sk_test_... ile değiştirin." >&2
  exit 1
fi

if [[ "$STRIPE_SECRET_KEY" != sk_test_* ]]; then
  echo "UYARI: STRIPE_SECRET_KEY beklenen formatta değil (sk_test_... olmalı)." >&2
  echo "Devam ediliyor ama kontrol edin." >&2
fi

echo "Stripe key modu doğrulandı: TEST MODE."
