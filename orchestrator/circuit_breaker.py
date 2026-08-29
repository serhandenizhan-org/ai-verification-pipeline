#!/usr/bin/env python3
"""
circuit_breaker.py

Aynı PR üzerinde Builder <-> CI/Codex döngüsünün sonsuza kadar sürmesini
engeller. Her PR için bir state dosyası tutar (.verification/state/pr-<no>.json)
ve iki sınırı zorlar:

  - MAX_ITERATIONS: toplam fix denemesi sayısı (varsayılan 3)
  - MAX_SAME_FAILURE: aynı hata imzasının tekrar sayısı (varsayılan 2)

Sınır aşılırsa breaker "TRIPPED" durumuna geçer ve orkestrasyon script'i
bunu Şef'e escalate etmelidir. Breaker tripped olduğunda otomatik reset
YAPILMAZ — sıfırlama yalnızca insan (Şef) kararıyla, reset_breaker() ile
yapılır.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(".verification/state")

DEFAULT_MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "3"))
DEFAULT_MAX_SAME_FAILURE = int(os.environ.get("MAX_SAME_FAILURE", "2"))


@dataclass
class BreakerState:
    pr_number: int
    iterations: int = 0
    failure_counts: dict[str, int] = field(default_factory=dict)
    tripped: bool = False
    trip_reason: str | None = None
    history: list[dict] = field(default_factory=list)


def _state_path(pr_number: int) -> Path:
    return STATE_DIR / f"pr-{pr_number}.json"


def _load(pr_number: int) -> BreakerState:
    path = _state_path(pr_number)
    if not path.exists():
        return BreakerState(pr_number=pr_number)
    data = json.loads(path.read_text(encoding="utf-8"))
    return BreakerState(**data)


def _save(state: BreakerState) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _state_path(state.pr_number)
    path.write_text(
        json.dumps(state.__dict__, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _signature(failure_text: str) -> str:
    """Hata metnini kısa, karşılaştırılabilir bir imzaya indirger."""
    normalized = " ".join(failure_text.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def record_attempt(
    pr_number: int,
    failure_text: str,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_same_failure: int = DEFAULT_MAX_SAME_FAILURE,
) -> BreakerState:
    """
    Yeni bir fix denemesi kaydeder. Zaten tripped ise state'i olduğu gibi
    döndürür (yeniden tetiklemez, insan onayı gerektirir).
    """
    state = _load(pr_number)

    if state.tripped:
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
        state.trip_reason = (
            f"MAX_ITERATIONS aşıldı ({state.iterations}/{max_iterations})"
        )
    elif state.failure_counts[sig] >= max_same_failure:
        state.tripped = True
        state.trip_reason = (
            f"Aynı hata {state.failure_counts[sig]} kez tekrarlandı "
            f"(imza: {sig}) — muhtemelen mimari sorun, Orchestrator'a escalate."
        )

    _save(state)
    return state


def is_tripped(pr_number: int) -> bool:
    return _load(pr_number).tripped


def reset_breaker(pr_number: int, approved_by: str) -> BreakerState:
    """
    Yalnızca Şef onayıyla çağrılmalıdır. Yeni bir çalışma döngüsü için
    state'i sıfırlar ama geçmişi (history) korur — audit amaçlı.
    """
    state = _load(pr_number)
    state.history.append({
        "event": "manual_reset",
        "approved_by": approved_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    state.iterations = 0
    state.failure_counts = {}
    state.tripped = False
    state.trip_reason = None
    _save(state)
    return state


def get_state(pr_number: int) -> BreakerState:
    return _load(pr_number)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Circuit breaker CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="Yeni bir fix denemesi kaydet")
    p_record.add_argument("pr_number", type=int)
    p_record.add_argument("failure_text")

    p_status = sub.add_parser("status", help="Mevcut durumu göster")
    p_status.add_argument("pr_number", type=int)

    p_reset = sub.add_parser("reset", help="Breaker'ı sıfırla (yalnızca Şef onayıyla)")
    p_reset.add_argument("pr_number", type=int)
    p_reset.add_argument("approved_by")

    args = parser.parse_args()

    if args.command == "record":
        state = record_attempt(args.pr_number, args.failure_text)
    elif args.command == "status":
        state = get_state(args.pr_number)
    elif args.command == "reset":
        state = reset_breaker(args.pr_number, args.approved_by)
    else:
        sys.exit(1)

    print(json.dumps(state.__dict__, ensure_ascii=False, indent=2))
    if state.tripped:
        print("\n*** CIRCUIT BREAKER TRIPPED — Şef'e escalate edilmeli ***", file=sys.stderr)
        sys.exit(2)
