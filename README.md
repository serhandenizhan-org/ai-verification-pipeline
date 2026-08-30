# AI Verification Pipeline

Claude (Orchestrator + Builder) ve Codex (Reviewer) ile kurulan, insan
onaylı, denetlenebilir ve fail-closed otonom yazılım geliştirme sistemi.

Tam mimari dokümanı için ekip içi PDF'e bakın. Bu repo, o spesifikasyonun
çalışan iskeletidir.

## Yeni bir projeye bağlama

Bu repo, kendi başına çalışan bir proje değil — **her yeni projeye tek
komutla bağlanan bir şablon/bootstrap** olarak tasarlandı (bkz. HANDOFF.md
madde 1). Yeni bir projede kurmak için, bu repodan:

```bash
bash scripts/install_pipeline.sh /path/to/new-project [owner/repo]
```

`owner/repo` verilirse (ve `gh` o repoya erişebiliyorsa) label'lar ve
branch protection da otomatik kurulur. Script neyi kopyalayıp neyi
kopyalamadığını (özellikle `ci.yml` — bu proje stack'ine özel olduğu için
elle uyarlanır) kendi başında detaylı açıklıyor. Mac mini'de bir kere
kurulması gereken ön koşullar (gitleaks, trufflehog, PostgreSQL, `codex
login`, self-hosted runner) proje başına tekrarlanmaz — bunlar host
seviyesinde, script'in sonunda listeleniyor.

## Bu repoda yerel geliştirme / test için Hızlı Kurulum

```bash
# 1. Ortam değişkenlerini kopyala ve doldur
cp .env.example .env
cp verification/playwright/test.env.example verification/playwright/test.env

# 2. Python bağımlılıklarını kur
pip install -r orchestrator/requirements.txt

# 3. PostgreSQL kur ve ledger veritabanını oluştur (Verification Ledger için)
brew install postgresql@16 && brew services start postgresql@16
createdb verification_pipeline
psql verification_pipeline -c "CREATE ROLE pipeline_app LOGIN;"
psql verification_pipeline -c "GRANT ALL PRIVILEGES ON DATABASE verification_pipeline TO pipeline_app;"
psql verification_pipeline -c "GRANT ALL ON SCHEMA public TO pipeline_app;"
# Şema orchestrator/ledger.py tarafından ilk bağlantıda otomatik oluşturulur
# (bkz. orchestrator/schema.sql için manuel/dokümantasyon amaçlı versiyon)

# 4. Secret tarama aracını kur (gitleaks)
#    bkz. README > Güvenlik Araçları

# 5. AC dosyasını kilitle (Şef onayından sonra)
bash scripts/lock_ac.sh specs/features/<feature-adi>/acceptance_criteria.yaml
```

## Pipeline'ın kendi testleri

`orchestrator/`'daki mantık (risk sınıflandırma, verification-gate kararı,
stale-commit koruması, circuit breaker) gerçek bir Postgres'e karşı test
ediliyor — mock değil, çünkü asıl riskler (concurrency, stale veri)
mock'lanmış bir DB ile yakalanamaz:

```bash
pip install -r orchestrator/requirements.txt -r orchestrator/requirements-dev.txt
python3 -m pytest orchestrator/tests/ -v
```

## Klasör Yapısı

```
.github/workflows/     — CI ve verification pipeline'ları
orchestrator/          — router, circuit breaker, ledger, notifier script'leri
verification/          — Codex severity kuralları, Playwright test ortamı
specs/                 — DoD, güvenlik taban çizgisi, feature bazlı AC dosyaları
scripts/               — AC lock, Stripe test-key guard vb. yardımcı script'ler
.verification/         — circuit breaker state (git'e committed, .env değil)
                          NOT: Verification Ledger artık PostgreSQL'de tutuluyor
                          (bkz. orchestrator/schema.sql, DATABASE_URL), .verification/
                          altındaki eski ledger/ klasörü kullanımdan kalktı.
```

## Güvenlik Araçları

Detaylı kurulum talimatları için sohbet geçmişine veya
`specs/security-baseline.md` dosyasına bakın. Özet:

- **gitleaks** (birincil, erken katman): local pre-commit hook + CI.
  Kurulum: `cp scripts/git-hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit`
- **TruffleHog** (derin katman, CI sonrası): bulunan secret'ların gerçekten
  aktif olduğunu doğrular. Doğrulanırsa Alert + Rotate akışı devreye girer
  ve merge bloklanır. Detay: `verification/trufflehog/README.md`
- **Stripe (test mode)**: ödeme akışlarının ücretsiz test edilmesi
- **Telegram Bot API**: circuit breaker / BLOCKING bulgu / secret sızıntısı bildirimleri

## Branch Protection

`main` branch için GitHub ayarlarını `.github/branch-protection.md`
dosyasındaki adımlara göre manuel olarak yapılandırın — bu ayarlar kod ile
değil, repo Settings üzerinden yapılır.
