#!/usr/bin/env python3
"""
generate_ci_workflow.py

.github/workflows/ci.yml dosyasını proje stack'ini otomatik tespit ederek
üretir — elle YAML yazmaya gerek KALMAZ. `install_pipeline.sh` yeni bir
projeye bu pipeline'ı bağlarken bunu otomatik çağırır; kod eklendikten/
değiştikten sonra tekrar çalıştırmak istersen de doğrudan kullanabilirsin:

    python3 scripts/generate_ci_workflow.py /path/to/proje

Nasıl tespit ediyor:
  - Node/npm: <kök>/package.json ya da <kök>/{frontend,client,web,app}/package.json
    — bulursa "scripts" alanındaki gerçek script adlarına (lint, typecheck,
    test, build) bakar, YALNIZCA var olanları workflow'a ekler. package.json
    içinde devDependencies'te "@playwright/test" varsa E2E job'ı da ekler.
  - Python: <kök>/requirements.txt veya pyproject.toml, ya da
    <kök>/{backend,server,api}/ altında aynıları — pytest/ruff/mypy'nin
    gerçekten kurulu/kullanılıyor olup olmadığına (requirements.txt içeriği,
    tests/ klasörü, ruff/mypy config dosyası) bakar.
  - Hem Node hem Python bulunursa monorepo kabul edilir, ikisi ayrı job olur.
  - Hiçbiri bulunamazsa yalnızca secret-scan + AC-lock job'larıyla minimal
    bir ci.yml üretir ve ekrana "gerçek kod eklenince tekrar çalıştır" uyarısı
    basar — bu, henüz kod yazılmamış tertemiz bir proje için beklenen durumdur.

Bu script SESSİZCE YANLIŞ bir şey üretmez: bir şey bulamazsa/emin
olamazsa o adımı eklemez (fail-closed değil ama "az ve doğru" prensibi —
var olmayan bir script'i çağırıp CI'ı anlamsız yere kırmaktansa atlamayı
tercih eder).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

NODE_SUBDIRS = ["", "frontend", "client", "web", "app"]
PYTHON_SUBDIRS = ["", "backend", "server", "api"]


def _rel(root: Path, sub: str) -> Path:
    return root if sub == "" else root / sub


def detect_node(root: Path) -> dict | None:
    for sub in NODE_SUBDIRS:
        d = _rel(root, sub)
        pkg = d / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            scripts = data.get("scripts", {}) or {}
            dev_deps = data.get("devDependencies", {}) or {}
            deps = data.get("dependencies", {}) or {}
            has_playwright = "@playwright/test" in dev_deps or "@playwright/test" in deps
            has_stripe = "stripe" in deps or "stripe" in dev_deps
            return {
                "dir": sub,
                "scripts": {k: v for k, v in scripts.items() if k in ("lint", "typecheck", "test", "build")},
                "has_playwright": has_playwright,
                "has_stripe": has_stripe,
            }
    return None


def detect_python(root: Path) -> dict | None:
    for sub in PYTHON_SUBDIRS:
        d = _rel(root, sub)
        req = d / "requirements.txt"
        pyproj = d / "pyproject.toml"
        if not req.exists() and not pyproj.exists():
            continue
        content = ""
        if req.exists():
            content += req.read_text(encoding="utf-8", errors="ignore")
        if pyproj.exists():
            content += pyproj.read_text(encoding="utf-8", errors="ignore")
        content_lower = content.lower()
        has_tests_dir = (d / "tests").exists()
        return {
            "dir": sub,
            "has_pytest": "pytest" in content_lower or has_tests_dir,
            "has_ruff": "ruff" in content_lower,
            "has_mypy": "mypy" in content_lower,
        }
    return None


def _workdir_path(sub: str) -> str:
    return "/workspace" if sub == "" else f"/workspace/{sub}"


def build_node_job(node: dict) -> str:
    scripts = node["scripts"]
    workdir = _workdir_path(node["dir"])
    cmds = ["set -euo pipefail", "npm ci"]
    if "lint" in scripts:
        cmds.append("npm run lint")
    if "typecheck" in scripts:
        cmds.append("npm run typecheck")
    if "test" in scripts:
        cmds.append("npm test -- --ci")
    if "build" in scripts:
        cmds.append("npm run build")
    cmd_block = "\n".join(f"              {c}" for c in cmds)
    label = f"Frontend ({node['dir']})" if node["dir"] else "Frontend"
    return f"""  frontend-test:
    name: {label} Lint/Test/Build
    runs-on: [self-hosted, macOS, ARM64]
    needs: secret-scan
    steps:
      - uses: actions/checkout@v4

      - name: Bağımlılık kur + kontroller (container içinde, izole)
        run: |
          docker run --rm \\
            --cap-drop=ALL \\
            --security-opt=no-new-privileges:true \\
            -v "$PWD":/workspace -w {workdir} \\
            node:20-bookworm-slim \\
            bash -c "
{cmd_block}
            "
