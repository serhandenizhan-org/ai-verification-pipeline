#!/usr/bin/env bash
#
# install_pipeline.sh — Bu AI Verification Pipeline'ı yeni bir projeye bağlar.
#
# Bu script'i BU repodan (ai-verification-pipeline) çalıştırın, hedef olarak
# yeni projenizin yolunu verin:
#
#   bash scripts/install_pipeline.sh /path/to/new-project [owner/repo]
#
# [owner/repo] verilirse (ör. serhandenizhan-org/kuyumcukent-project) ve
# `gh` CLI o repoya erişebiliyorsa, script ayrıca:
#   - Gerekli label'ları oluşturur (needs-codex-review, ready-for-human-approval)
#   - Branch protection'ı kurar (solo-friendly: onay şartı yok, yalnızca
#     gitleaks zorunlu status check — bkz. HANDOFF.md, bu ayarları elle
#     bulmak saatler sürmüştü, script bunu tekrar keşfetmenize gerek
#     bırakmıyor)
#
# ci.yml ARTIK ELLE YAZILMIYOR: scripts/generate_ci_workflow.py, hedef
# projenin package.json/requirements.txt/pyproject.toml'una bakarak stack'i
# (Node/Python/monorepo) otomatik tespit eder ve ci.yml'i üretir. Kod
# eklendikçe/değiştikçe (yeni script, yeni klasör) tekrar çalıştırabilirsiniz:
#   python3 scripts/generate_ci_workflow.py .
#
# NE KOPYALANMAZ (bilinçli olarak):
#   - .env — .env.example kopyalanır, gerçek secret'ları siz doldurursunuz.
#
# YEDEKLEME (Codex review bulgusu — P1): Bu script'i ZATEN kurulu bir
# projeye TEKRAR çalıştırırsanız (ör. güncelleme almak için), var olan
# HER dosya üzerine yazmadan ÖNCE `.pipeline-install-backup-<zaman damgası>/`
# altına yedeklenir — CLAUDE.md, .claude/settings.json, AGENTS.md,
# pre-commit hook dahil. Script sonunda hangi dosyaların yedeklendiği
# özetlenir. Eskiden bunlar SESSİZCE eziliyordu, git'e alınmamış elle
# yapılmış özelleştirmeler geri getirilemez şekilde kaybolabiliyordu.
#
# ÖN KOŞULLAR (Mac mini'de bir kere kurulur, proje başına değil):
#   - gitleaks, trufflehog (brew)
#   - PostgreSQL (brew services start postgresql@16) — ledger için
#   - codex CLI, `codex login --device-auth` ile authenticated
#   - Self-hosted GitHub Actions runner org seviyesinde kayıtlı ve çalışıyor
#   Bunlar eksikse script sonunda uyarır ama devam eder (fail-closed değil,
#   bunlar tek seferlik host kurulumu, proje bootstrap'ının parçası değil).

set -euo pipefail

SOURCE_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-}"
GITHUB_REPO="${2:-}"

if [[ -z "$TARGET_DIR" ]]; then
  echo "Kullanım: $0 /path/to/new-project [owner/repo]" >&2
  exit 1
fi

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "HATA: Hedef dizin bulunamadı: $TARGET_DIR" >&2
  exit 1
fi

TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
BACKUP_DIR="$TARGET_DIR/.pipeline-install-backup-$(date +%Y%m%d-%H%M%S)"
BACKED_UP_FILES=()

echo "== AI Verification Pipeline kuruluyor =="
echo "Kaynak: $SOURCE_REPO_ROOT"
echo "Hedef:  $TARGET_DIR"
echo ""

# Var olan bir dosyanın üzerine yazmadan önce yedekler. `dest` MUTLAK yol
# olmalı ve $TARGET_DIR altında olmalı.
_backup_if_exists() {
  local dest="$1"
  local rel="${dest#"$TARGET_DIR"/}"
  if [[ -e "$dest" ]]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
    cp -R "$dest" "$BACKUP_DIR/$rel"
    BACKED_UP_FILES+=("$rel")
  fi
}

