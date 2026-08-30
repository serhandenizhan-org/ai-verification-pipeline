#!/usr/bin/env python3
"""
ledger.py

Verification Ledger — her PR için append-only (yalnızca ekleme yapılan,
geriye dönük değiştirilmeyen) bir denetim kaydı tutar.

ÖNEMLİ: Bu dosyayı hiçbir agent (Builder, Codex) doğrudan çağırmamalıdır.
Ledger'a yazma yetkisi yalnızca orkestrasyon script'lerine (verifier.py,
CI workflow'ları) aittir. Bir agent "PASS" dediği için ledger'a "PASS"
yazılmaz — ledger, exit code ve structured tool output'undan orchestrator
tarafından üretilir.

Depolama: PostgreSQL (bkz. schema.sql, HANDOFF.md 3.3) — çoklu PR
eşzamanlılığında sorgulanabilirlik için eski JSON dosya bazlı (.verification/
ledger/pr-<no>.jsonl) yaklaşımdan taşındı. Bağlantı DATABASE_URL ortam
değişkeninden okunur; tanımlı değilse Mac mini'deki local dev instance'a
düşer (bkz. .env.example).

Append-only garantisi: append_entry() yalnızca INSERT yapar, hiçbir
fonksiyon UPDATE/DELETE çalıştırmaz.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

DEFAULT_DATABASE_URL = "postgresql://pipeline_app@localhost/verification_pipeline"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_entries (
    id          BIGSERIAL PRIMARY KEY,
    pr          INTEGER NOT NULL,
    event       TEXT NOT NULL,
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    "timestamp" TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_pr ON ledger_entries (pr);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_pr_id ON ledger_entries (pr, id);
"""


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


# Sabit advisory lock ID — şema init'ini eşzamanlı bağlantılar arasında
# serileştirmek için (bkz. Codex review bulgusu: "IF NOT EXISTS" tek başına
# concurrent DDL'i yarış durumundan korumuyor, aynı anda bağlanan iki PR
# job'ı duplicate-key hatası alabiliyordu). Rastgele seçilmiş bir sayı,
# yalnızca bu uygulamaya özel bir lock namespace'i olması yeterli.
_SCHEMA_INIT_LOCK_ID = 847_291_003

def _connect() -> psycopg.Connection:
    conn = psycopg.connect(_database_url(), row_factory=dict_row)
    with conn.cursor() as cur:
        # xact-scoped lock: yalnızca bu transaction COMMIT/ROLLBACK olana
        # kadar tutulur, serbest bırakma sırası elle yönetilmiyor — bir
        # önceki denemede unlock'u commit'ten ÖNCE çağırmak, tablo henüz
        # commit edilmeden başka bir bağlantının lock'u alıp aynı
        # CREATE TABLE'ı tekrar denemesine (duplicate-key hatası) yol
        # açıyordu. xact_lock bunu yapısal olarak imkansız kılıyor.
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_INIT_LOCK_ID,))
        cur.execute(_SCHEMA)
    conn.commit()
    return conn


@dataclass
class LedgerEntry:
    pr: int
    event: str  # ör. "ci_result", "codex_result", "human_approval", "merge"
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def append_entry(entry: LedgerEntry) -> None:
    """
    Ledger'a yeni bir satır ekler (INSERT ONLY — append-only garantisi).
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ledger_entries (pr, event, data, "timestamp")
                VALUES (%s, %s, %s, %s)
                """,
                (entry.pr, entry.event, psycopg.types.json.Jsonb(entry.data), entry.timestamp),
            )
        conn.commit()


def read_ledger(pr_number: int) -> list[dict]:
    """Bir PR'ın tüm ledger geçmişini okur (yalnızca okuma amaçlı), id sırasıyla."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pr, event, data, "timestamp"
                FROM ledger_entries
                WHERE pr = %s
                ORDER BY id ASC
                """,
                (pr_number,),
            )
            rows = cur.fetchall()
    return [
        {
            "pr": row["pr"],
            "event": row["event"],
            "data": row["data"],
            "timestamp": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else row["timestamp"],
        }
        for row in rows
    ]


def summarize(pr_number: int) -> dict:
    """
    Ledger geçmişinden özet bir durum çıkarır — merge kararı vermeden önce
    hızlıca "bu PR'da şu ana kadar ne oldu" görmek için kullanılır.
    """
    entries = read_ledger(pr_number)
    summary: dict[str, Any] = {
        "pr": pr_number,
        "total_events": len(entries),
        "ci": None,
        "codex": None,
        "risk_level": None,
        "iterations": 0,
        "human_approval": False,
        "approved_by": None,
        "secret_leak_blocking": False,
        "secret_rotation_confirmed": False,
    }
    for e in entries:
        event, data = e["event"], e.get("data", {})
        if event == "risk_computed":
            summary["risk_level"] = data.get("risk_level")
        elif event == "ci_result":
            summary["ci"] = data.get("status")
        elif event == "codex_result":
            summary["codex"] = data.get("status")
            summary["codex_findings"] = data.get("findings")
        elif event == "fix_iteration":
            summary["iterations"] += 1
        elif event == "human_approval":
            summary["human_approval"] = bool(data.get("approved"))
            summary["approved_by"] = data.get("approved_by")
        elif event == "secret_alert_triggered":
            summary["secret_leak_blocking"] = True
        elif event == "secret_rotation_confirmed":
            summary["secret_leak_blocking"] = False
            summary["secret_rotation_confirmed"] = True
    return summary


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Verification Ledger CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Yeni bir ledger event'i ekle")
    p_add.add_argument("pr", type=int)
    p_add.add_argument("event")
    p_add.add_argument("data_json", help="JSON string, ör. '{\"status\": \"PASS\"}'")

    p_read = sub.add_parser("read", help="Bir PR'ın tüm ledger geçmişini göster")
    p_read.add_argument("pr", type=int)

    p_summary = sub.add_parser("summary", help="Bir PR için özet durum göster")
    p_summary.add_argument("pr", type=int)

    args = parser.parse_args()

    if args.command == "add":
        entry = LedgerEntry(pr=args.pr, event=args.event, data=json.loads(args.data_json))
        append_entry(entry)
        print(f"Ledger'a eklendi: PR #{args.pr} -> {args.event}")
    elif args.command == "read":
        for e in read_ledger(args.pr):
            print(json.dumps(e, ensure_ascii=False))
    elif args.command == "summary":
        print(json.dumps(summarize(args.pr), ensure_ascii=False, indent=2))
    else:
        sys.exit(1)