"""


def build_python_job(py: dict) -> str:
    workdir = _workdir_path(py["dir"])
    cmds = ["set -euo pipefail", "pip install -r requirements.txt"]
    if py["has_ruff"]:
        cmds.append("pip install ruff")
        cmds.append("ruff check .")
    if py["has_mypy"]:
        cmds.append("pip install mypy")
        cmds.append("mypy .")
    if py["has_pytest"]:
        cmds.append("pip install pytest")
        cmds.append("python -m pytest tests/")
        # NOT: "pytest tests/" DEĞİL "python -m pytest tests/" — çıplak
        # pytest binary'si cwd'yi sys.path'e eklemiyor, import hatası
        # veriyor (kuyumcukent-project'te gerçekten yaşanan bir bug'dı).
    cmd_block = "\n".join(f"              {c}" for c in cmds)
    label = f"Backend ({py['dir']})" if py["dir"] else "Backend"
    return f"""  backend-test:
    name: {label} Lint/Test
    runs-on: [self-hosted, macOS, ARM64]
    needs: secret-scan
    steps:
      - uses: actions/checkout@v4

      - name: Bağımlılık kur + kontroller (container içinde, izole)
        run: |
          docker run --rm \\
            --cap-drop=ALL \\
            --security-opt=no-new-privileges:true \\
            -v "$PWD":/workspace -w {workdir} \\
            python:3.12-slim \\
            bash -c "
{cmd_block}
            "
"""


def build_e2e_job(needs: list[str], has_stripe: bool = False) -> str:
    needs_str = ", ".join(needs)

    stripe_env = ""
    stripe_guard_step = ""
    stripe_docker_env = ""
    if has_stripe:
        # ÖNEMLİ (Codex review bulgusu — P1): Guard HOST'ta, container'a
        # secret hiç verilmeden ÖNCE çalışıyor. Eski tasarımda key
        # doğrudan `docker run -e` ile container'a veriliyor, guard ise
        # container İÇİNDE `npm ci` SIRASINDAN SONRA çalışıyordu — yani
        # PR'ın kendi lifecycle script'leri (npm ci sırasında) guard hiç
        # çalışmadan key'e erişebiliyordu. Artık key, guard geçmeden
        # container'a hiç ulaşmıyor.
        stripe_env = """    env:
      STRIPE_SECRET_KEY: ${{ secrets.STRIPE_TEST_SECRET_KEY }}
"""
        stripe_guard_step = """      - name: Stripe key modunu doğrula (host'ta, container'a VERİLMEDEN ÖNCE)
        run: bash scripts/check_stripe_key_mode.sh

"""
        stripe_docker_env = '            -e STRIPE_SECRET_KEY="$STRIPE_SECRET_KEY" \\\n'

    return f"""  e2e-playwright:
    name: Playwright E2E
    runs-on: [self-hosted, macOS, ARM64]
    needs: [{needs_str}]
{stripe_env}    steps:
      - uses: actions/checkout@v4

{stripe_guard_step}      - name: E2E testleri (container içinde, izole)
        run: |
          docker run --rm \\
            --ipc=host \\
{stripe_docker_env}            -v "$PWD":/workspace -w /workspace \\
            mcr.microsoft.com/playwright:v1.48.0-jammy \\
            bash -c "
              set -euo pipefail
              npm ci
              npx playwright test
            "

      - name: Test raporunu artifact olarak yükle
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-report
          path: playwright-report/
          retention-days: 7
"""


HEADER = """# FAST CI — otomatik üretildi (bkz. scripts/generate_ci_workflow.py).
# Elle yazılmadı — proje stack'i tespit edilip buna göre oluşturuldu.
# Yeni bağımlılık/klasör/script eklediğinde şu komutla YENİDEN üret:
#   python3 scripts/generate_ci_workflow.py .
#
# SANDBOX NOTU: Runner self-hosted VE macOS (Mac mini) olduğu için GitHub
# Actions'ın native `container:` job anahtarı KULLANILAMAZ (yalnızca Linux
# runner'da destekleniyor) — bunun yerine adımlar `docker run` ile izole
# ediliyor.

name: Fast CI

on:
  pull_request:
    branches: [main]

permissions:
  contents: read
  pull-requests: read

