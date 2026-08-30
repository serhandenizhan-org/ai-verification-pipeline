#!/usr/bin/env bash
#
# check_stripe_key_mode.sh — CI/test ortamında yanlışlıkla GERÇEK (live)
# bir Stripe key kullanılmasını engeller.
#
# NEDEN ALLOWLIST (Codex review bulgusu — P1): Eski script yalnızca
# "sk_live_" ile başlayan değerleri reddediyordu — "sk_test_" DIŞINDAKİ
# her şey (boş string, yazım hatası, tamamen farklı bir servisin key'i,
# rastgele bir string) yalnızca bir UYARIYLA kabul edilip test mode
# doğrulanmış SAYILIYORDU. Artık yalnızca "sk_test_" ile başlayan
# değerler kabul ediliyor — geri kalan HER ŞEY reddedilir (allowlist,
# blocklist değil).
#
# Kullanım (CI içinde, PLAYWRIGHT CONTAINER'INA secret verilmeden ÖNCE,
# host'ta çalıştırılmalı — bkz. scripts/generate_ci_workflow.py'deki
# sıralama notu, Codex review bulgusu: eskiden key container'a `npm ci`
# ÇALIŞMADAN önce veriliyordu, yani guard'dan geçmeden bile PR'ın
# lifecycle script'leri key'e erişebiliyordu):
#   bash scripts/check_stripe_key_mode.sh

set -euo pipefail

if [[ -z "${STRIPE_SECRET_KEY:-}" ]]; then
  echo "UYARI: STRIPE_SECRET_KEY tanımlı değil — Stripe testleri atlanacak." >&2
  exit 0
fi

if [[ "$STRIPE_SECRET_KEY" != sk_test_* ]]; then
  echo "!!! KRİTİK HATA !!!" >&2
  echo "STRIPE_SECRET_KEY 'sk_test_' ile başlamıyor. Test ortamında YALNIZCA" >&2
  echo "açıkça test-mode formatındaki key'ler kabul edilir — 'sk_live_' ile" >&2
  echo "başlayanlar, boş/bozuk değerler, ya da başka bir formattaki HER ŞEY" >&2
  echo "reddedilir (allowlist, yalnızca sk_live_'ı reddeden blocklist DEĞİL)." >&2
  exit 1
fi

echo "Stripe key modu doğrulandı: TEST MODE (sk_test_...)."
