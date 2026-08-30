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
  7. `gate` komutu: TEK bağlayıcı merge kararını üretir (bkz. aşağı)

Bu script hiçbir agent'ın "PASS" demesine güvenmez — yalnızca exit code
ve structured JSON output'u okur, ledger'a onu yazar.

--repo: Tüm projeler AYNI Postgres ledger'ını paylaşıyor, bu yüzden her
komut "owner/repo" formatında bir repo belirtmek ZORUNDADIR (fail-closed —
belirtilmezse ledger.py hata verir). GitHub Actions içinde varsayılan
olarak $GITHUB_REPOSITORY ortam değişkeninden okunur (GitHub bunu otomatik
sağlar), elle --repo vermenize gerek kalmaz.

--head-sha: Codex review bulgusu — "rapor üretildi" ile "merge yapılabilir"
birbirine karışıyordu, çünkü hiçbir yerde TÜM sonuçları TEK bir bağlayıcı
karara dönüştüren mekanizma yoktu. `gate` komutu bunu çözer: yalnızca
BELİRLİ bir commit'e (head_sha) ait ledger olaylarını okur
(ledger.summarize_for_gate), circuit breaker'ın tripped olup olmadığına
bakar, ve tek bir PASS/FAIL kararı üretir. Bu karar GitHub'a gerçek PR
commit SHA'sına karşı bir status olarak yazılmalıdır (verification.yml
bunu yapıyor) — GERİDE HİÇBİR "sonuçları yorumla" adımı bırakmaz.

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
        head_sha=args.head_sha,
        run_id=args.run_id,
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
        head_sha=args.head_sha,
        run_id=args.run_id,
    ))

    if args.status == "FAIL":
        state = circuit_breaker.record_attempt(args.repo, args.pr, args.failure_text or "CI FAIL")
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
        head_sha=args.head_sha,
        run_id=args.run_id,
    ))

    if blocking_count > 0:
        summary = f"{blocking_count} adet BLOCKING bulgu tespit edildi. Rapor: {args.report_url}"
        notifier.notify_blocking_finding(args.pr, args.pr_url, summary)

    if args.status == "FAIL":
        state = circuit_breaker.record_attempt(args.repo, args.pr, args.failure_text or "CODEX FAIL")
        if state.tripped:
            notifier.notify_circuit_breaker_tripped(args.pr, args.pr_url, state.trip_reason or "")
            print("CIRCUIT_BREAKER_TRIPPED=true")
            return 2
    elif args.status == "PASS" and blocking_count == 0:
        risk_summary = ledger.summarize(args.repo, args.pr)
        notifier.notify_ready_for_review(args.pr, args.pr_url, risk_summary.get("risk_level", "?"))

    print("CIRCUIT_BREAKER_TRIPPED=false")
    # NOT: Codex review bulgusu — önceden BLOCKING bulgu olsa bile burası
    # her zaman 0 dönüyordu. Artık BLOCKING varsa 1 dönüyor (defense in
    # depth) — ama asıl bağlayıcı karar `gate` komutunda, bu exit code'a
    # güvenilmiyor (tek karar mekanizması ilkesi, bkz. modül docstring'i).
    return 1 if blocking_count > 0 else 0


