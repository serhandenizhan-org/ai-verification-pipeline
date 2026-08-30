#!/usr/bin/env python3
"""
circuit_breaker.py

Aynı PR üzerinde Builder <-> CI/Codex döngüsünün sonsuza kadar sürmesini
engeller. Her (repo, PR) çifti için state tutar ve iki sınırı zorlar:

  - MAX_ITERATIONS: toplam fix denemesi sayısı (varsayılan 3)
  - MAX_SAME_FAILURE: aynı hata imzasının tekrar sayısı (varsayılan 2)

Sınır aşılırsa breaker "TRIPPED" durumuna geçer ve orkestrasyon script'i
bunu Şef'e escalate etmelidir. Breaker tripped olduğunda otomatik reset
YAPILMAZ — sıfırlama yalnızca insan (Şef) kararıyla, reset_breaker() ile
yapılır.

DEPOLAMA: PostgreSQL (Codex review bulgusu — eski JSON dosya bazlı state
`.verification/state/pr-<no>.json` PR checkout dizininde duruyordu; hem
checkout'un temizlenmesiyle silinebiliyordu HEM de dosya yazımı kilitsiz
olduğu için eşzamanlı iki job aynı sayaç üzerinde yarış durumuna
girebilirdi. Artık ledger.py ile aynı DB'de, `SELECT ... FOR UPDATE` ile
satır kilitlenerek atomik güncelleniyor.

Çoklu proje izolasyonu: ledger.py ile aynı gerekçeyle `repo` zorunludur.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

DEFAULT_DATABASE_URL = "postgresql://pipeline_app@localhost/verification_pipeline"

DEFAULT_MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "3"))
DEFAULT_MAX_SAME_FAILURE = int(os.environ.get("MAX_SAME_FAILURE", "2"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    repo            TEXT NOT NULL,
    pr              INTEGER NOT NULL,
    iterations      INTEGER NOT NULL DEFAULT 0,
    failure_counts  JSONB NOT NULL DEFAULT '{}'::jsonb,
    tripped         BOOLEAN NOT NULL DEFAULT false,
    trip_reason     TEXT,
    history         JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (repo, pr)
);
"""

_SCHEMA_INIT_LOCK_ID = 847_291_004  # ledger.py'dekinden farklı bir sabit


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def _connect() -> psycopg.Connection:
    conn = psycopg.connect(_database_url(), row_factory=dict_row, autocommit=False)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_INIT_LOCK_ID,))
        cur.execute(_SCHEMA)
    conn.commit()
    return conn


def _require_repo(repo: str) -> str:
    if not repo or "/" not in repo:
        raise ValueError(
            f"Geçersiz repo değeri: {repo!r} — 'owner/repo' formatında olmalı. "
            "Circuit breaker çoklu proje paylaştığı için repo zorunludur (fail-closed)."
        )
    return repo


@dataclass
class BreakerState:
    repo: str
    pr: int
    iterations: int = 0
    failure_counts: dict[str, int] = field(default_factory=dict)
    tripped: bool = False
    trip_reason: str | None = None
    history: list[dict] = field(default_factory=list)


