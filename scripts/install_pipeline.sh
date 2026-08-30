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

echo "== AI Verification Pipeline kuruluyor =="
echo "Kaynak: $SOURCE_REPO_ROOT"
echo "Hedef:  $TARGET_DIR"
echo ""

copy_dir() {
  local rel="$1"
  mkdir -p "$TARGET_DIR/$(dirname "$rel")"
  cp -R "$SOURCE_REPO_ROOT/$rel" "$TARGET_DIR/$rel"
  echo "kopyalandı: $rel"
}

# --- orchestrator/ (stack-agnostic, olduğu gibi kopyalanır) ---
mkdir -p "$TARGET_DIR/orchestrator"
for f in router.py verifier.py ledger.py circuit_breaker.py notifier.py \
         alert_and_rotate.py trufflehog_result.py requirements.txt schema.sql; do
  cp "$SOURCE_REPO_ROOT/orchestrator/$f" "$TARGET_DIR/orchestrator/$f"
done
echo "kopyalandı: orchestrator/"

# --- scripts/ ---
mkdir -p "$TARGET_DIR/scripts/git-hooks"
for f in lock_ac.sh verify_ac_lock.sh check_stripe_key_mode.sh \
         check_new_dependencies.py pin_trusted_files.sh generate_ci_workflow.py; do
  cp "$SOURCE_REPO_ROOT/scripts/$f" "$TARGET_DIR/scripts/$f"
done
cp "$SOURCE_REPO_ROOT/scripts/git-hooks/pre-commit" "$TARGET_DIR/scripts/git-hooks/pre-commit"
chmod +x "$TARGET_DIR"/scripts/*.sh "$TARGET_DIR/scripts/git-hooks/pre-commit"
echo "kopyalandı: scripts/"

# --- specs/ (DoD + security baseline sabit, AC şablonu generic) ---
mkdir -p "$TARGET_DIR/specs/features/example-feature"
cp "$SOURCE_REPO_ROOT/specs/dod.md" "$TARGET_DIR/specs/dod.md"
cp "$SOURCE_REPO_ROOT/specs/security-baseline.md" "$TARGET_DIR/specs/security-baseline.md"
cp "$SOURCE_REPO_ROOT/specs/features/example-feature/acceptance_criteria.yaml" \
   "$TARGET_DIR/specs/features/example-feature/acceptance_criteria.yaml"
echo "kopyalandı: specs/"

# --- CLAUDE.md (Builder rolü, sabit) + model pinning ---
# Orchestrator (ai-verification-pipeline reposu) her zaman Opus'a sabit;
# Builder (bu hedef proje) her zaman Sonnet'e sabit. İkisi de ayrı Claude
# Code sohbeti/oturumu olarak açılır — Şef "sen builder'sın" demek zorunda
# kalmaz, .claude/settings.json + CLAUDE.md otomatik yüklenir.
cp "$SOURCE_REPO_ROOT/specs/builder_claude_template.md" "$TARGET_DIR/CLAUDE.md"
mkdir -p "$TARGET_DIR/.claude"
cat > "$TARGET_DIR/.claude/settings.json" <<'SETTINGS_EOF'
{
  "model": "sonnet"
}
SETTINGS_EOF
echo "kopyalandı: CLAUDE.md (Builder rolü) + .claude/settings.json (model: sonnet)"

# --- verification/ (Codex kuralları + trufflehog dokümantasyonu) ---
mkdir -p "$TARGET_DIR/verification/codex" "$TARGET_DIR/verification/trufflehog"
cp "$SOURCE_REPO_ROOT/verification/codex/severity_rules.md" \
   "$TARGET_DIR/verification/codex/severity_rules.md"
cp "$SOURCE_REPO_ROOT/verification/trufflehog/README.md" \
   "$TARGET_DIR/verification/trufflehog/README.md"
echo "kopyalandı: verification/"

# --- AGENTS.md (Codex CLI'ın otomatik okuduğu reviewer talimatları) ---
cp "$SOURCE_REPO_ROOT/AGENTS.md" "$TARGET_DIR/AGENTS.md"
echo "kopyalandı: AGENTS.md"

# --- .github/workflows/ ---
mkdir -p "$TARGET_DIR/.github/workflows"
cp "$SOURCE_REPO_ROOT/.github/workflows/verification.yml" \
   "$TARGET_DIR/.github/workflows/verification.yml"
cp "$SOURCE_REPO_ROOT/.github/branch-protection.md" \
   "$TARGET_DIR/.github/branch-protection.md"
echo "kopyalandı: .github/workflows/verification.yml (olduğu gibi)"

# ci.yml artık ELLE YAZILMIYOR — proje stack'i otomatik tespit edilip
# üretiliyor (bkz. scripts/generate_ci_workflow.py). Node/Python/monorepo
# fark etmeksizin package.json/requirements.txt/pyproject.toml'a bakarak
# doğru job'ları oluşturur. Kod eklendikçe/değiştikçe tekrar çalıştırılabilir.
echo "ci.yml otomatik üretiliyor (proje stack'i tespit ediliyor)..."
python3 "$TARGET_DIR/scripts/generate_ci_workflow.py" "$TARGET_DIR"

# --- .env.example ---
cp "$SOURCE_REPO_ROOT/.env.example" "$TARGET_DIR/.env.example"
echo "kopyalandı: .env.example"

# --- .verification/ (ledger artık Postgres'te ama circuit breaker state hâlâ dosya) ---
mkdir -p "$TARGET_DIR/.verification/state"
touch "$TARGET_DIR/.verification/state/.gitkeep"
echo "oluşturuldu: .verification/state/"

# --- .gitignore ekleri ---
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
  cp "$TARGET_DIR/scripts/git-hooks/pre-commit" "$TARGET_DIR/.git/hooks/pre-commit"
  chmod +x "$TARGET_DIR/.git/hooks/pre-commit"
  echo "kuruldu: .git/hooks/pre-commit"
else
  echo "UYARI: $TARGET_DIR bir git reposu değil, pre-commit hook kurulamadı." >&2
fi

echo ""
echo "== Dosya kopyalama tamamlandı =="
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

    # NOT: required_status_checks context'i "Secret Scan (gitleaks)" —
    # generate_ci_workflow.py'nin ürettiği secret-scan job'ının adıyla
    # eşleşiyor (bu job stack tespitinden bağımsız, her zaman aynı isimle
    # üretilir). Context adı gerçek job adıyla BİREBİR eşleşmezse branch
    # protection asla "yeşil" görmez (bu repoda saatlerce süren gerçek bir
    # hataydı, bkz. HANDOFF.md).
    gh api "repos/$GITHUB_REPO/branches/main/protection" --method PUT --input - <<'EOF' 2>&1 || true
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Secret Scan (gitleaks)"]
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
