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

ÖNEMLİ — çoklu proje izolasyonu: Tüm projeler AYNI Postgres veritabanını
paylaşıyor (tek Mac mini, tek DB). Her satır bir `repo` alanı taşır
("owner/repo" formatında, ör. "serhandenizhan-org/kuyumcukent-project") —
bu olmadan iki farklı projenin aynı PR numarası (ör. ikisinde de #7)
ledger'da karışırdı. `repo` HER ZAMAN açıkça verilmelidir, sessizce
varsayılan bir değere düşülmez (fail-closed: yanlış repo'ya yazmaktansa
hata vermek tercih edilir).

ÖNEMLİ — commit/run kimliği (Codex review bulgusu): Bir PR aynı numarayla
birden çok commit alabilir (yeni push, force-push, rebase). `pr` alanı tek
başına HANGİ COMMIT için üretildiğini ayırt etmez — eski (geç biten) bir
çalışma, daha yeni bir commit'in sonucunu "ezmiş" gibi görünebilir çünkü
summarize() tüm geçmişi PR bazında birleştiriyordu. Bunu çözmek için her
satır artık `head_sha` (incelenen commit) ve `run_id` (GitHub Actions run
kimliği) taşıyor. `summarize_for_gate()` yalnızca BELİRLİ bir head_sha'ya
ait olayları dikkate alır — bu, verification-gate'in karar verirken eski
bir commit'in sonucuna güvenmemesini garanti eder.

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

# NOT: sıralama önemli — önce tablo (yeni kolonlar OLMADAN, eski
# kurulumlarla "IF NOT EXISTS" uyumlu kalması için), sonra migration (eksik
# kolonları ekler), sonra index'ler (yeni kolonlara referans veriyorlar,
# migration'dan ÖNCE çalışırlarsa "column does not exist" hatası verirler
# — bu tam olarak `repo` kolonu eklenirken yaşanan bir bug'dı).
_SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS ledger_entries (
    id          BIGSERIAL PRIMARY KEY,
    pr          INTEGER NOT NULL,
    event       TEXT NOT NULL,
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    "timestamp" TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Eski şemalardan yükseltme — eksik kolonları ekler. `repo` yoksa
# "unknown/legacy" atanır, `head_sha`/`run_id` yoksa "" atanır (bu projede
# henüz gerçek çoklu-commit verisi olmadığı için pratikte etkilenen satır
# olmayacak, ama fail-closed olarak burada da ele alınıyor).
_MIGRATION = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ledger_entries' AND column_name = 'repo'
    ) THEN
        ALTER TABLE ledger_entries ADD COLUMN repo TEXT;
        UPDATE ledger_entries SET repo = 'unknown/legacy' WHERE repo IS NULL;
        ALTER TABLE ledger_entries ALTER COLUMN repo SET NOT NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ledger_entries' AND column_name = 'head_sha'
    ) THEN
        ALTER TABLE ledger_entries ADD COLUMN head_sha TEXT NOT NULL DEFAULT '';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ledger_entries' AND column_name = 'run_id'
    ) THEN
        ALTER TABLE ledger_entries ADD COLUMN run_id TEXT NOT NULL DEFAULT '';
    END IF;
END $$;
"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_ledger_entries_repo_pr ON ledger_entries (repo, pr);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_repo_pr_id ON ledger_entries (repo, pr, id);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_repo_pr_sha ON ledger_entries (repo, pr, head_sha);
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
        cur.execute(_SCHEMA_TABLE)
        cur.execute(_MIGRATION)
        cur.execute(_SCHEMA_INDEXES)
    conn.commit()
    return conn


def _require_repo(repo: str) -> str:
    if not repo or "/" not in repo:
        raise ValueError(
            f"Geçersiz repo değeri: {repo!r} — 'owner/repo' formatında olmalı "
            "(ör. 'serhandenizhan-org/kuyumcukent-project'). Ledger çoklu proje "
            "paylaştığı için repo belirtmeden yazmak/okumak YASAK (fail-closed)."
        )
    return repo


@dataclass
class LedgerEntry:
    repo: str  # "owner/repo" formatında — çoklu proje izolasyonu için zorunlu
    pr: int
    event: str  # ör. "ci_result", "codex_result", "human_approval", "merge"
    data: dict[str, Any] = field(default_factory=dict)
    head_sha: str = ""  # incelenen commit — verification-gate stale-result korumasına dayanak
    run_id: str = ""  # GitHub Actions run kimliği — audit/debug için
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def append_entry(entry: LedgerEntry) -> None:
    """
    Ledger'a yeni bir satır ekler (INSERT ONLY — append-only garantisi).
    """
    repo = _require_repo(entry.repo)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ledger_entries (repo, pr, event, data, head_sha, run_id, "timestamp")
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (repo, entry.pr, entry.event, psycopg.types.json.Jsonb(entry.data),
                 entry.head_sha, entry.run_id, entry.timestamp),
            )
        conn.commit()


