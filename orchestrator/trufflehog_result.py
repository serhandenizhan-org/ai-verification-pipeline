#!/usr/bin/env python3
"""
trufflehog_result.py

TruffleHog'un ürettiği JSON Lines çıktısını okur ve "Verified: true"
olan (yani gerçekten aktif olduğu API'ye sorularak doğrulanmış) secret
var mı diye kontrol eder.

Kullanım:
    trufflehog git file://. --since-commit=$BASE --branch=$HEAD \
        --only-verified --json > trufflehog_output.jsonl

    python3 trufflehog_result.py trufflehog_output.jsonl --pr 142 \
        --pr-url "https://github.com/.../pull/142"

Exit code:
    0 -> doğrulanmış secret yok, akışa devam edilebilir
    1 -> doğrulanmış secret bulundu, pipeline durdurulmalı
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import alert_and_rotate
import ledger


def parse_findings(jsonl_path: Path) -> list[dict]:
    """TruffleHog JSONL çıktısından yalnızca Verified=true olanları döndürür."""
    if not jsonl_path.exists() or jsonl_path.stat().st_size == 0:
        return []

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
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--pr-url", required=True)
    args = parser.parse_args()

    verified_findings = parse_findings(args.jsonl_path)

    if not verified_findings:
        print("TruffleHog: doğrulanmış (verified) secret bulunamadı. Devam ediliyor.")
        ledger.append_entry(ledger.LedgerEntry(
            pr=args.pr,
            event="trufflehog_result",
            data={"verified_secrets_found": 0},
        ))
        return 0

    redacted = [redact_finding(r) for r in verified_findings]

    ledger.append_entry(ledger.LedgerEntry(
        pr=args.pr,
        event="trufflehog_result",
        data={"verified_secrets_found": len(redacted), "findings": redacted},
    ))

    alert_and_rotate.trigger(
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
