#!/usr/bin/env python3
"""
usage_tracker.py — Codex'in önerdiği özellik: maliyet/kullanım
görünürlüğü.

NE İZLENİYOR: Bu pipeline'ın asıl maliyet sürücüsü Codex CLI çağrılarıdır
(her `codex exec review` bir API çağrısıdır, self-hosted runner'ın
kendisi ücretsizdir). Bu modül HER GÜN, her repo için, her event tipi
(şimdilik yalnızca "codex_review") için bir sayaç tutar (Postgres,
`usage_daily` tablosu, `(date, repo, event_type)` primary key).

KADEMELİ BİLDİRİM (claude.md politikası): sayaç WARN/CRITICAL eşiklerini
aştığında Telegram'a bildirim gider — ama pipeline KENDİ KENDİNE DURMAZ,
yalnızca Şef'i bilgilendirir (bkz. claude.md "Maliyet limiti politikası").
Aynı eşik için günde yalnızca BİR KEZ bildirim gider (`notified_tiers`
JSONB kolonu) — her PR'da tekrar tekrar spam olmaması için.

Eşikler ortam değişkeniyle ayarlanır (Şef'in netleştirmesi gereken,
projeye özel sayılar — bkz. claude.md):
    CODEX_DAILY_WARN_THRESHOLD   (varsayılan: 10)
    CODEX_DAILY_CRITICAL_THRESHOLD (varsayılan: 20)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date as _date

import notifier
from ledger import _connect, _require_repo  # type: ignore

_SCHEMA_INIT_LOCK_ID = 847_291_011

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_daily (
    usage_date DATE NOT NULL,
    repo TEXT NOT NULL,
    event_type TEXT NOT NULL,
    count INT NOT NULL DEFAULT 0,
    notified_tiers JSONB NOT NULL DEFAULT '[]',
    PRIMARY KEY (usage_date, repo, event_type)
);
"""

DEFAULT_WARN_THRESHOLD = 10
DEFAULT_CRITICAL_THRESHOLD = 20


def _warn_threshold() -> int:
    # GitHub Actions, tanımsız bir `vars.X` için env değişkenini BOŞ STRING
    # olarak set eder (yok saymaz) — `or` ile boş string de varsayılana düşer.
    return int(os.environ.get("CODEX_DAILY_WARN_THRESHOLD") or DEFAULT_WARN_THRESHOLD)


def _critical_threshold() -> int:
    return int(os.environ.get("CODEX_DAILY_CRITICAL_THRESHOLD") or DEFAULT_CRITICAL_THRESHOLD)


def _ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_INIT_LOCK_ID,))
        cur.execute(_SCHEMA)
    conn.commit()


def record_usage(repo: str, event_type: str, today: _date | None = None) -> int:
    """Bugünün sayacını 1 artırır, yeni değeri döner."""
    _require_repo(repo)
    today = today or _date.today()
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO usage_daily (usage_date, repo, event_type, count)
                VALUES (%s, %s, %s, 1)
                ON CONFLICT (usage_date, repo, event_type) DO UPDATE SET
                    count = usage_daily.count + 1
                RETURNING count
                """,
                (today, repo, event_type),
            )
            count = cur.fetchone()["count"]
        conn.commit()
        return count
    finally:
        conn.close()


def get_today_count(repo: str, event_type: str, today: _date | None = None) -> int:
    _require_repo(repo)
    today = today or _date.today()
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count FROM usage_daily WHERE usage_date = %s AND repo = %s AND event_type = %s",
                (today, repo, event_type),
            )
            row = cur.fetchone()
            return row["count"] if row else 0
    finally:
        conn.close()


def check_and_notify_thresholds(repo: str, event_type: str, count: int, today: _date | None = None) -> list[str]:
    """
    Aşılan eşikleri kontrol eder, bugün İLK KEZ aşıldıysa Telegram'a
    bildirir. Döner: bu çağrıda YENİ tetiklenen tier isimleri
    (['warn'], ['critical'], ['warn','critical'], veya []).

    Pipeline HİÇBİR ZAMAN durmaz — bu yalnızca bildirimdir (bkz. claude.md).
    """
    _require_repo(repo)
    today = today or _date.today()
    warn_t, crit_t = _warn_threshold(), _critical_threshold()

    tiers_to_check = []
    if count >= warn_t:
        tiers_to_check.append("warn")
    if count >= crit_t:
        tiers_to_check.append("critical")
    if not tiers_to_check:
        return []

    conn = _connect()
    try:
        _ensure_schema(conn)
        newly_triggered = []
        with conn.cursor() as cur:
            cur.execute(
                "SELECT notified_tiers FROM usage_daily WHERE usage_date = %s AND repo = %s AND event_type = %s",
                (today, repo, event_type),
            )
            row = cur.fetchone()
            already = set(row["notified_tiers"]) if row else set()
            to_notify = [t for t in tiers_to_check if t not in already]
            if to_notify:
                newly_triggered = to_notify
                cur.execute(
                    """
                    INSERT INTO usage_daily (usage_date, repo, event_type, count, notified_tiers)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (usage_date, repo, event_type) DO UPDATE SET
                        notified_tiers = EXCLUDED.notified_tiers
                    """,
                    (today, repo, event_type, count, json.dumps(sorted(already | set(to_notify)))),
                )
        conn.commit()
    finally:
        conn.close()

    for tier in newly_triggered:
        threshold = warn_t if tier == "warn" else crit_t
        emoji = "⚠️" if tier == "warn" else "🚨"
        notifier.send_telegram_message(
            f"{emoji} Kullanım eşiği aşıldı ({repo})\n"
            f"Bugün {event_type}: {count} çağrı (eşik: {threshold}, tier: {tier})\n"
            f"Pipeline ÇALIŞMAYA DEVAM EDİYOR, otomatik durmuyor — "
            f"gerekirse Telegram üzerinden manuel müdahale et."
        )
    return newly_triggered


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="Kullanım olayını kaydet, eşikleri kontrol et")
    p_record.add_argument("--repo", required=True)
    p_record.add_argument("--event-type", default="codex_review")

    p_summary = sub.add_parser("summary", help="Bugünün sayaçlarını göster")
    p_summary.add_argument("--repo", required=True)
    p_summary.add_argument("--event-type", default="codex_review")

    args = parser.parse_args()

    if args.command == "record":
        count = record_usage(args.repo, args.event_type)
        triggered = check_and_notify_thresholds(args.repo, args.event_type, count)
        print(json.dumps({"count": count, "newly_triggered_tiers": triggered}))
        return 0

    if args.command == "summary":
        count = get_today_count(args.repo, args.event_type)
        print(json.dumps({
            "repo": args.repo,
            "event_type": args.event_type,
            "count": count,
            "warn_threshold": _warn_threshold(),
            "critical_threshold": _critical_threshold(),
        }))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(_cli())