def read_ledger(repo: str, pr_number: int, head_sha: str | None = None) -> list[dict]:
    """
    Bir proje+PR'ın ledger geçmişini okur (yalnızca okuma amaçlı), id sırasıyla.
    `head_sha` verilirse yalnızca o commit'e ait satırlar döner.
    """
    repo = _require_repo(repo)
    query = """
        SELECT repo, pr, event, data, head_sha, run_id, "timestamp"
        FROM ledger_entries
        WHERE repo = %s AND pr = %s
    """
    params: list[Any] = [repo, pr_number]
    if head_sha:
        query += " AND head_sha = %s"
        params.append(head_sha)
    query += " ORDER BY id ASC"

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    return [
        {
            "repo": row["repo"],
            "pr": row["pr"],
            "event": row["event"],
            "data": row["data"],
            "head_sha": row["head_sha"],
            "run_id": row["run_id"],
            "timestamp": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else row["timestamp"],
        }
        for row in rows
    ]


def _summarize_entries(repo: str, pr_number: int, entries: list[dict]) -> dict:
    summary: dict[str, Any] = {
        "repo": repo,
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


def summarize(repo: str, pr_number: int) -> dict:
    """
    Ledger geçmişinden özet bir durum çıkarır (TÜM commit'ler dahil) —
    "bu PR'da şimdiye kadar ne oldu" görmek için (insan tarafından okunan
    bir özet). Karar/gate mantığı için summarize_for_gate() kullanılmalı.
    """
    return _summarize_entries(repo, pr_number, read_ledger(repo, pr_number))


def summarize_for_gate(repo: str, pr_number: int, head_sha: str) -> dict:
    """
    Yalnızca BELİRLİ bir commit'e (head_sha) ait olayları özetler. Merge
    kararı burada üretilmeli — PR'ın tüm geçmişini (summarize()) kullanmak,
    eski bir commit'in PASS sonucunun yeni bir commit için de geçerliymiş
    gibi görünmesine yol açabilir (Codex review bulgusu).
    """
    if not head_sha:
        raise ValueError(
            "summarize_for_gate() için head_sha zorunlu — boş geçilirse "
            "hangi commit'in değerlendirildiği belirsizleşir (fail-closed)."
        )
    entries = read_ledger(repo, pr_number, head_sha=head_sha)
    result = _summarize_entries(repo, pr_number, entries)
    result["head_sha"] = head_sha
    return result


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Verification Ledger CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Yeni bir ledger event'i ekle")
    p_add.add_argument("repo", help="owner/repo formatında, ör. serhandenizhan-org/kuyumcukent-project")
    p_add.add_argument("pr", type=int)
    p_add.add_argument("event")
    p_add.add_argument("data_json", help="JSON string, ör. '{\"status\": \"PASS\"}'")
    p_add.add_argument("--head-sha", default="")
    p_add.add_argument("--run-id", default="")

    p_read = sub.add_parser("read", help="Bir proje+PR'ın tüm ledger geçmişini göster")
    p_read.add_argument("repo")
    p_read.add_argument("pr", type=int)
    p_read.add_argument("--head-sha", default=None, help="Verilirse yalnızca bu commit'e ait satırlar")

    p_summary = sub.add_parser("summary", help="Bir proje+PR için özet durum göster (tüm commit'ler)")
    p_summary.add_argument("repo")
    p_summary.add_argument("pr", type=int)

    p_gate_summary = sub.add_parser("gate-summary", help="Belirli bir commit için özet durum göster")
    p_gate_summary.add_argument("repo")
    p_gate_summary.add_argument("pr", type=int)
    p_gate_summary.add_argument("head_sha")

    args = parser.parse_args()

    if args.command == "add":
        entry = LedgerEntry(
            repo=args.repo, pr=args.pr, event=args.event, data=json.loads(args.data_json),
            head_sha=args.head_sha, run_id=args.run_id,
        )
        append_entry(entry)
        print(f"Ledger'a eklendi: {args.repo} PR #{args.pr} -> {args.event}")
    elif args.command == "read":
        for e in read_ledger(args.repo, args.pr, head_sha=args.head_sha):
            print(json.dumps(e, ensure_ascii=False))
    elif args.command == "summary":
        print(json.dumps(summarize(args.repo, args.pr), ensure_ascii=False, indent=2))
    elif args.command == "gate-summary":
        print(json.dumps(summarize_for_gate(args.repo, args.pr, args.head_sha), ensure_ascii=False, indent=2))
    else:
        sys.exit(1)
