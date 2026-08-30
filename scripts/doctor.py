#!/usr/bin/env python3
"""
doctor.py — Kurulumu (host seviyesi + proje seviyesi) doğrular, eksikleri
tek komutla listeler. Codex'in önerdiği "kurulum doğrulayıcı" özelliği.

Kullanım:
    python3 scripts/doctor.py [--repo owner/repo]

`--repo` verilirse GitHub tarafı da (secrets, branch protection, runner)
kontrol edilir — bunun için `gh` CLI'ın o repoya erişimi olmalı.

Bu script hiçbir şeyi DEĞİŞTİRMEZ, yalnızca teşhis koyar. Her kontrol
✅/⚠️/❌ ile raporlanır, sonunda özet + exit code (0=hepsi OK, 1=en az
bir ❌ var).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CHECK = "✅"
WARN = "⚠️ "
FAIL = "❌"


class Report:
    def __init__(self) -> None:
        self.failed = False
        self.lines: list[str] = []

    def ok(self, msg: str) -> None:
        self.lines.append(f"{CHECK} {msg}")

    def warn(self, msg: str) -> None:
        self.lines.append(f"{WARN} {msg}")

    def fail(self, msg: str) -> None:
        self.lines.append(f"{FAIL} {msg}")
        self.failed = True

    def section(self, title: str) -> None:
        self.lines.append(f"\n== {title} ==")


def _cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.returncode, (result.stdout + result.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, str(e)


def check_host_tools(r: Report) -> None:
    r.section("Host araçları (Mac mini'de bir kere kurulur)")
    for tool in ("gitleaks", "trufflehog", "docker", "codex", "gh"):
        if _cmd_exists(tool):
            r.ok(f"{tool} kurulu")
        else:
            r.fail(f"{tool} PATH'te bulunamadı — brew install {tool}")

    code, out = _run(["docker", "info"])
    if code == 0:
        r.ok("Docker daemon çalışıyor")
    else:
        r.fail("Docker daemon çalışmıyor (Docker Desktop'ı başlatın)")

    code, out = _run(["codex", "login", "status"])
    if code == 0 and "logged in" in out.lower():
        r.ok("codex CLI authenticated")
    else:
        r.fail("codex CLI login değil — `codex login --device-auth` çalıştırın")


def check_postgres(r: Report) -> None:
    r.section("PostgreSQL (Verification Ledger)")
    database_url = os.environ.get("DATABASE_URL", "postgresql://pipeline_app@localhost/verification_pipeline")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
        import ledger  # noqa: PLC0415

        with ledger._connect():  # noqa: SLF001 — teşhis amaçlı doğrudan bağlantı testi
            pass
        r.ok(f"Postgres bağlantısı başarılı ({database_url})")
    except Exception as e:  # noqa: BLE001 — teşhis script'i, her hatayı yakalayıp raporlamalı
        r.fail(f"Postgres'e bağlanılamadı: {e}")


def check_local_env(r: Report, project_dir: Path) -> None:
    r.section("Proje dizini")
    if (project_dir / ".env").exists():
        r.ok(".env mevcut")
    else:
        r.warn(".env yok — `cp .env.example .env` ile oluşturup doldurun")

    if (project_dir / ".github" / "workflows" / "ci.yml").exists():
        r.ok("ci.yml üretilmiş")
    else:
        r.warn("ci.yml yok — `python3 scripts/generate_ci_workflow.py .` çalıştırın")

    if (project_dir / ".git" / "hooks" / "pre-commit").exists():
        r.ok("pre-commit hook kurulu")
    else:
        r.warn("pre-commit hook kurulu değil")

    if (project_dir / "AGENTS.md").exists():
        r.ok("AGENTS.md mevcut")
    else:
        r.warn("AGENTS.md yok")


def check_github(r: Report, repo: str) -> None:
    r.section(f"GitHub: {repo}")

    code, out = _run(["gh", "repo", "view", repo])
    if code != 0:
        r.fail(f"{repo} erişilemiyor: {out}")
        return
    r.ok("repo erişilebilir")

    # Self-hosted runner (org seviyesinde kayıtlı mı, online mı)
    org = repo.split("/")[0]
    code, out = _run(["gh", "api", f"orgs/{org}/actions/runners"])
    if code == 0:
        try:
            data = json.loads(out)
            runners = data.get("runners", [])
            online = [x for x in runners if x.get("status") == "online"]
            if online:
                r.ok(f"self-hosted runner online ({len(online)}/{len(runners)})")
            else:
                r.fail("self-hosted runner kayıtlı ama ONLINE değil")
        except json.JSONDecodeError:
            r.warn("runner listesi parse edilemedi")
    else:
        r.warn(f"runner listesi alınamadı (org seviyesinde admin erişimi gerekebilir): {out}")

    # GitHub Secrets — yalnızca isim listesi görülebilir, değer değil
    code, out = _run(["gh", "secret", "list", "--repo", repo])
    if code == 0:
        secret_names = {line.split()[0] for line in out.splitlines() if line.strip()}
        for needed in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            if needed in secret_names:
                r.ok(f"GitHub Secret '{needed}' tanımlı")
            else:
                r.warn(f"GitHub Secret '{needed}' TANIMLI DEĞİL — Telegram bildirimleri CI'da sessizce atlanır")
    else:
        r.warn(f"secret listesi alınamadı: {out}")

    # Branch protection — context isimleri gerçek job isimleriyle eşleşiyor mu (yaklaşık kontrol)
    code, out = _run(["gh", "api", f"repos/{repo}/branches/main/protection"])
    if code == 0:
        try:
            data = json.loads(out)
            contexts = data.get("required_status_checks", {}).get("contexts", [])
            if "verification-gate" in contexts:
                r.ok("branch protection 'verification-gate'i zorunlu tutuyor")
            else:
                r.fail("branch protection 'verification-gate'i ZORUNLU TUTMUYOR — merge Codex/secret kontrolüne bağlı değil")
            if "Secret Scan (gitleaks)" in contexts:
                r.ok("branch protection 'Secret Scan (gitleaks)'i zorunlu tutuyor")
            else:
                r.warn("branch protection 'Secret Scan (gitleaks)'i zorunlu tutmuyor")
        except json.JSONDecodeError:
            r.warn("branch protection yanıtı parse edilemedi")
    else:
        r.fail(f"branch protection okunamadı (hiç kurulmamış olabilir): {out}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Kurulum doğrulayıcı")
    parser.add_argument("--repo", default="", help="owner/repo — verilirse GitHub tarafı da kontrol edilir")
    parser.add_argument("--project-dir", default=".", help="Proje dizini (varsayılan: cwd)")
    args = parser.parse_args()

    r = Report()
    check_host_tools(r)
    check_postgres(r)
    check_local_env(r, Path(args.project_dir).resolve())
    if args.repo:
        check_github(r, args.repo)
    else:
        r.section("GitHub")
        r.warn("--repo verilmedi, GitHub tarafı (runner/secrets/branch protection) kontrol edilmedi")

    print("\n".join(r.lines))
    print()
    if r.failed:
        print(f"{FAIL} En az bir kritik eksik var — yukarıya bakın.")
        return 1
    print(f"{CHECK} Tüm kritik kontroller geçti (uyarılar varsa gözden geçirin).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
