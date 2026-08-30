#!/usr/bin/env python3
"""
check_new_dependencies.py

PR'da eklenen YENİ bağımlılıkları (var olan bir paketin versiyon bump'ı
DEĞİL, ilk kez eklenen paketleri) tespit eder ve npm/PyPI registry'sinden
Reviewer Codex'in tedarik zinciri (supply-chain) incelemesi için gereken
ham metadata'yı çeker: ilk yayın tarihi, son güncelleme, maintainer bilgisi.

Bu script BİLİNÇLİ OLARAK bir "güvenli/güvensiz" kararı VERMEZ — Codex'in
kendi eğitim verisinden tahmin yürütmesi yerine, kör (blind) review'ında
yorumlayacağı gerçek zamanlı veriyi sağlar. Bilinen CVE taraması bu
script'in işi değildir (bkz. `npm audit` / `pip-audit` / osv-scanner,
DoD'de zaten zorunlu).

Kullanım:
    python3 scripts/check_new_dependencies.py --base origin/main --head HEAD

Çıktı: structured JSON, stdout'a. Registry'e ulaşılamazsa (ağ hatası,
zaman aşımı) o paket için metadata alanları null bırakılır — script
ASLA bu yüzden fail etmez, sadece eksik veriyle devam eder (Codex,
eksik metadata'yı kendisi ADVISORY olarak işaretleyebilir).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

REQUEST_TIMEOUT = 10

NPM_MANIFESTS = ["package.json"]
PYTHON_MANIFESTS = ["requirements.txt", "pyproject.toml", "Pipfile"]

# "dependencies"/"devDependencies" içindeki satırlar: "paket-adi": "^1.2.3"
NPM_LINE_RE = re.compile(r'^\+\s*"([A-Za-z0-9@/_.-]+)"\s*:\s*"[^"]+"\s*,?\s*$')

# requirements.txt: paket-adi==1.2.3 / paket-adi>=1.2.3 / paket-adi
PY_REQ_LINE_RE = re.compile(r'^\+\s*([A-Za-z0-9_.-]+)\s*(==|>=|<=|~=|>|<)?')

# pyproject.toml (PEP 621 / poetry) satırları: paket-adi = "^1.2.3" veya "paket-adi>=1.2.3",
PY_TOML_LINE_RE = re.compile(r'^\+\s*"?([A-Za-z0-9_.-]+)"?\s*=')


def git_diff(base: str, head: str, paths: list[str]) -> str:
    """İlgili manifest dosyalarının diff'ini döndürür; dosya yoksa boş string."""
    try:
        result = subprocess.run(
            ["git", "diff", f"{base}...{head}", "--"] + paths,
            capture_output=True, text=True, check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return ""


def extract_added_npm_deps(diff_text: str) -> set[str]:
    names = set()
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        m = NPM_LINE_RE.match(line)
        if m:
            key = m.group(1)
            if key not in ("name", "version", "description", "main", "scripts",
                            "dependencies", "devDependencies", "engines", "license"):
                names.add(key)
    return names


def extract_added_python_deps(diff_text: str) -> set[str]:
    names = set()
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+#") or line.strip() == "+":
            continue
        m = PY_REQ_LINE_RE.match(line) or PY_TOML_LINE_RE.match(line)
        if m:
            names.add(m.group(1).lower())
    return names


def removed_python_deps(diff_text: str) -> set[str]:
    """Silinen (-) satırlardaki paket adları — 'yeni eklenen' sayılmaması için."""
    names = set()
    for line in diff_text.splitlines():
        if not line.startswith("-") or line.startswith("---"):
            continue
        rebuilt = "+" + line[1:]
        m = PY_REQ_LINE_RE.match(rebuilt) or PY_TOML_LINE_RE.match(rebuilt)
        if m:
            names.add(m.group(1).lower())
    return names


def removed_npm_deps(diff_text: str) -> set[str]:
    names = set()
    for line in diff_text.splitlines():
        if not line.startswith("-") or line.startswith("---"):
            continue
        rebuilt = "+" + line[1:]
        m = NPM_LINE_RE.match(rebuilt)
        if m:
            names.add(m.group(1))
    return names


def fetch_json(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-verification-pipeline"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return {}


def npm_metadata(name: str) -> dict:
    data = fetch_json(f"https://registry.npmjs.org/{name}")
    if not data:
        return {"lookup_failed": True}
    time_info = data.get("time", {})
    maintainers = [m.get("name") for m in data.get("maintainers", []) if isinstance(m, dict)]
    return {
        "created": time_info.get("created"),
        "last_modified": time_info.get("modified"),
        "maintainers": maintainers,
        "latest_version": (data.get("dist-tags") or {}).get("latest"),
    }


def pypi_metadata(name: str) -> dict:
    data = fetch_json(f"https://pypi.org/pypi/{name}/json")
    if not data:
        return {"lookup_failed": True}
    info = data.get("info", {})
    releases = data.get("releases", {})
    first_release = None
    for files in releases.values():
        for f in files:
            t = f.get("upload_time_iso_8601")
            if t and (first_release is None or t < first_release):
                first_release = t
    return {
        "author": info.get("author") or None,
        "maintainer": info.get("maintainer") or None,
        "first_release": first_release,
        "latest_version": info.get("version"),
    }


def build_report(base: str, head: str) -> dict:
    npm_diff = git_diff(base, head, NPM_MANIFESTS)
    py_diff = git_diff(base, head, PYTHON_MANIFESTS)

    new_npm = extract_added_npm_deps(npm_diff) - removed_npm_deps(npm_diff)
    new_py = extract_added_python_deps(py_diff) - removed_python_deps(py_diff)

    npm_entries = [
        {"name": name, "registry": "npm", "metadata": npm_metadata(name)}
        for name in sorted(new_npm)
    ]
    py_entries = [
        {"name": name, "registry": "pypi", "metadata": pypi_metadata(name)}
        for name in sorted(new_py)
    ]

    return {
        "new_dependencies_found": len(npm_entries) + len(py_entries),
        "npm": npm_entries,
        "python": py_entries,
        "note": (
            "Bu rapor bir güvenlik kararı vermez — yalnızca ham registry "
            "metadata'sıdır. Reviewer Codex bunu typosquatting/bakım "
            "durumu/maintainer güvenilirliği açısından yorumlamalıdır. "
            "'lookup_failed: true' olan paketler için Codex bunu ADVISORY "
            "olarak işaretlemelidir (registry'e erişilemedi, manuel kontrol gerek)."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Yeni eklenen bağımlılıkları tespit et ve registry metadata'sı çek")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()

    report = build_report(args.base, args.head)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