# cp'nin yedeklemeli sürümü — src'yi dest'e kopyalar, dest zaten varsa önce yedekler.
safe_copy() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  _backup_if_exists "$dest"
  cp -R "$src" "$dest"
}

# Heredoc/üretilmiş içerik dest'e yazılmadan önce dest'i yedekler.
# Kullanım: safe_write_start "$dest"; cat > "$dest" <<'EOF' ... EOF
safe_write_start() {
  local dest="$1"
  mkdir -p "$(dirname "$dest")"
  _backup_if_exists "$dest"
}

# --- orchestrator/ (stack-agnostic, olduğu gibi kopyalanır) ---
mkdir -p "$TARGET_DIR/orchestrator"
for f in router.py verifier.py ledger.py circuit_breaker.py notifier.py \
         alert_and_rotate.py trufflehog_result.py ac_lock.py requirements.txt schema.sql; do
  safe_copy "$SOURCE_REPO_ROOT/orchestrator/$f" "$TARGET_DIR/orchestrator/$f"
done
echo "kopyalandı: orchestrator/"

# --- scripts/ ---
mkdir -p "$TARGET_DIR/scripts/git-hooks"
for f in lock_ac.sh verify_ac_lock.sh verify_ac_lock.py check_stripe_key_mode.sh \
         check_new_dependencies.py pin_trusted_files.sh generate_ci_workflow.py \
         stage_trusted_orchestrator.sh; do
  safe_copy "$SOURCE_REPO_ROOT/scripts/$f" "$TARGET_DIR/scripts/$f"