jobs:
  secret-scan:
    name: Secret Scan (gitleaks)
    runs-on: [self-hosted, macOS, ARM64]
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: gitleaks tara
        run: |
          gitleaks detect --source=. --redact --verbose --log-opts="origin/main..HEAD"

      - name: Güvenilir sonuç işleyicisini main'den stage'le
        # Codex review bulgusu (P1): TruffleHog hiçbir workflow'a bağlı
        # değildi. Şimdi buraya eklendi — ve sonucu işleyen script de
        # (PR'ın kendi checkout'undan çalıştırılırsa etkisizleştirilebileceği
        # için) izole bir dizinden çalıştırılıyor.
        id: stage
        run: |
          TRUSTED_DIR=$(git show origin/main:scripts/stage_trusted_orchestrator.sh | bash -s -- "$RUNNER_TEMP/trusted-orchestrator")
          echo "dir=$TRUSTED_DIR" >> "$GITHUB_OUTPUT"

      - name: TruffleHog ile doğrulanmış secret taraması
        id: trufflehog
        run: |
          set +e
          trufflehog git file://. \
            --since-commit=origin/main \
            --branch="${{ github.event.pull_request.head.sha }}" \
            --only-verified --json > trufflehog_output.jsonl 2> trufflehog_stderr.log
          echo "exit_code=$?" >> "$GITHUB_OUTPUT"

      - name: Python kur
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Orchestrator bağımlılıklarını kur
        run: pip install -r "${{ steps.stage.outputs.dir }}/orchestrator/requirements.txt"

      - name: TruffleHog sonucunu işle (ERROR/OK ayrımı net — sessiz "temiz" varsayımı YOK)
        env:
          PR_NUMBER: ${{ github.event.pull_request.number }}
          PR_URL: ${{ github.event.pull_request.html_url }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          python3 "${{ steps.stage.outputs.dir }}/orchestrator/trufflehog_result.py" \
            trufflehog_output.jsonl \
            --pr "$PR_NUMBER" \
            --pr-url "$PR_URL" \
            --head-sha "$HEAD_SHA" \
            --scan-exit-code "${{ steps.trufflehog.outputs.exit_code }}"

  ac-lock-check:
    name: AC Lock Bütünlüğü
    runs-on: [self-hosted, macOS, ARM64]
    needs: secret-scan
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Güvenilir AC lock doğrulayıcıyı main'den stage'le
        # PR checkout'undan çalıştırmak, PR'ın verify_ac_lock.py'yi
        # değiştirip kontrolü etkisizleştirmesine izin verirdi (Codex
        # review bulgusu — aynı sınıf risk, bkz. stage_trusted_orchestrator.sh).
        id: stage
        run: |
          TRUSTED_DIR=$(git show origin/main:scripts/stage_trusted_orchestrator.sh | bash -s -- "$RUNNER_TEMP/trusted-orchestrator")
          echo "dir=$TRUSTED_DIR" >> "$GITHUB_OUTPUT"
      - name: Python kur
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Orchestrator bağımlılıklarını kur (psycopg — AC lock artık Postgres'te)
        run: pip install -r "${{ steps.stage.outputs.dir }}/orchestrator/requirements.txt"
      - name: AC lock doğrula
        run: python3 "${{ steps.stage.outputs.dir }}/scripts/verify_ac_lock.py"

"""


def generate(root: Path) -> tuple[str, list[str]]:
    node = detect_node(root)
    py = detect_python(root)

    notes = []
    body = HEADER
    e2e_needs = []

    if py:
        body += build_python_job(py)
        e2e_needs.append("backend-test")
        notes.append(f"Backend tespit edildi: '{py['dir'] or '.'}' (pytest={py['has_pytest']}, ruff={py['has_ruff']}, mypy={py['has_mypy']})")
    if node:
        body += build_node_job(node)
        e2e_needs.append("frontend-test")
        notes.append(f"Frontend tespit edildi: '{node['dir'] or '.'}' (scripts={list(node['scripts'].keys())})")
        if node["has_playwright"]:
            body += build_e2e_job(e2e_needs, has_stripe=node["has_stripe"])
            notes.append("Playwright tespit edildi, E2E job'ı eklendi.")
            if node["has_stripe"]:
                notes.append("Stripe bağımlılığı tespit edildi, E2E job'ına test-mode key guard'ı eklendi.")

    if not node and not py:
        notes.append(
            "UYARI: Ne Node ne Python projesi tespit edildi (package.json/"
            "requirements.txt/pyproject.toml bulunamadı). Yalnızca secret-scan "
            "+ ac-lock-check job'ları üretildi. Gerçek kod ekledikten sonra bu "
            "script'i tekrar çalıştırın: python3 scripts/generate_ci_workflow.py ."
        )

    return body, notes


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    target = target.resolve()

    if not target.exists():
        print(f"HATA: dizin bulunamadı: {target}", file=sys.stderr)
        return 1

    workflow, notes = generate(target)

    out_dir = target / ".github" / "workflows"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ci.yml"
    out_path.write_text(workflow, encoding="utf-8")

    print(f"Üretildi: {out_path}")
    for n in notes:
        print(f"  - {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