def cmd_record_human_approval(args: argparse.Namespace) -> int:
    ledger.append_entry(ledger.LedgerEntry(
        repo=args.repo,
        pr=args.pr,
        event="human_approval",
        data={"approved": args.approved, "approved_by": args.approved_by},
        head_sha=args.head_sha,
        run_id=args.run_id,
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


def cmd_gate(args: argparse.Namespace) -> int:
    """
    TEK bağlayıcı merge kararı. Yalnızca `--head-sha` ile verilen commit'e
    ait ledger olaylarına bakar (eski bir commit'in sonucu asla kullanılmaz)
    ve şu sırayla kontrol eder:

      1. Circuit breaker tripped mi? -> FAIL
      2. Bu commit için risk hesaplanmış mı (Fast CI + risk-routing
         çalışmış mı)? -> hesaplanmamışsa FAIL (Fast CI başarısız/hiç
         çalışmamış demektir)
      3. Doğrulanmış bir secret sızıntısı bloklanmış mı (rotasyon onayı
         gelmemiş)? -> FAIL
      4. Risk LOW ise: yalnızca yukarıdakiler yeterli -> PASS
      5. Risk LOW değilse: Codex sonucu bu commit için var mı, PASS mi,
         blocking=0 mı? -> hepsi sağlanmıyorsa FAIL

    Çıktı: {"decision": "PASS"|"FAIL", "reason": "..."} JSON, stdout'a.
    Exit code: PASS ise 0, FAIL ise 1.
    """
    if circuit_breaker.is_tripped(args.repo, args.pr):
        return _gate_result("FAIL", "Circuit breaker tripped — Şef'in reset onayı gerekiyor.")

    summary = ledger.summarize_for_gate(args.repo, args.pr, args.head_sha)

    if summary.get("secret_leak_blocking"):
        return _gate_result("FAIL", "Doğrulanmış secret sızıntısı — rotasyon onayı bekleniyor.")

    risk_level = summary.get("risk_level")
    if risk_level is None:
        return _gate_result(
            "FAIL",
            f"Bu commit ({args.head_sha}) için risk hesaplanmamış — Fast CI "
            "başarısız olmuş ya da hiç çalışmamış olabilir.",
        )

    if risk_level == "LOW":
        return _gate_result("PASS", "Risk LOW, Fast CI başarılı — Codex review atlandı (politika gereği).")

    codex_status = summary.get("codex")
    codex_findings = summary.get("codex_findings") or {}
    blocking = codex_findings.get("blocking", None)

    if codex_status is None:
        return _gate_result("FAIL", f"Risk {risk_level} — bu commit için Codex sonucu henüz yok.")
    if codex_status != "PASS":
        return _gate_result("FAIL", f"Codex review durumu PASS değil: {codex_status}")
    if blocking is None:
        return _gate_result("FAIL", "Codex sonucu var ama blocking sayısı okunamadı (eksik/bozuk rapor).")
    if blocking > 0:
        return _gate_result("FAIL", f"{blocking} adet BLOCKING Codex bulgusu var.")

    return _gate_result("PASS", f"Risk {risk_level}, Fast CI başarılı, Codex PASS, 0 BLOCKING bulgu.")


def _gate_result(decision: str, reason: str) -> int:
    print(json.dumps({"decision": decision, "reason": reason}, ensure_ascii=False))
    return 0 if decision == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Verification Pipeline orchestrator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    default_repo = os.environ.get("GITHUB_REPOSITORY", "")
    default_run_id = os.environ.get("GITHUB_RUN_ID", "")

    p_risk = sub.add_parser("compute-risk")
    p_risk.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_risk.add_argument("--pr", type=int, required=True)
    p_risk.add_argument("--base", required=True)
    p_risk.add_argument("--head", required=True)
    p_risk.add_argument("--head-sha", default="", help="İncelenen commit SHA'sı (ledger stale-guard için)")
    p_risk.add_argument("--run-id", default=default_run_id)
    p_risk.set_defaults(func=cmd_compute_risk)

    p_ci = sub.add_parser("record-ci")
    p_ci.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_ci.add_argument("--pr", type=int, required=True)
    p_ci.add_argument("--status", choices=["PASS", "FAIL"], required=True)
    p_ci.add_argument("--details-url", default="")
    p_ci.add_argument("--pr-url", default="")
    p_ci.add_argument("--failure-text", default="")
    p_ci.add_argument("--head-sha", default="")
    p_ci.add_argument("--run-id", default=default_run_id)
    p_ci.set_defaults(func=cmd_record_ci)

    p_codex = sub.add_parser("record-codex")
    p_codex.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_codex.add_argument("--pr", type=int, required=True)
    p_codex.add_argument("--status", choices=["PASS", "FAIL"], required=True)
    p_codex.add_argument("--findings-json", default="{}")
    p_codex.add_argument("--report-url", default="")
    p_codex.add_argument("--pr-url", default="")
    p_codex.add_argument("--failure-text", default="")
    p_codex.add_argument("--head-sha", default="")
    p_codex.add_argument("--run-id", default=default_run_id)
    p_codex.set_defaults(func=cmd_record_codex)

    p_human = sub.add_parser("record-human-approval")
    p_human.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_human.add_argument("--pr", type=int, required=True)
    p_human.add_argument("--approved", type=lambda x: x.lower() == "true", required=True)
    p_human.add_argument("--approved-by", required=True)
    p_human.add_argument("--head-sha", default="")
    p_human.add_argument("--run-id", default=default_run_id)
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

    p_gate = sub.add_parser("gate", help="TEK bağlayıcı merge kararını üret (PASS/FAIL)")
    p_gate.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_gate.add_argument("--pr", type=int, required=True)
    p_gate.add_argument("--head-sha", required=True, help="Kararın verileceği commit SHA'sı (zorunlu)")
    p_gate.set_defaults(func=cmd_gate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
