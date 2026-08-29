#!/usr/bin/env python3
"""
alert_and_rotate.py

TruffleHog bir secret'ı "Verified: true" olarak işaretlediğinde (yani
gerçekten aktif olduğu doğrulandığında) devreye girer.

Bu script BİLİNÇLİ OLARAK secret'ı otomatik rotate ETMEZ — hangi servise
ait olursa olsun, bir credential'ı insan onayı olmadan invalidate etmek
başlı başına riskli bir otomasyondur (yanlış servisi etkileme, ekip
üyelerinin elindeki geçerli bir key'i habersizce kırma vb.). Bunun
yerine:

  1. Acil Telegram bildirimi gönderir (yalnızca redakte edilmiş bilgi).
  2. Ledger'a BLOCKING event yazar.
  3. Bir rotasyon kontrol listesi üretir (PR yorumuna eklenmek üzere).
  4. Merge'ü blokladığını netleştirir — yalnızca Şef'in
     "record-secret-rotated" onayı bu bloğu kaldırır.
"""

from __future__ import annotations

import sys

import ledger
import notifier


ROTATION_CHECKLIST_TEMPLATE = """\
## 🚨 Doğrulanmış (aktif) secret sızıntısı tespit edildi

TruffleHog aşağıdaki secret'ların **gerçekten aktif** olduğunu doğruladı:

{findings_list}

### Yapılması gerekenler (sırayla)

1. [ ] İlgili servis panelinden bu credential'ı **hemen invalidate/rotate** edin.
2. [ ] Yeni bir credential üretin ve yalnızca `.env` / GitHub Secrets üzerinden ekleyin.
3. [ ] Sızan değerin commit geçmişinden temizlenmesi gerekiyorsa
       (`git filter-repo` veya benzeri) bunu ayrı bir bakım işi olarak planlayın.
4. [ ] Rotasyon tamamlandığında şu komutu çalıştırın:
       ```
       python3 orchestrator/verifier.py record-secret-rotated --pr {pr} --confirmed-by "<adınız>"
       ```

Bu PR, yukarıdaki onay verilene kadar **merge edilemez**.
"""


def format_findings_list(redacted_findings: list[dict]) -> str:
    lines = []
    for f in redacted_findings:
        lines.append(f"- **{f['detector']}** — `{f['file']}:{f['line']}` (commit `{f['commit']}`)")
    return "\n".join(lines)


def build_rotation_checklist(pr_number: int, redacted_findings: list[dict]) -> str:
    return ROTATION_CHECKLIST_TEMPLATE.format(
        findings_list=format_findings_list(redacted_findings),
        pr=pr_number,
    )


def trigger(pr_number: int, pr_url: str, redacted_findings: list[dict]) -> None:
    """Alert + rotate akışının tamamını tetikler."""
    summary_lines = [
        f"{f['detector']} — {f['file']}:{f['line']}" for f in redacted_findings
    ]
    summary = "\n".join(summary_lines)

    notifier.send_telegram_message(
        f"🚨🚨 *DOĞRULANMIŞ SECRET SIZINTISI — PR #{pr_number}*\n\n"
        f"{summary}\n\n"
        f"Bu secret'lar AKTİF olduğu doğrulandı. Hemen rotate edilmeli.\n"
        f"[PR'ı incele]({pr_url})"
    )

    ledger.append_entry(ledger.LedgerEntry(
        pr=pr_number,
        event="secret_alert_triggered",
        data={"findings": redacted_findings, "severity": "BLOCKING"},
    ))

    checklist = build_rotation_checklist(pr_number, redacted_findings)
    print("--- PR yorumuna eklenecek rotasyon kontrol listesi ---")
    print(checklist)
    # Not: Bu script yalnızca içerik üretir. GitHub Actions workflow'u
    # bu çıktıyı `gh pr comment` ile PR'a yazar (bkz. verification.yml).


def record_rotation_confirmed(pr_number: int, confirmed_by: str) -> None:
    """Şef rotasyonu tamamladığını onayladığında çağrılır — bloğu kaldırır."""
    ledger.append_entry(ledger.LedgerEntry(
        pr=pr_number,
        event="secret_rotation_confirmed",
        data={"confirmed_by": confirmed_by},
    ))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Alert & Rotate CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_confirm = sub.add_parser("confirm-rotated")
    p_confirm.add_argument("pr", type=int)
    p_confirm.add_argument("confirmed_by")

    args = parser.parse_args()

    if args.command == "confirm-rotated":
        record_rotation_confirmed(args.pr, args.confirmed_by)
        print(f"Rotasyon onayı kaydedildi: PR #{args.pr} by {args.confirmed_by}")
    else:
        sys.exit(1)
