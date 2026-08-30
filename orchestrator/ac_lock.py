#!/usr/bin/env python3
"""
ac_lock.py

Acceptance Criteria (AC) kilitleme kayıtlarının GÜVENİLİR (dosyanın
KENDİSİNİN dışında tutulan) kopyasını Postgres'te saklar.

NEDEN (Codex review bulgusu — P1): Eski `lock_ac.sh`/`verify_ac_lock.sh`
çifti, kilitli hash'i AC dosyasının İÇİNE (`locked_hash:` alanı) yazıyordu
ve doğrulama da yine dosyanın kendi beyanına bakıyordu. Bu, "bu içerik
insan tarafından onaylandı" kanıtı değildi — biri hem içeriği hem
`locked_hash` alanını birlikte değiştirirse kontrol yine geçerdi.
`status: locked` alanını `draft`'a çevirmek ya da dosyayı tamamen silmek
de kontrolü tamamen atlatıyordu (script yalnızca "locked/implemented"
statüsündeki VAR OLAN dosyaları kontrol ediyordu).

ÇÖZÜM: Kilit anında hesaplanan hash, dosyadan tamamen BAĞIMSIZ bir yerde
(Postgres, yalnızca `scripts/lock_ac.sh` — yani Şef'in kendi elle
çalıştırdığı, CI'ın değil, bir insan aksiyonu — tarafından yazılabilir)
saklanır. Doğrulama artık dosyanın kendi beyanına değil, bu bağımsız
kayda bakar. Ayrıca: bir feature için kayıt varsa ama dosya artık
locked/implemented değilse (draft'a çevrilmiş) VEYA dosya hiç yoksa
(silinmiş), bu da BLOCKING bir ihlal sayılır.

Append-only: record_lock() yalnızca INSERT yapar, geçmiş kilit kayıtları
asla silinmez/değiştirilmez — bir feature yeniden kilitlenirse (relock),
bu yeni bir satır olarak eklenir, en son satır geçerli kabul edilir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

DEFAULT_DATABASE_URL = "postgresql://pipeline_app@localhost/verification_pipeline"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_locks (
    id          BIGSERIAL PRIMARY KEY,
    repo        TEXT NOT NULL,
    feature     TEXT NOT NULL,
    locked_hash TEXT NOT NULL,
    locked_by   TEXT NOT NULL,
    locked_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ac_locks_repo_feature ON ac_locks (repo, feature, id DESC);
"""

_SCHEMA_INIT_LOCK_ID = 847_291_005  # ledger/breaker'dakinden farklı sabit


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def _connect() -> psycopg.Connection:
    conn = psycopg.connect(_database_url(), row_factory=dict_row)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_INIT_LOCK_ID,))
        cur.execute(_SCHEMA)
    conn.commit()
    return conn


def _require_repo(repo: str) -> str:
    if not repo or "/" not in repo:
        raise ValueError(
            f"Geçersiz repo değeri: {repo!r} — 'owner/repo' formatında olmalı. "
            "AC lock çoklu proje paylaştığı için repo zorunludur (fail-closed)."
        )
    return repo


@dataclass
class AcLockRecord:
    repo: str
    feature: str
    locked_hash: str
    locked_by: str
    locked_at: str | None = None


def record_lock(repo: str, feature: str, locked_hash: str, locked_by: str) -> None:
    """
    Yeni bir kilit kaydı ekler (INSERT ONLY). Bu, YALNIZCA `lock_ac.sh`
    tarafından (Şef'in elle çalıştırdığı bir insan aksiyonu olarak)
    çağrılmalıdır — CI/agent tarafından değil.
    """
    repo = _require_repo(repo)
    if not locked_by:
        raise ValueError("locked_by boş olamaz — kilidi kimin onayladığı izlenebilir olmalı.")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ac_locks (repo, feature, locked_hash, locked_by, locked_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (repo, feature, locked_hash, locked_by, datetime.now(timezone.utc).isoformat()),
            )
        conn.commit()


def get_latest_lock(repo: str, feature: str) -> AcLockRecord | None:
    """Bir feature için en son (geçerli) kilit kaydını döndürür, yoksa None."""
    repo = _require_repo(repo)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT repo, feature, locked_hash, locked_by, locked_at
                FROM ac_locks
                WHERE repo = %s AND feature = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (repo, feature),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return AcLockRecord(
        repo=row["repo"], feature=row["feature"], locked_hash=row["locked_hash"],
        locked_by=row["locked_by"],
        locked_at=row["locked_at"].isoformat() if hasattr(row["locked_at"], "isoformat") else row["locked_at"],
    )


def list_locked_features(repo: str) -> list[str]:
    """Bu repo'da en az bir kez kilitlenmiş TÜM feature isimlerini döndürür."""
    repo = _require_repo(repo)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT feature FROM ac_locks WHERE repo = %s", (repo,))
            rows = cur.fetchall()
    return [r["feature"] for r in rows]


if __name__ == "__main__":
    import argparse
    import json
    import sys

    default_repo = os.environ.get("GITHUB_REPOSITORY", "")

    parser = argparse.ArgumentParser(description="AC Lock kayıt CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record")
    p_record.add_argument("--repo", default=default_repo)
    p_record.add_argument("feature")
    p_record.add_argument("locked_hash")
    p_record.add_argument("locked_by")

    p_get = sub.add_parser("get")
    p_get.add_argument("--repo", default=default_repo)
    p_get.add_argument("feature")

    p_list = sub.add_parser("list")
    p_list.add_argument("--repo", default=default_repo)

    args = parser.parse_args()

    if args.command == "record":
        record_lock(args.repo, args.feature, args.locked_hash, args.locked_by)
        print(f"AC kilit kaydı eklendi: {args.repo}/{args.feature} by {args.locked_by}")
    elif args.command == "get":
        rec = get_latest_lock(args.repo, args.feature)
        print(json.dumps(rec.__dict__ if rec else None, ensure_ascii=False, indent=2))
    elif args.command == "list":
        print(json.dumps(list_locked_features(args.repo), ensure_ascii=False))
    else:
        sys.exit(1)
