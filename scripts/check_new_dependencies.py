#!/usr/bin/env python3
"""
check_new_dependencies.py

PR'da eklenen YENİ bağımlılıkları (var olan bir paketin versiyon bump'ı
DEĞİL, ilk kez eklenen paketleri) tespit eder ve npm/PyPI registry'sinden
Reviewer Codex'in tedarik zinciri (supply-chain) incelemesi için gereken
ham metadata'yı çeker: ilk yayın tarihi, son güncelleme, maintainer bilgisi.

ÖNEMLİ (Codex review bulgusu — P1): Eski sürüm `git diff` ÇIKTISINI satır
satır regex'le parse ediyordu — bu üç ayrı şekilde yanlış sonuç
üretiyordu:
  1. PEP 621 formatlı `pyproject.toml` bağımlılıkları ("requests>=2" gibi
     TOML dizi elemanları) regex'le eşleşmiyordu, tamamen KAÇIYORDU.
  2. npm'de "scripts" gibi bir anahtarın altındaki key'ler (ör.
     "build": "vite build") paket sanılabiliyordu.
  3. `git diff` komutu HATA verirse (ör. base ref bulunamazsa) sessizce
     boş sonuç dönüp "yeni paket yok" diye raporlanıyordu — registry
     erişim hatasından FARKLI bir durum, ama aynı şekilde ele alınıyordu.

ÇÖZÜM: Artık diff satırlarını regex'lemek yerine, base ve head
commit'lerindeki TAM manifest dosyalarını (`git show <ref>:<path>`)
GERÇEK parser'larla (JSON için `json`, TOML için `tomllib`, requirements.txt
için PEP 508 uyumlu bir regex TEK SATIRIN TAMAMINA, diff prefix'ine değil)
okuyup bağımlılık İSİMLERİ kümesini karşılaştırıyor. Bu hem PEP 621'i
doğru okuyor hem npm'in yalnızca gerçek dependency/devDependency
anahtarlarına bakıyor.

Git/parse hatası artık AYRI bir "error" alanında raporlanıyor ve script
bu durumda exit 1 dönüyor — "registry'e ulaşılamadı" (ADVISORY, devam
edilebilir) ile "manifest hiç okunamadı" (analiz güvenilir değil)
KARIŞTIRILMIYOR.

Bilinen CVE taraması bu script'in işi değildir (bkz. `npm audit` /
`pip-audit` / osv-scanner, DoD'de zaten zorunlu).

Kullanım:
    python3 scripts/check_new_dependencies.py --base origin/main --head HEAD
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

REQUEST_TIMEOUT = 10

NPM_MANIFEST = "package.json"
PYTHON_MANIFESTS = ["requirements.txt", "pyproject.toml"]

# PEP 508 paket adı grameri (basitleştirilmiş): harf/rakamla başlar,
# içinde -._ olabilir. Versiyon belirteci (==, >=, ;, [extra]) öncesi
# kısım paket adıdır. Bu, TAM SATIR üzerinde çalışır (diff prefix'i değil).
PY_PACKAGE_NAME_RE = re.compile(r'^\s*"?([A-Za-z0-9][A-Za-z0-9._-]*)')


class GitError(Exception):
    """git komutu beklenmedik şekilde başarısız oldu — bu 'dosya yok' değil, GERÇEK bir hata."""


def git_show(ref: str, path: str) -> str | None:
    """
    `ref` üzerindeki `path` dosyasının tam içeriğini döndürür.
    Dosya o ref'te hiç yoksa None döner (GEÇERLİ bir durum — ör. base'de
    henüz eklenmemiş bir manifest). Başka bir git hatası (bozuk ref,
    erişilemeyen repo vb.) GitError fırlatır — bu SESSİZCE yutulmaz.
    """
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return result.stdout
    stderr = result.stderr.lower()
    if "does not exist" in stderr or "exists on disk, but not in" in stderr:
        return None  # dosya o ref'te yok — geçerli, "henüz eklenmemiş" demek
    raise GitError(f"git show {ref}:{path} başarısız: {result.stderr.strip()}")


def npm_dependency_names(content: str | None) -> set[str]:
    if content is None:
        return set()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise GitError(f"package.json parse edilemedi (bozuk JSON)")
    names = set(data.get("dependencies", {}) or {})
    names |= set(data.get("devDependencies", {}) or {})
    return names


def requirements_txt_names(content: str | None) -> set[str]:
    if content is None:
        return set()
    names = set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        m = PY_PACKAGE_NAME_RE.match(line)
        if m:
            names.add(m.group(1).lower())
    return names


def pyproject_toml_names(content: str | None) -> set[str]:
    if content is None:
        return set()
    if tomllib is None:
        raise GitError("tomllib mevcut değil (Python < 3.11) — pyproject.toml parse edilemiyor")
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        raise GitError("pyproject.toml parse edilemedi (bozuk TOML)")

    names: set[str] = set()

    # PEP 621: [project] dependencies = ["requests>=2", "click"]
    project_deps = (data.get("project") or {}).get("dependencies", []) or []
    for dep_str in project_deps:
        m = PY_PACKAGE_NAME_RE.match(dep_str)
        if m:
            names.add(m.group(1).lower())
    optional_deps = (data.get("project") or {}).get("optional-dependencies", {}) or {}
    for dep_list in optional_deps.values():
        for dep_str in dep_list:
            m = PY_PACKAGE_NAME_RE.match(dep_str)
            if m:
                names.add(m.group(1).lower())

    # Poetry: [tool.poetry.dependencies] requests = "^2.0"
    poetry_deps = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies", {}) or {}
    names |= {k.lower() for k in poetry_deps if k.lower() != "python"}

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
    base_npm = git_show(base, NPM_MANIFEST)
    head_npm = git_show(head, NPM_MANIFEST)
    new_npm = npm_dependency_names(head_npm) - npm_dependency_names(base_npm)

    new_py: set[str] = set()
    for manifest in PYTHON_MANIFESTS:
        base_content = git_show(base, manifest)
        head_content = git_show(head, manifest)
        parser = requirements_txt_names if manifest == "requirements.txt" else pyproject_toml_names
        new_py |= parser(head_content) - parser(base_content)

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

    try:
        report = build_report(args.base, args.head)
    except GitError as e:
        # Codex review bulgusu: bu HATA registry erişim hatasından farklı —
        # manifest hiç okunamadı/parse edilemedi, "yeni paket yok" ile
        # KARIŞTIRILMAMALI. Rapor yine üretilir ama "error" alanıyla
        # işaretlenir ve exit code 1 döner.
        print(json.dumps({
            "new_dependencies_found": None,
            "npm": [],
            "python": [],
            "error": str(e),
            "note": "Manifest okuma/parse hatası — bu bir 'yeni bağımlılık yok' sonucu DEĞİLDİR, analiz güvenilir değildir.",
        }, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