def _signature(failure_text: str) -> str:
    """Hata metnini kısa, karşılaştırılabilir bir imzaya indirger."""
    normalized = " ".join(failure_text.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _row_to_state(repo: str, pr: int, row: dict | None) -> BreakerState:
    if row is None:
        return BreakerState(repo=repo, pr=pr)
    return BreakerState(
        repo=repo,
        pr=pr,
        iterations=row["iterations"],
        failure_counts=row["failure_counts"],
        tripped=row["tripped"],
        trip_reason=row["trip_reason"],
        history=row["history"],
    )


def record_attempt(
    repo: str,
    pr_number: int,
    failure_text: str,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_same_failure: int = DEFAULT_MAX_SAME_FAILURE,
) -> BreakerState:
    """
    Yeni bir fix denemesi kaydeder. Zaten tripped ise state'i olduğu gibi
    döndürür (yeniden tetiklemez, insan onayı gerektirir).

    Atomik: satır `FOR UPDATE` ile kilitlenir, okuma+yazma tek transaction
    içinde yapılır — eşzamanlı iki çağrı aynı sayaç artışını kaybetmez.
    """
    repo = _require_repo(repo)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO circuit_breaker_state (repo, pr)
                VALUES (%s, %s)
                ON CONFLICT (repo, pr) DO NOTHING
                """,
                (repo, pr_number),
            )
            cur.execute(
                """
                SELECT iterations, failure_counts, tripped, trip_reason, history
                FROM circuit_breaker_state
                WHERE repo = %s AND pr = %s
                FOR UPDATE
                """,
                (repo, pr_number),
            )
            row = cur.fetchone()
            state = _row_to_state(repo, pr_number, row)

            if state.tripped:
                conn.commit()
                return state

            state.iterations += 1
            sig = _signature(failure_text)
            state.failure_counts[sig] = state.failure_counts.get(sig, 0) + 1
            state.history.append({
                "iteration": state.iterations,
                "failure_signature": sig,
                "failure_excerpt": failure_text[:200],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            if state.iterations >= max_iterations:
                state.tripped = True
                state.trip_reason = f"MAX_ITERATIONS aşıldı ({state.iterations}/{max_iterations})"
            elif state.failure_counts[sig] >= max_same_failure:
                state.tripped = True
                state.trip_reason = (
                    f"Aynı hata {state.failure_counts[sig]} kez tekrarlandı "
                    f"(imza: {sig}) — muhtemelen mimari sorun, Orchestrator'a escalate."
                )

            cur.execute(
                """
                UPDATE circuit_breaker_state
                SET iterations = %s, failure_counts = %s, tripped = %s,
                    trip_reason = %s, history = %s, updated_at = now()
                WHERE repo = %s AND pr = %s
                """,
                (
                    state.iterations, psycopg.types.json.Jsonb(state.failure_counts),
                    state.tripped, state.trip_reason, psycopg.types.json.Jsonb(state.history),
                    repo, pr_number,
                ),
            )
        conn.commit()
    return state


def is_tripped(repo: str, pr_number: int) -> bool:
    repo = _require_repo(repo)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tripped FROM circuit_breaker_state WHERE repo = %s AND pr = %s",
                (repo, pr_number),
            )
            row = cur.fetchone()
    return bool(row["tripped"]) if row else False


def reset_breaker(repo: str, pr_number: int, approved_by: str) -> BreakerState:
    """
    Yalnızca Şef onayıyla çağrılmalıdır. Yeni bir çalışma döngüsü için
    state'i sıfırlar ama geçmişi (history) korur — audit amaçlı.
    """
    repo = _require_repo(repo)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO circuit_breaker_state (repo, pr)
                VALUES (%s, %s)
                ON CONFLICT (repo, pr) DO NOTHING
                """,
                (repo, pr_number),
            )
            cur.execute(
                "SELECT history FROM circuit_breaker_state WHERE repo = %s AND pr = %s FOR UPDATE",
                (repo, pr_number),
            )
            row = cur.fetchone()
            history = row["history"] if row else []
            history.append({
                "event": "manual_reset",
                "approved_by": approved_by,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            cur.execute(
                """
                UPDATE circuit_breaker_state
                SET iterations = 0, failure_counts = '{}'::jsonb, tripped = false,
                    trip_reason = NULL, history = %s, updated_at = now()
                WHERE repo = %s AND pr = %s
                """,
                (psycopg.types.json.Jsonb(history), repo, pr_number),
            )
        conn.commit()
    return get_state(repo, pr_number)


def get_state(repo: str, pr_number: int) -> BreakerState:
    repo = _require_repo(repo)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT iterations, failure_counts, tripped, trip_reason, history
                FROM circuit_breaker_state
                WHERE repo = %s AND pr = %s
                """,
                (repo, pr_number),
            )
            row = cur.fetchone()
    return _row_to_state(repo, pr_number, row)


if __name__ == "__main__":
    import argparse
    import sys

    default_repo = os.environ.get("GITHUB_REPOSITORY", "")

    parser = argparse.ArgumentParser(description="Circuit breaker CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="Yeni bir fix denemesi kaydet")
    p_record.add_argument("--repo", default=default_repo)
    p_record.add_argument("pr_number", type=int)
    p_record.add_argument("failure_text")

    p_status = sub.add_parser("status", help="Mevcut durumu göster")
    p_status.add_argument("--repo", default=default_repo)
    p_status.add_argument("pr_number", type=int)

    p_reset = sub.add_parser("reset", help="Breaker'ı sıfırla (yalnızca Şef onayıyla)")
    p_reset.add_argument("--repo", default=default_repo)
    p_reset.add_argument("pr_number", type=int)
    p_reset.add_argument("approved_by")

    args = parser.parse_args()

    if args.command == "record":
        state = record_attempt(args.repo, args.pr_number, args.failure_text)
    elif args.command == "status":
        state = get_state(args.repo, args.pr_number)
    elif args.command == "reset":
        state = reset_breaker(args.repo, args.pr_number, args.approved_by)
    else:
        sys.exit(1)

    print(json.dumps(asdict(state), ensure_ascii=False, indent=2))
    if state.tripped:
        print("\n*** CIRCUIT BREAKER TRIPPED — Şef'e escalate edilmeli ***", file=sys.stderr)
        sys.exit(2)