done
safe_copy "$SOURCE_REPO_ROOT/scripts/git-hooks/pre-commit" "$TARGET_DIR/scripts/git-hooks/pre-commit"
chmod +x "$TARGET_DIR"/scripts/*.sh "$TARGET_DIR/scripts/git-hooks/pre-commit"
echo "kopyalandı: scripts/"

# --- specs/ (DoD + security baseline sabit, AC şablonu generic) ---
mkdir -p "$TARGET_DIR/specs/features/example-feature"
safe_copy "$SOURCE_REPO_ROOT/specs/dod.md" "$TARGET_DIR/specs/dod.md"
safe_copy "$SOURCE_REPO_ROOT/specs/security-baseline.md" "$TARGET_DIR/specs/security-baseline.md"
safe_copy "$SOURCE_REPO_ROOT/specs/features/example-feature/acceptance_criteria.yaml" \
   "$TARGET_DIR/specs/features/example-feature/acceptance_criteria.yaml"
echo "kopyalandı: specs/"

# --- CLAUDE.md (Builder rolü, sabit) + model pinning ---
# Orchestrator (ai-verification-pipeline reposu) her zaman Opus'a sabit;
# Builder (bu hedef proje) her zaman Sonnet'e sabit. İkisi de ayrı Claude
# Code sohbeti/oturumu olarak açılır — Şef "sen builder'sın" demek zorunda
# kalmaz, .claude/settings.json + CLAUDE.md otomatik yüklenir.
safe_copy "$SOURCE_REPO_ROOT/specs/builder_claude_template.md" "$TARGET_DIR/CLAUDE.md"
SETTINGS_DEST="$TARGET_DIR/.claude/settings.json"
safe_write_start "$SETTINGS_DEST"
cat > "$SETTINGS_DEST" <<'SETTINGS_EOF'
{
  "model": "sonnet"
}
SETTINGS_EOF
echo "kopyalandı: CLAUDE.md (Builder rolü) + .claude/settings.json (model: sonnet)"

# --- verification/ (Codex kuralları + trufflehog dokümantasyonu) ---
mkdir -p "$TARGET_DIR/verification/codex" "$TARGET_DIR/verification/trufflehog"
safe_copy "$SOURCE_REPO_ROOT/verification/codex/severity_rules.md" \
   "$TARGET_DIR/verification/codex/severity_rules.md"
safe_copy "$SOURCE_REPO_ROOT/verification/trufflehog/README.md" \
   "$TARGET_DIR/verification/trufflehog/README.md"
echo "kopyalandı: verification/"

# --- AGENTS.md (Codex CLI'ın otomatik okuduğu reviewer talimatları) ---
safe_copy "$SOURCE_REPO_ROOT/AGENTS.md" "$TARGET_DIR/AGENTS.md"
echo "kopyalandı: AGENTS.md"

# --- .github/workflows/ ---
mkdir -p "$TARGET_DIR/.github/workflows"
safe_copy "$SOURCE_REPO_ROOT/.github/workflows/verification.yml" \
   "$TARGET_DIR/.github/workflows/verification.yml"
safe_copy "$SOURCE_REPO_ROOT/.github/branch-protection.md" \
   "$TARGET_DIR/.github/branch-protection.md"
echo "kopyalandı: .github/workflows/verification.yml (olduğu gibi)"

# ci.yml artık ELLE YAZILMIYOR — proje stack'i otomatik tespit edilip
# üretiliyor (bkz. scripts/generate_ci_workflow.py). generate_ci_workflow.py
# kendi ci.yml çıktısını YAZIYOR (bu script'in cp'si değil) — o script de
# hedef dosya varsa üzerine yazıyor, ama bu bilinçli: ci.yml zaten stack
# değiştikçe yeniden üretilmesi gereken bir dosya, "kişisel özelleştirme"
# saklanacak bir dosya değil. Yine de var olan bir ci.yml'i kaybetmemek
# için burada da yedekliyoruz.
safe_write_start "$TARGET_DIR/.github/workflows/ci.yml"
echo "ci.yml otomatik üretiliyor (proje stack'i tespit ediliyor)..."
python3 "$TARGET_DIR/scripts/generate_ci_workflow.py" "$TARGET_DIR"

# --- .env.example ---
safe_copy "$SOURCE_REPO_ROOT/.env.example" "$TARGET_DIR/.env.example"
echo "kopyalandı: .env.example"

# --- .verification/ (ledger artık Postgres'te ama circuit breaker state hâlâ dosya) ---
mkdir -p "$TARGET_DIR/.verification/state"
touch "$TARGET_DIR/.verification/state/.gitkeep"
echo "oluşturuldu: .verification/state/"

# --- .gitignore ekleri (zaten ek yapıyor, üzerine yazmıyor — yedeklemeye gerek yok) ---
GITIGNORE_ADDITIONS='
# --- AI Verification Pipeline ---
.env
.env.local
verification/playwright/test.env
*.pem
*.key
secrets.json
__pycache__/
*.pyc
.venv/
.verification/state/*.json
.pipeline-install-backup-*/
'
if [[ -f "$TARGET_DIR/.gitignore" ]]; then
  if ! grep -q "AI Verification Pipeline" "$TARGET_DIR/.gitignore" 2>/dev/null; then
    echo "$GITIGNORE_ADDITIONS" >> "$TARGET_DIR/.gitignore"
    echo "güncellendi: .gitignore (pipeline ekleri eklendi)"
  else
    echo "atlandı: .gitignore zaten pipeline eklerini içeriyor"
  fi
else
  echo "$GITIGNORE_ADDITIONS" > "$TARGET_DIR/.gitignore"
  echo "oluşturuldu: .gitignore"
fi

# --- pre-commit hook kurulumu (hedef bir git reposuysa) ---
if [[ -d "$TARGET_DIR/.git" ]]; then
  safe_copy "$TARGET_DIR/scripts/git-hooks/pre-commit" "$TARGET_DIR/.git/hooks/pre-commit"
  chmod +x "$TARGET_DIR/.git/hooks/pre-commit"
  echo "kuruldu: .git/hooks/pre-commit"
