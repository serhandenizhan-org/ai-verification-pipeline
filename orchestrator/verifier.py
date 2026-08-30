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
import finding_triage
import pipeline_control


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

    # Codex'in önerdiği özellik: tek güncellenen PR yorumu. Rapor metnini
    # (ve varsa tedarik zinciri raporunu) ledger'a da yazıyoruz ki
    # verification-gate job'u AYRI bir dosya paylaşımına ihtiyaç duymadan
    # (farklı bir runner job'unda çalıştığı için codex_last_message.txt'e
    # erişemez) tek, kapsamlı bir yorum oluşturabilsin.
    report_text = ""
    if args.report_file:
        try:
            report_text = open(args.report_file, encoding="utf-8").read()
        except OSError:
            pass
    deps_report = None
    if args.deps_report_file:
        try:
            deps_report = json.loads(open(args.deps_report_file, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            pass

    # Codex'in önerdiği özellik: bulgulara kalıcı kimlik (fingerprint) ve
    # triage geçmişi — aynı bulgu tekrar tekrar "yeni" gibi görünmesin,
    # Şef'in kabul ettiği (accepted) istisnalar takip edilebilsin.
    parsed_findings = finding_triage.parse_findings(report_text)
    finding_status = finding_triage.record_findings(args.repo, parsed_findings) if parsed_findings else {}
    unaccepted_blocking = finding_triage.unaccepted_blocking_count(args.repo, parsed_findings)

    ledger.append_entry(ledger.LedgerEntry(
        repo=args.repo,
        pr=args.pr,
        event="codex_result",
        data={
            "status": args.status,
            "findings": findings,
            "report_text": report_text,
            "deps_report": deps_report,
            "finding_triage": finding_status,
            "unaccepted_blocking": unaccepted_blocking,
        },
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
    # `unaccepted_blocking` kullanılıyor: Şef'in `finding_triage.py accept`
    # ile onayladığı bir P1 artık bloklayıcı sayılmaz.
    return 1 if unaccepted_blocking > 0 else 0


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


# Marker: PR yorumlarında BU pipeline'ın "durum yorumu"nu bulmak için
# kullanılır (workflow, bu satırla başlayan yorumu arayıp günceller,
# her run'da yeni yorum biriktirmek yerine).
MARKER = "<!-- ai-verification-pipeline:status -->"


def _evaluate_gate(repo: str, pr: int, head_sha: str) -> tuple[str, str, dict]:
    """
    TEK bağlayıcı merge kararının mantığı. Yalnızca `head_sha` ile verilen
    commit'e ait ledger olaylarına bakar (eski bir commit'in sonucu asla
    kullanılmaz) ve şu sırayla kontrol eder:

      1. Circuit breaker tripped mi? -> FAIL
      2. Doğrulanmış bir secret sızıntısı bloklanmış mı? -> FAIL
      3. TruffleHog bu commit için 'OK' mü? -> değilse FAIL
      4. Risk hesaplanmış mı? -> hesaplanmamışsa FAIL
      5. Risk LOW ise: yukarıdakiler yeterli -> PASS
      6. Risk LOW değilse: Codex sonucu var mı, PASS mi, blocking=0 mı?
         -> hepsi sağlanmıyorsa FAIL

    Döndürür: (decision, reason, summary) — summary, cmd_render_comment'in
    tam yorum metnini oluşturmak için kullandığı ledger özetidir (rapor
    metni, tedarik zinciri raporu dahil).
    """
    # Codex özellik 7: Şef, Telegram üzerinden bir repo'yu KASITLI olarak
    # durdurabilir (circuit breaker'dan farklı — otomatik değil, insan
    # kararı, repo genelinde). Bu kontrol her şeyden ÖNCE gelir.
    stopped, stop_reason = pipeline_control.is_stopped(repo)
    if stopped:
        return "FAIL", f"Şef pipeline'ı manuel olarak durdurdu: {stop_reason or 'sebep belirtilmedi'}", {}

    if circuit_breaker.is_tripped(repo, pr):
        return "FAIL", "Circuit breaker tripped — Şef'in reset onayı gerekiyor.", {}

    summary = ledger.summarize_for_gate(repo, pr, head_sha)

    if summary.get("secret_leak_blocking"):
        return "FAIL", "Doğrulanmış secret sızıntısı — rotasyon onayı bekleniyor.", summary

    # Codex review bulgusu (P1): TruffleHog hiçbir workflow'dan çağrılmıyordu,
    # yani hiçbir zaman engelleyici olamıyordu. Artık gate BU EVENT'İN VAR
    # OLMASINI ve "OK" olmasını ZORUNLU KILIYOR — TruffleHog adımı workflow'a
    # eklenmezse (ya da hata verirse) gate FAIL verir, "sessizce atlanma"
    # yapısal olarak imkansız hale gelir.
    trufflehog_status = summary.get("trufflehog_status")
    if trufflehog_status != "OK":
        return (
            "FAIL",
            f"Bu commit için TruffleHog sonucu 'OK' değil (durum: {trufflehog_status!r}) "
            "— tarama hiç çalışmamış, hata vermiş ya da doğrulanmış secret bulmuş olabilir.",
            summary,
        )

    risk_level = summary.get("risk_level")
    if risk_level is None:
        return (
            "FAIL",
            f"Bu commit ({head_sha}) için risk hesaplanmamış — Fast CI "
            "başarısız olmuş ya da hiç çalışmamış olabilir.",
            summary,
        )

    if risk_level == "LOW":
        return "PASS", "Risk LOW, Fast CI başarılı — Codex review atlandı (politika gereği).", summary

    codex_status = summary.get("codex")
    codex_findings = summary.get("codex_findings") or {}
    blocking = codex_findings.get("blocking", None)

    if codex_status is None:
        return "FAIL", f"Risk {risk_level} — bu commit için Codex sonucu henüz yok.", summary
    if codex_status != "PASS":
        return "FAIL", f"Codex review durumu PASS değil: {codex_status}", summary
    if blocking is None:
        return "FAIL", "Codex sonucu var ama blocking sayısı okunamadı (eksik/bozuk rapor).", summary
    if blocking > 0:
        # Codex'in önerdiği özellik: kalıcı bulgu kimliği + triage.
        # `unaccepted_blocking`, ham `blocking` sayısından, Şef'in
        # `finding_triage.py accept` ile onayladığı P1'leri düşer. Eski
        # ledger kayıtlarında bu alan yoksa (None) ham sayıya geri döner
        # (fail-closed: bilinmeyen durumda daha az güvenmek, daha çok değil).
        unaccepted = summary.get("unaccepted_blocking")
        effective_blocking = unaccepted if unaccepted is not None else blocking
        if effective_blocking > 0:
            return "FAIL", (
                f"{effective_blocking} adet kabul edilmemiş BLOCKING Codex bulgusu var "
                f"(toplam {blocking}, {blocking - effective_blocking} tanesi Şef tarafından kabul edilmiş)."
                if effective_blocking != blocking
                else f"{blocking} adet BLOCKING Codex bulgusu var."
            ), summary

    return "PASS", f"Risk {risk_level}, Fast CI başarılı, Codex PASS, 0 BLOCKING bulgu.", summary


def cmd_gate(args: argparse.Namespace) -> int:
    decision, reason, _summary = _evaluate_gate(args.repo, args.pr, args.head_sha)
    print(json.dumps({"decision": decision, "reason": reason}, ensure_ascii=False))
    return 0 if decision == "PASS" else 1


def cmd_render_comment(args: argparse.Namespace) -> int:
    """
    Codex'in önerdiği özellik: TEK, güncellenen bir PR yorumu. Gate
    kararını + risk + Codex raporunun tamamı + tedarik zinciri raporunu
    tek bir Markdown çıktısında birleştirir. Workflow, bu çıktıyı bir
    "işaretli" (marker) yoruma yazar/günceller — böylece her run'da yeni
    bir yorum birikmez.
    """
    decision, reason, summary = _evaluate_gate(args.repo, args.pr, args.head_sha)

    badge = "✅ PASS" if decision == "PASS" else "❌ FAIL"
    lines = [
        MARKER,
        f"## 🤖 AI Verification Pipeline — PR #{args.pr}",
        "",
        f"**Sonuç: {badge}** — {reason}",
        "",
        f"**Risk seviyesi:** {summary.get('risk_level', 'bilinmiyor')}",
        f"**TruffleHog:** {summary.get('trufflehog_status', 'bilinmiyor')}",
    ]

    codex_status = summary.get("codex")
    if codex_status is not None:
        findings = summary.get("codex_findings") or {}
        lines += [
            "",
            "### Reviewer Codex",
            f"Durum: {codex_status} — {findings.get('blocking', '?')} BLOCKING, "
            f"{findings.get('advisory', '?')} ADVISORY",
        ]
        report_text = summary.get("codex_report_text")
        if report_text:
            lines += ["", "<details><summary>Tam rapor</summary>", "", report_text, "", "</details>"]

    deps_report = summary.get("deps_report")
    if deps_report and deps_report.get("new_dependencies_found"):
        lines += [
            "",
            "### 🔎 Tedarik Zinciri (Supply-Chain)",
            f"{deps_report['new_dependencies_found']} yeni bağımlılık tespit edildi.",
            "",
            "<details><summary>Ham registry metadata'sı</summary>",
            "",
            "```json",
            json.dumps(deps_report, ensure_ascii=False, indent=2),
            "```",
            "",
            "</details>",
        ]

    lines += ["", "---", f"_head_sha: `{args.head_sha}`_"]
    print("\n".join(lines))
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
    p_codex.add_argument("--report-file", default="", help="Codex'in tam rapor metnini içeren dosya (tek PR yorumu için ledger'a yazılır)")
    p_codex.add_argument("--deps-report-file", default="", help="check_new_dependencies.py çıktısı JSON dosyası")
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

    p_render = sub.add_parser("render-comment", help="Tek, güncellenen PR yorumu için Markdown üret")
    p_render.add_argument("--repo", default=default_repo, help="owner/repo (varsayılan: $GITHUB_REPOSITORY)")
    p_render.add_argument("--pr", type=int, required=True)
    p_render.add_argument("--head-sha", required=True)
    p_render.set_defaults(func=cmd_render_comment)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
