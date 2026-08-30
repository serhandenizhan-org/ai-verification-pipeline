#!/usr/bin/env python3
"""
verifier.py

Ana orkestrasyon script'i. GitHub Actions workflow'ları bu script'i
çağırarak şu akışı yürütür:

  1. router.compute_risk()      -> risk seviyesi ve zorunlu kontroller
  2. ledger.append_entry()      -> risk_computed event'i
  3. (CI ve Codex sonuçları workflow tarafından argüman olarak verilir)
  4. ledger.append_entry()      -> ci_result / codex_result event'leri
  5. Gerekirse circuit_breaker.record_attempt()
  6. Gerekirse notifier ile Şef'e bildirim

Bu script hiçbir agent'ın "PASS" demesine güvenmez — yalnızca exit code
ve structured JSON output'u okur, ledger'a onu yazar.

--repo: Tüm projeler AYNI Postgres ledger'ını paylaşıyor, bu yüzden her
komut "owner/repo" formatında bir repo belirtmek ZORUNDADIR (fail-closed —
belirtilmezse ledger.py hata verir). GitHub Actions içinde varsayılan
olarak $GITHUB_REPOSITORY ortam değişkeninden okunur (GitHub bunu otomatik
sağlar), elle --repo vermenize gerek kalmaz.

Kullanım örnekleri README.md ve .github/workflows/verification.yml
içinde gösterilmiştir.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import circuit_breaker
import ledger
import notifier
import router
import alert_and_rotate


def cmd_compute_risk(args: argparse.Namespace) -> int:
    result = router.compute_risk(args.base, args.head, None)
    required = router.required_checks_for(result.level)

    ledger.append_entry(ledger.LedgerEntry(
        repo=args.repo,
        pr=args.pr,
        event="risk_computed",
        data={
            "risk_level": result.level,
            "score": result.score,
            "fail_closed": result.fail_closed,
            "required_checks": required,
        },
    ))

    print(json.dumps({
        "risk_level": result.level,
        "required_checks": required,
        "fail_closed": result.fail_closed,
    }, ensure_ascii=False))
    return 0


def cmd_record_ci(args: argparse.Namespace) -> int:
    ledger.append_entry(ledger.LedgerEntry(
        repo=args.repo,
        pr=args.pr,
        event="ci_result",
        data={"status": args.status, "details_url": args.details_url},
    ))

    if args.status == "FAIL":
        state = circuit_breaker.record_attempt(args.pr, args.failure_text or "CI FAIL")
        if state.tripped:
            notifier.notify_circuit_breaker_tripped(args.pr, args.pr_url, state.trip_reason or "")
            print("CIRCUIT_BREAKER_TRIPPED=true")
            return 2

    print("CIRCUIT_BREAKER_TRIPPED=false")
    return 0


def cmd_record_codex(args: argparse.Namespace) -> int:
    findings = json.loads(args.findings_json) if args.findings_json else {}
    blocking_count = findings.get("blocking", 0)

    ledger.append_entry(ledger.LedgerEntry(
        repo=args.repo,
        pr=args.pr,
        event="codex_result",
        data={"status": args.status, "findings": findings},
    ))

    if blocking_count > 0:
        summary = f"{blocking_count} adet BLOCKING bulgu tespit edildi. Rapor: {args.report_url}"
        notifier.notify_blocking_finding(args.pr, args.pr_url, summary)

    if args.status == "FAIL":
        state = circuit_breaker.record_attempt(args.pr, args.failure_text or "CODEX FAIL")
        if state.tripped:
            notifier.notify_circuit_breaker_tripped(args.pr, args.pr_url, state.trip_reason or "")
            print("CIRCUIT_BREAKER_TRIPPED=true")
            return 2
    elif args.status == "PASS" and blocking_count == 0:
        risk_summary = ledger.summarize(args.repo, args.pr)
        notifier.notify_ready_for_review(args.pr, args.pr_url, risk_summary.get("risk_level", "?"))

    print("CIRCUIT_BREAKER_TRIPPED=false")
    return 0


def cmd_record_human_approval(args: argparse.Namespace) -> int:
    ledger.append_entry(ledger.LedgerEntry(
        repo=args.repo,
        pr=args.pr,
        event="human_approval",
        data={"approved": args.approved, "approved_by": args.approved_by},
    ))
    print(f"human_approval kaydedildi: approved={args.approved} by={args.approved_by}")
    return 0


def cmd_record_secret_rotated(args: argparse.Namespace) -> int:
    alert_and_rotate.record_rotation_confirmed(args.repo, args.pr, args.confirmed_by)
    print(f"Secret rotasyon onayı kaydedildi: {args.repo} PR #{args.pr} by {args.confirmed_by}")
    print("Bu PR artık merge akışına devam edebilir (CI/Codex yeniden tetiklenmeli).")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    print(json.dumps(ledger.summarize(args.repo, args.pr), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Verification Pipeline orchestrator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    default_repo = os.environ.get("GITHUB_REPOSITORY", "")

    p_risk = sub.add_parser("compute-risk")
    p_risk.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_risk.add_argument("--pr", type=int, required=True)
    p_risk.add_argument("--base", required=True)
    p_risk.add_argument("--head", required=True)
    p_risk.set_defaults(func=cmd_compute_risk)

    p_ci = sub.add_parser("record-ci")
    p_ci.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_ci.add_argument("--pr", type=int, required=True)
    p_ci.add_argument("--status", choices=["PASS", "FAIL"], required=True)
    p_ci.add_argument("--details-url", default="")
    p_ci.add_argument("--pr-url", default="")
    p_ci.add_argument("--failure-text", default="")
    p_ci.set_defaults(func=cmd_record_ci)

    p_codex = sub.add_parser("record-codex")
    p_codex.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_codex.add_argument("--pr", type=int, required=True)
    p_codex.add_argument("--status", choices=["PASS", "FAIL"], required=True)
    p_codex.add_argument("--findings-json", default="{}")
    p_codex.add_argument("--report-url", default="")
    p_codex.add_argument("--pr-url", default="")
    p_codex.add_argument("--failure-text", default="")
    p_codex.set_defaults(func=cmd_record_codex)

    p_human = sub.add_parser("record-human-approval")
    p_human.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_human.add_argument("--pr", type=int, required=True)
    p_human.add_argument("--approved", type=lambda x: x.lower() == "true", required=True)
    p_human.add_argument("--approved-by", required=True)
    p_human.set_defaults(func=cmd_record_human_approval)

    p_rotated = sub.add_parser("record-secret-rotated")
    p_rotated.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_rotated.add_argument("--pr", type=int, required=True)
    p_rotated.add_argument("--confirmed-by", required=True)
    p_rotated.set_defaults(func=cmd_record_secret_rotated)

    p_summary = sub.add_parser("summary")
    p_summary.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_summary.add_argument("--pr", type=int, required=True)
    p_summary.set_defaults(func=cmd_summary)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
