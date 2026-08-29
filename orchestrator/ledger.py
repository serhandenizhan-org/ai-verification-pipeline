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

Format: JSON Lines (.verification/ledger/pr-<no>.jsonl)
Her satır bağımsız bir event'tir. Var olan satırlar asla değiştirilmez,
yalnızca yeni satır eklenir.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEDGER_DIR = Path(".verification/ledger")


@dataclass
class LedgerEntry:
    pr: int
    event: str  # ör. "ci_result", "codex_result", "human_approval", "merge"
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _ledger_path(pr_number: int) -> Path:
    return LEDGER_DIR / f"pr-{pr_number}.jsonl"


def append_entry(entry: LedgerEntry) -> None:
    """
    Ledger'a yeni bir satır ekler. Var olan dosyaya append modunda yazar,
    hiçbir zaman mevcut içeriği okuyup yeniden yazmaz (append-only garantisi).
    """
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    path = _ledger_path(entry.pr)
    line = json.dumps(
        {
            "pr": entry.pr,
            "event": entry.event,
            "data": entry.data,
            "timestamp": entry.timestamp,
        },
        ensure_ascii=False,
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_ledger(pr_number: int) -> list[dict]:
    """Bir PR'ın tüm ledger geçmişini okur (yalnızca okuma amaçlı)."""
    path = _ledger_path(pr_number)
    if not path.exists():
        return []
    entries = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


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
