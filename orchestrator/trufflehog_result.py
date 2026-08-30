#!/usr/bin/env python3
"""
trufflehog_result.py

TruffleHog'un ürettiği JSON Lines çıktısını okur ve "Verified: true"
olan (yani gerçekten aktif olduğu API'ye sorularak doğrulanmış) secret
var mı diye kontrol eder.

ÖNEMLİ (Codex review bulgusu — P1): Eskiden bu script HİÇBİR workflow'dan
çağrılmıyordu (TruffleHog taraması hiç çalışmıyordu) VE dosya
bulunamadığında/parse edilemediğinde sessizce "bulgu yok, devam ediliyor"
diyordu — yani "tarama hiç yapılmadı" ile "tarama yapıldı, temiz çıktı"
birbirinden ayırt edilemiyordu. Artık:

  1. `--scan-exit-code` ZORUNLU — TruffleHog process'inin kendi exit
     kodu. 0 dışında bir değer, taramanın GERÇEKTEN çalışmadığı/hata
     verdiği anlamına gelir (bulgu olup olmaması farklı bir konu) — bu
     durumda ERROR statüsüyle ledger'a yazılır ve script FAIL (exit 1)
     döner, "bulgu yok" ile KARIŞTIRILMAZ.
  2. jsonl dosyası TAMAMEN yoksa (boş değil, hiç yoksa) da ERROR sayılır
     — TruffleHog `> dosya` yönlendirmesiyle her zaman bir dosya
     oluşturur (boş bile olsa), dosyanın hiç olmaması taramanın hiç
     çalıştırılmadığının işaretidir.

Kullanım:
    trufflehog git file://. --since-commit=$BASE --branch=$HEAD \
        --only-verified --json > trufflehog_output.jsonl
    EXIT_CODE=$?

    python3 trufflehog_result.py trufflehog_output.jsonl --pr 142 \
        --pr-url "https://github.com/.../pull/142" --scan-exit-code "$EXIT_CODE"

Exit code:
    0 -> tarama gerçekten çalıştı VE doğrulanmış secret yok
    1 -> tarama hiç çalışmadı/hata verdi, JSON bozuk, VEYA doğrulanmış
         secret bulundu — hepsi pipeline'ı durdurur, hiçbiri "temiz" değildir
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import alert_and_rotate
import ledger


class ScanError(Exception):
    """Tarama hiç çalışmadı/sonucu güvenilir değil — 'bulgu yok' ile KARIŞTIRILMAMALI."""


def parse_findings(jsonl_path: Path) -> list[dict]:
    """
    TruffleHog JSONL çıktısından yalnızca Verified=true olanları döndürür.
    Dosya hiç yoksa ScanError fırlatır (boş olması farklı — TruffleHog
    normalde bulgu yoksa da boş bir dosya oluşturur, bu durum GEÇERLİDİR).
    """
    if not jsonl_path.exists():
        raise ScanError(
            f"{jsonl_path} hiç oluşturulmamış — TruffleHog komutu muhtemelen "
            "hiç çalıştırılmadı (yönlendirme her zaman bir dosya oluşturur, "
            "boş bile olsa)."
        )

    verified = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # TruffleHog bazen bilgi satırları da yazar, atla
            if record.get("Verified") is True:
                verified.append(record)
    return verified


def redact_finding(record: dict) -> dict:
    """Telegram/PR yorumuna gidecek özet — gerçek secret değerini ASLA içermez."""
    meta = record.get("SourceMetadata", {}).get("Data", {})
    git_meta = meta.get("Git", {}) if isinstance(meta, dict) else {}
    return {
        "detector": record.get("DetectorName", "bilinmiyor"),
        "file": git_meta.get("file", "bilinmiyor"),
        "line": git_meta.get("line", "?"),
        "commit": git_meta.get("commit", "?")[:12] if git_meta.get("commit") else "?",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="TruffleHog sonuç işleyici")
    parser.add_argument("jsonl_path", type=Path)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--pr-url", required=True)
    parser.add_argument("--scan-exit-code", type=int, required=True,
                         help="TruffleHog process'inin kendi exit kodu (0 dışı = tarama hata verdi)")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    args = parser.parse_args()

    if args.scan_exit_code != 0:
        print(
            f"HATA: TruffleHog process'i exit_code={args.scan_exit_code} ile bitti — "
            "tarama BAŞARISIZ oldu, 'bulgu yok' ile karıştırılmamalı.",
            file=sys.stderr,
        )
        ledger.append_entry(ledger.LedgerEntry(
            repo=args.repo, pr=args.pr, event="trufflehog_result",
            data={"status": "ERROR", "reason": f"scan process exit_code={args.scan_exit_code}"},
            head_sha=args.head_sha, run_id=args.run_id,
        ))
        return 1

    try:
        verified_findings = parse_findings(args.jsonl_path)
    except ScanError as e:
        print(f"HATA: {e}", file=sys.stderr)
        ledger.append_entry(ledger.LedgerEntry(
            repo=args.repo, pr=args.pr, event="trufflehog_result",
            data={"status": "ERROR", "reason": str(e)},
            head_sha=args.head_sha, run_id=args.run_id,
        ))
        return 1

    if not verified_findings:
        print("TruffleHog: tarama başarıyla çalıştı, doğrulanmış (verified) secret bulunamadı.")
        ledger.append_entry(ledger.LedgerEntry(
            repo=args.repo, pr=args.pr, event="trufflehog_result",
            data={"status": "OK", "verified_secrets_found": 0},
            head_sha=args.head_sha, run_id=args.run_id,
        ))
        return 0

    redacted = [redact_finding(r) for r in verified_findings]

    ledger.append_entry(ledger.LedgerEntry(
        repo=args.repo, pr=args.pr, event="trufflehog_result",
        data={"status": "OK", "verified_secrets_found": len(redacted), "findings": redacted},
        head_sha=args.head_sha, run_id=args.run_id,
    ))

    alert_and_rotate.trigger(
        repo=args.repo,
        pr_number=args.pr,
        pr_url=args.pr_url,
        redacted_findings=redacted,
    )

    print(
        f"!!! {len(redacted)} DOĞRULANMIŞ (AKTİF) SECRET BULUNDU !!!",
        file=sys.stderr,
    )
    for f in redacted:
        print(f"  - {f['detector']} @ {f['file']}:{f['line']} (commit {f['commit']})",
              file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
