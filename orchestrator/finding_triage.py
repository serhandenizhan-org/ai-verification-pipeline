#!/usr/bin/env python3
"""
finding_triage.py — Codex'in önerdiği özellik: bulgulara kalıcı kimlik
(fingerprint) ve triage geçmişi.

SORUN: Codex her review'da raporu yeniden üretir; aynı P1 bulgusu iki
farklı run'da birebir aynı metinle gelmeyebilir (kelime seçimi değişebilir).
Bu yüzden "bu daha önce gördüğümüz bir bulgu mu, yoksa yeni mi" sorusuna
cevap yoktu — her run'da her şey "yeni" gibi görünüyordu.

ÇÖZÜM: Her bulgunun `severity + title + file:line` kısmından STABIL bir
fingerprint (sha256) türetilir (gövde metni/açıklama fingerprint'e dahil
değildir — o değişken olabilir). Postgres'te `finding_history` tablosunda:
  - ilk görülme / son görülme zamanı, kaç kez tekrar ettiği
  - triage durumu: 'open' (varsayılan) | 'accepted' (Şef onaylı istisna)

ÖNEMLİ — GATE SEMANTİĞİ: Bir BLOCKING bulgu 'accepted' olarak işaretlenirse
(yalnızca Şef onayıyla, `finding_triage.py accept` üzerinden — tıpkı
secret rotasyon onayı gibi insan-onaylı bir işlem), o SPESİFİK bulgu artık
gate'i bloklamaz. Kabul edilmemiş diğer BLOCKING bulgular gate'i bloklamaya
devam eder. Bu, "AI kendi kendine karar veremez" ilkesini korur (bkz.
claude.md) — accept() çağrısı her zaman bir `accepted_by` insan ismi ister.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ledger import _connect, _require_repo  # type: ignore

_SCHEMA_INIT_LOCK_ID = 847_291_009

_SCHEMA = """
CREATE TABLE IF NOT EXISTS finding_history (
    repo TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    occurrence_count INT NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'open',
    accepted_by TEXT,
    accepted_reason TEXT,
    accepted_at TIMESTAMPTZ,
    accepted_until TIMESTAMPTZ,
    PRIMARY KEY (repo, fingerprint)
);
"""

# Codex raporu satır formatı: "- [P1] Title — file.py:42" (bkz. verification.yml
# parse mantığı — aynı regex ailesi burada da kullanılıyor).
_FINDING_LINE_RE = re.compile(r"^-\s*\[(P1|P2|P3)\]\s*(.+?)\s*(?:—|--)\s*(\S+)\s*$")


@dataclass
class Finding:
    severity: str
    title: str
    location: str
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        raw = f"{self.severity}|{self.title.strip().lower()}|{self.location.strip()}"
        self.fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_findings(report_text: str) -> list[Finding]:
    findings = []
    for line in (report_text or "").splitlines():
        m = _FINDING_LINE_RE.match(line.strip())
        if m:
            severity, title, location = m.groups()
            findings.append(Finding(severity=severity, title=title, location=location))
    return findings


def _ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_INIT_LOCK_ID,))
        cur.execute(_SCHEMA)
        # Feature 7 öncesi oluşturulmuş tablolarda (PR #30) bu kolon yok —
        # ADD COLUMN IF NOT EXISTS ile geriye dönük uyumlu migration.
        cur.execute("ALTER TABLE finding_history ADD COLUMN IF NOT EXISTS accepted_until TIMESTAMPTZ")
    conn.commit()


def record_findings(repo: str, findings: list[Finding]) -> dict[str, dict]:
    """Her finding için upsert yapar; {fingerprint: {"is_new": bool, "occurrence_count": int, "status": str}} döner."""
    _require_repo(repo)
    result: dict[str, dict] = {}
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            for f in findings:
                cur.execute(
                    """
                    INSERT INTO finding_history (repo, fingerprint, severity, title, location)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (repo, fingerprint) DO UPDATE SET
                        last_seen_at = now(),
                        occurrence_count = finding_history.occurrence_count + 1
                    RETURNING occurrence_count, status, (xmax = 0) AS is_new
                    """,
                    (repo, f.fingerprint, f.severity, f.title, f.location),
                )
                row = cur.fetchone()
                result[f.fingerprint] = {
                    "is_new": bool(row["is_new"]),
                    "occurrence_count": row["occurrence_count"],
                    "status": row["status"],
                }
        conn.commit()
    finally:
        conn.close()
    return result


def get_status(repo: str, fingerprint: str) -> str | None:
    _require_repo(repo)
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM finding_history WHERE repo = %s AND fingerprint = %s",
                (repo, fingerprint),
            )
            row = cur.fetchone()
            return row["status"] if row else None
    finally:
        conn.close()


def accept_finding(
    repo: str, fingerprint: str, accepted_by: str, reason: str, expires_in_hours: float | None = None
) -> bool:
    """
    Şef onayıyla bir bulguyu istisna olarak işaretler. Satır bulunamazsa
    False döner. `expires_in_hours` verilirse istisna SÜRELİDİR — bu süre
    geçtikten sonra `unaccepted_blocking_count` bu bulguyu tekrar
    bloklayıcı sayar (bkz. Codex özellik 7: "yetkili durdur/devam + süreli
    istisna"). Verilmezse istisna kalıcıdır (eski davranış).
    """
    _require_repo(repo)
    if not accepted_by.strip():
        raise ValueError("accepted_by boş olamaz — istisna her zaman bir insan ismine bağlanmalı.")
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE finding_history
                SET status = 'accepted', accepted_by = %s, accepted_reason = %s,
                    accepted_at = now(),
                    accepted_until = CASE WHEN %s::double precision IS NULL THEN NULL
                                          ELSE now() + (%s::double precision::text || ' hours')::interval END
                WHERE repo = %s AND fingerprint = %s
                """,
                (accepted_by, reason, expires_in_hours, expires_in_hours, repo, fingerprint),
            )
            updated = cur.rowcount > 0
        conn.commit()
        return updated
    finally:
        conn.close()


