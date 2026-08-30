#!/usr/bin/env bash
#
# check_pipeline_version.sh — hedef bir projenin kurulu pipeline sürümünü,
# BU kaynak repodaki (ai-verification-pipeline) GÜNCEL sürümle karşılaştırır.
#
# NEDEN (Codex'in önerdiği özellik): install_pipeline.sh ile kopyalanan
# dosyalar zamanla kaynaktan sapabilir — bir projede bug fix'i alıp
# diğerinde almamak, hangi projenin hangi düzeltmeye sahip olduğunu takip
# edilemez hale getirir. Bu script, hedefin `.pipeline-meta.json`'ına
# bakıp güncel mi diye söyler — OTOMATİK GÜNCELLEME YAPMAZ (install_pipeline.sh
# zaten var olan dosyaları yedekleyerek güvenli şekilde tekrar çalıştırılabilir,
# güncelleme = o script'i tekrar çalıştırmaktır).
#
# Kullanım:
#   bash scripts/check_pipeline_version.sh /path/to/proje

set -euo pipefail

SOURCE_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-.}"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"

SOURCE_VERSION=$(cat "$SOURCE_REPO_ROOT/PIPELINE_VERSION" 2>/dev/null || echo "bilinmiyor")
SOURCE_COMMIT=$(git -C "$SOURCE_REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo "bilinmiyor")

META_FILE="$TARGET_DIR/.pipeline-meta.json"

if [[ ! -f "$META_FILE" ]]; then
  echo "UYARI: $META_FILE yok — bu proje install_pipeline.sh'in eski (versiyon" >&2
  echo "takibi olmayan) bir sürümüyle kurulmuş olabilir, ya da hiç kurulmamış." >&2
  echo "Kaynak repo güncel sürüm: $SOURCE_VERSION (commit $SOURCE_COMMIT)" >&2
  exit 1
fi

TARGET_VERSION=$(python3 -c "import json; print(json.load(open('$META_FILE')).get('version', 'bilinmiyor'))")
TARGET_COMMIT=$(python3 -c "import json; print(json.load(open('$META_FILE')).get('source_commit', 'bilinmiyor'))")
INSTALLED_AT=$(python3 -c "import json; print(json.load(open('$META_FILE')).get('installed_at', 'bilinmiyor'))")

echo "Hedef proje:     $TARGET_DIR"
echo "  Kurulu sürüm:  $TARGET_VERSION (commit $TARGET_COMMIT, kurulum: $INSTALLED_AT)"
echo "Kaynak repo:      $SOURCE_REPO_ROOT"
echo "  Güncel sürüm:  $SOURCE_VERSION (commit $SOURCE_COMMIT)"
echo ""

if [[ "$TARGET_VERSION" == "$SOURCE_VERSION" && "$TARGET_COMMIT" == "$SOURCE_COMMIT" ]]; then
  echo "✅ Güncel — kurulu pipeline, kaynağın en son haliyle aynı."
  exit 0
else
  echo "⚠️  GÜNCEL DEĞİL — kaynak repo bu kurulumdan sonra değişmiş."
  echo "   Güncellemek için tekrar çalıştırın (var olan dosyalar otomatik yedeklenir):"
  echo "   bash scripts/install_pipeline.sh $TARGET_DIR"
  exit 2
fi