else
  echo "UYARI: $TARGET_DIR bir git reposu değil, pre-commit hook kurulamadı." >&2
fi

echo ""
echo "== Dosya kopyalama tamamlandı =="

if [[ ${#BACKED_UP_FILES[@]} -gt 0 ]]; then
  echo ""
  echo "== ${#BACKED_UP_FILES[@]} var olan dosya EZİLMEDEN ÖNCE yedeklendi =="
  echo "Yedek konumu: $BACKUP_DIR"
  for f in "${BACKED_UP_FILES[@]}"; do
    echo "  - $f"
  done
  echo "Bir şey kayboldu sanıyorsanız yukarıdaki dizine bakın."
fi
echo ""

# --- GitHub tarafı (opsiyonel — owner/repo verildiyse ve gh erişebiliyorsa) ---
if [[ -n "$GITHUB_REPO" ]]; then
  if ! command -v gh &> /dev/null; then
    echo "UYARI: gh CLI kurulu değil, GitHub kurulumu (label/branch protection) atlanıyor." >&2
  elif ! gh repo view "$GITHUB_REPO" &> /dev/null; then
    echo "UYARI: $GITHUB_REPO erişilemiyor (henüz push edilmemiş olabilir), GitHub kurulumu atlanıyor." >&2
    echo "       Push ettikten sonra şunu elle çalıştırabilirsiniz:" >&2
    echo "       bash scripts/setup_github.sh $GITHUB_REPO" >&2
  else
    echo "== GitHub kurulumu: $GITHUB_REPO =="
    gh label create "needs-codex-review" --repo "$GITHUB_REPO" \
      --color "FBCA04" --description "Risk seviyesi Codex deep review gerektiriyor" 2>&1 || true
    gh label create "ready-for-human-approval" --repo "$GITHUB_REPO" \
      --color "0E8A16" --description "CI ve Codex geçti, Şef onayı bekleniyor" 2>&1 || true

    # NOT: required_status_checks context'leri GERÇEK adlarla BİREBİR
    # eşleşmeli — context adı job adıyla eşleşmezse branch protection asla
    # "yeşil" görmez (bu repoda saatlerce süren gerçek bir hataydı, bkz.
    # HANDOFF.md). İki context de zorunlu:
    #   - "Secret Scan (gitleaks)": Fast CI'ın erken/hızlı katmanı
    #   - "verification-gate": TEK bağlayıcı karar (risk + Codex review +
    #     circuit breaker + secret rotasyonu hepsi buna dahil, bkz.
    #     verification.yml + verifier.py cmd_gate). Codex review bulgusu:
    #     önceden hiçbir status bu kararı GERÇEKTEN merge'e bağlamıyordu.
    gh api "repos/$GITHUB_REPO/branches/main/protection" --method PUT --input - <<'EOF' 2>&1 || true
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Secret Scan (gitleaks)", "verification-gate"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0
  },
  "restrictions": null,
  "required_linear_history": true,
  "required_conversation_resolution": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
    echo "GitHub kurulumu tamamlandı (label'lar + branch protection)."
  fi
else
  echo "owner/repo verilmedi — GitHub kurulumu (label/branch protection) atlandı."
fi

echo ""
echo "== Sıradaki elle yapılacaklar =="
echo "1. cd $TARGET_DIR"
echo "2. cp .env.example .env  ve  .env'i doldurun"
echo "3. ci.yml zaten otomatik üretildi — üretilen dosyayı bir göz gezdirin"
echo "   (.github/workflows/ci.yml), kod eklendikçe yeniden üretmek için:"
echo "   python3 scripts/generate_ci_workflow.py ."
echo "4. Gerçek bir feature için specs/features/<isim>/ oluşturup"
echo "   scripts/lock_ac.sh ile kilitleyin"
echo "5. Runner'ın bu repoya erişimi olduğundan emin olun (org seviyesinde"
echo "   kayıtlıysa otomatik erişir, bkz. HANDOFF.md 3.2)"
