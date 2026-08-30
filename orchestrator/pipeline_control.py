#!/usr/bin/env python3
"""
pipeline_control.py — Codex'in önerdiği özellik 7'nin "durdur/devam" yarısı:
Şef'in Telegram üzerinden bir repo'nun verification-gate'ini manuel olarak
durdurup devam ettirebilmesi.

Bu, per-PR circuit breaker'dan (`circuit_breaker.py`) FARKLIDIR: circuit
breaker otomatik (tekrarlayan hatalara göre) tetiklenir ve PR başınadır.
Buradaki 'stop', Şef'in KASITLI, REPO GENELİNDE bir müdahalesidir (ör.
"bu repo'da bir olay var, tüm PR'ları durdur").

Yalnızca `telegram_commands.py` (yetkilendirilmiş Telegram chat_id'den
gelen komutları doğruladıktan SONRA) bu modülü çağırır — bu modülün
kendisi bir yetkilendirme yapmaz, çağıranın zaten doğrulamış olduğunu
varsayar.
"""

from __future__ import annotations

import sys

from ledger import _connect, _require_repo  # type: ignore

_SCHEMA_INIT_LOCK_ID = 847_291_013

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_control (
    repo TEXT PRIMARY KEY,
    stopped BOOLEAN NOT NULL DEFAULT false,
    stopped_by TEXT,
    stopped_at TIMESTAMPTZ,
    reason TEXT,
    resumed_by TEXT,
    resumed_at TIMESTAMPTZ
);
"""


def _ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_INIT_LOCK_ID,))
        cur.execute(_SCHEMA)
    conn.commit()


def is_stopped(repo: str) -> tuple[bool, str | None]:
    """(durduruldu_mu, sebep) döner."""
    _require_repo(repo)
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT stopped, reason FROM pipeline_control WHERE repo = %s", (repo,))
            row = cur.fetchone()
            if not row:
                return False, None
            return bool(row["stopped"]), row["reason"]
    finally:
        conn.close()


def set_stopped(repo: str, stopped_by: str, reason: str) -> None:
    _require_repo(repo)
    if not stopped_by.strip():
        raise ValueError("stopped_by boş olamaz — durdurma her zaman bir insan ismine bağlanmalı.")
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pipeline_control (repo, stopped, stopped_by, stopped_at, reason)
                VALUES (%s, true, %s, now(), %s)
                ON CONFLICT (repo) DO UPDATE SET
                    stopped = true, stopped_by = %s, stopped_at = now(), reason = %s
                """,
                (repo, stopped_by, reason, stopped_by, reason),
            )
        conn.commit()
    finally:
        conn.close()


def clear_stopped(repo: str, resumed_by: str) -> bool:
    _require_repo(repo)
    if not resumed_by.strip():
        raise ValueError("resumed_by boş olamaz — devam ettirme her zaman bir insan ismine bağlanmalı.")
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pipeline_control
                SET stopped = false, resumed_by = %s, resumed_at = now()
                WHERE repo = %s AND stopped = true
                """,
                (resumed_by, repo),
            )
            updated = cur.rowcount > 0
        conn.commit()
        return updated
    finally:
        conn.close()


def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_stop = sub.add_parser("stop")
    p_stop.add_argument("repo")
    p_stop.add_argument("stopped_by")
    p_stop.add_argument("reason")

    p_resume = sub.add_parser("resume")
    p_resume.add_argument("repo")
    p_resume.add_argument("resumed_by")

    p_status = sub.add_parser("status")
    p_status.add_argument("repo")

    args = parser.parse_args()
    if args.command == "stop":
        set_stopped(args.repo, args.stopped_by, args.reason)
        print(f"Durduruldu: {args.repo} (by {args.stopped_by})")
        return 0
    if args.command == "resume":
        ok = clear_stopped(args.repo, args.resumed_by)
        print(f"Devam ettirildi: {args.repo}" if ok else f"Zaten durdurulmamış: {args.repo}")
        return 0
    if args.command == "status":
        stopped, reason = is_stopped(args.repo)
        print(f"stopped={stopped} reason={reason!r}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