def unaccepted_blocking_count(repo: str, findings: list[Finding]) -> int:
    """Verilen bulgular arasından P1 (BLOCKING) olup 'accepted' durumda OLMAYANLARIN sayısı."""
    _require_repo(repo)
    p1 = [f for f in findings if f.severity == "P1"]
    if not p1:
        return 0
    conn = _connect()
    try:
        _ensure_schema(conn)
        count = 0
        with conn.cursor() as cur:
            for f in p1:
                # Süreli istisna (accepted_until) geçmişse `is_expired` true
                # olur — bulgu tekrar bloklayıcı sayılır (fail-closed: süre
                # dolunca sessizce kalıcı istisnaya dönüşmemeli). Karşılaştırma
                # SQL/now() tarafında yapılır, Python-tz uyuşmazlığından kaçınmak için.
                cur.execute(
                    """
                    SELECT status,
                           (accepted_until IS NOT NULL AND accepted_until <= now()) AS is_expired
                    FROM finding_history WHERE repo = %s AND fingerprint = %s
                    """,
                    (repo, f.fingerprint),
                )
                row = cur.fetchone()
                status = row["status"] if row else "open"
                is_expired = bool(row["is_expired"]) if row else False
                if status != "accepted" or is_expired:
                    count += 1
        return count
    finally:
        conn.close()


def list_findings(repo: str) -> list[dict]:
    _require_repo(repo)
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fingerprint, severity, title, location, occurrence_count,
                       status, accepted_by, accepted_reason,
                       first_seen_at, last_seen_at
                FROM finding_history WHERE repo = %s
                ORDER BY last_seen_at DESC
                """,
                (repo,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_accept = sub.add_parser("accept", help="Bir bulguyu Şef onayıyla istisna olarak işaretle")
    p_accept.add_argument("repo")
    p_accept.add_argument("fingerprint")
    p_accept.add_argument("accepted_by")
    p_accept.add_argument("reason")

    p_list = sub.add_parser("list", help="Bir repo için bilinen tüm bulguları listele")
    p_list.add_argument("repo")

    args = parser.parse_args()

    if args.command == "accept":
        ok = accept_finding(args.repo, args.fingerprint, args.accepted_by, args.reason)
        if ok:
            print(f"Kabul edildi: {args.fingerprint} (onaylayan: {args.accepted_by})")
            return 0
        print(f"Bulunamadı: {args.fingerprint}", file=sys.stderr)
        return 1

    if args.command == "list":
        print(json.dumps(list_findings(args.repo), ensure_ascii=False, indent=2, default=str))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(_cli())
