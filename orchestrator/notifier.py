#!/usr/bin/env python3
"""
notifier.py

Circuit breaker tetiklendiğinde veya Codex BLOCKING bulgu raporladığında
Şef'e Telegram üzerinden bildirim gönderir.

Gerekli ortam değişkenleri (.env üzerinden):
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID

Bot oluşturma adımları için README / sohbet geçmişine bakın —
kısaca: Telegram'da @BotFather'a yaz, /newbot komutunu çalıştır,
verilen token'ı TELEGRAM_BOT_TOKEN olarak .env dosyana koy.

ÖNEMLİ (Codex review bulgusu — P2):
  - Dinamik metin (Codex'in bulgu özeti, circuit breaker'ın trip_reason'ı
    gibi PR/agent çıktısından gelen serbest metin) eskiden hiç kaçışsız
    Telegram Markdown'a gömülüyordu — bir bulgu metninde `*`/`_`/`[` gibi
    karakterler varsa mesaj formatı bozulabiliyordu (ciddi bir güvenlik
    açığı değil, ama gerçek bir hata sınıfı). Artık `_escape_markdown()`
    ile kaçışlanıyor.
  - Ağ hatasında (timeout, DNS, geçici 5xx) tek denemede pes ediliyordu.
    Artık kısa bir backoff ile 3 deneme yapılıyor.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


def _escape_markdown(text: str) -> str:
    """
    Telegram'ın (legacy) Markdown parse_mode'unda özel anlamı olan
    karakterleri kaçışlar — dinamik/güvenilmeyen metin (Codex bulgusu,
    breaker trip_reason'ı vb.) mesaj formatını bozmasın diye.
    """
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def send_telegram_message(text: str) -> bool:
    """
    Telegram Bot API'ye mesaj gönderir. Token/chat_id eksikse False döner
    ve stderr'e yazar — asla sessizce sistemi durdurmaz (bildirim
    başarısızlığı pipeline'ı bloklamamalı, sadece loglanmalı).
    Geçici ağ hatalarına karşı kısa bir backoff ile yeniden dener.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("UYARI: TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID tanımlı değil, "
              "bildirim gönderilemedi.", file=sys.stderr)
        return False

    url = TELEGRAM_API_BASE.format(token=token)
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }).encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        request = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status == 200
        except urllib.error.URLError as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    print(f"UYARI: Telegram bildirimi {MAX_RETRIES} denemeden sonra da gönderilemedi: {last_error}",
          file=sys.stderr)
    return False


def notify_blocking_finding(pr_number: int, pr_url: str, finding_summary: str) -> bool:
    text = (
        f"🚨 *BLOCKING bulgu — PR #{pr_number}*\n\n"
        f"{_escape_markdown(finding_summary)}\n\n"
        f"[PR'ı incele]({pr_url})"
    )
    return send_telegram_message(text)


def notify_circuit_breaker_tripped(pr_number: int, pr_url: str, reason: str) -> bool:
    text = (
        f"⛔ *Circuit Breaker tetiklendi — PR #{pr_number}*\n\n"
        f"{_escape_markdown(reason)}\n\n"
        f"Builder çözemedi, senin incelemen gerekiyor.\n"
        f"[PR'ı incele]({pr_url})"
    )
    return send_telegram_message(text)


def notify_ready_for_review(pr_number: int, pr_url: str, risk_level: str) -> bool:
    text = (
        f"✅ *Şef onayı bekleniyor — PR #{pr_number}*\n\n"
        f"Risk seviyesi: {_escape_markdown(str(risk_level))}\n"
        f"CI ve Codex kontrolleri geçti.\n\n"
        f"[PR'ı incele]({pr_url})"
    )
    return send_telegram_message(text)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Telegram bildirim CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_test = sub.add_parser("test", help="Bağlantıyı test et")

    p_blocking = sub.add_parser("blocking")
    p_blocking.add_argument("pr", type=int)
    p_blocking.add_argument("url")
    p_blocking.add_argument("summary")

    p_breaker = sub.add_parser("breaker")
    p_breaker.add_argument("pr", type=int)
    p_breaker.add_argument("url")
    p_breaker.add_argument("reason")

    p_ready = sub.add_parser("ready")
    p_ready.add_argument("pr", type=int)
    p_ready.add_argument("url")
    p_ready.add_argument("risk_level")

    args = parser.parse_args()

    if args.command == "test":
        ok = send_telegram_message("✅ AI Verification Pipeline — test bildirimi başarılı.")
    elif args.command == "blocking":
        ok = notify_blocking_finding(args.pr, args.url, args.summary)
    elif args.command == "breaker":
        ok = notify_circuit_breaker_tripped(args.pr, args.url, args.reason)
    elif args.command == "ready":
        ok = notify_ready_for_review(args.pr, args.url, args.risk_level)
    else:
        sys.exit(1)

    sys.exit(0 if ok else 1)
