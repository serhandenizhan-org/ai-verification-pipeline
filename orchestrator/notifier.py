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
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
import json


TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_message(text: str) -> bool:
    """
    Telegram Bot API'ye mesaj gönderir. Token/chat_id eksikse ya da
    istek başarısız olursa False döner ve stderr'e yazar — asla
    sessizce sistemi durdurmaz (bildirim başarısızlığı pipeline'ı
    bloklamamalı, sadece loglanmalı).
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

    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status == 200
    except urllib.error.URLError as e:
        print(f"UYARI: Telegram bildirimi gönderilemedi: {e}", file=sys.stderr)
        return False


def notify_blocking_finding(pr_number: int, pr_url: str, finding_summary: str) -> bool:
    text = (
        f"🚨 *BLOCKING bulgu — PR #{pr_number}*\n\n"
        f"{finding_summary}\n\n"
        f"[PR'ı incele]({pr_url})"
    )
    return send_telegram_message(text)


def notify_circuit_breaker_tripped(pr_number: int, pr_url: str, reason: str) -> bool:
    text = (
        f"⛔ *Circuit Breaker tetiklendi — PR #{pr_number}*\n\n"
        f"{reason}\n\n"
        f"Builder çözemedi, senin incelemen gerekiyor.\n"
        f"[PR'ı incele]({pr_url})"
    )
    return send_telegram_message(text)


def notify_ready_for_review(pr_number: int, pr_url: str, risk_level: str) -> bool:
    text = (
        f"✅ *Şef onayı bekleniyor — PR #{pr_number}*\n\n"
        f"Risk seviyesi: {risk_level}\n"
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
