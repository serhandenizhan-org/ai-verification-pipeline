# AI Verification Pipeline

Claude (Orchestrator + Builder) ve Codex (Reviewer) ile kurulan, insan
onaylı, denetlenebilir ve fail-closed otonom yazılım geliştirme sistemi.

Tam mimari dokümanı için ekip içi PDF'e bakın. Bu repo, o spesifikasyonun
çalışan iskeletidir.

## Hızlı Kurulum

```bash
# 1. Ortam değişkenlerini kopyala ve doldur
cp .env.example .env
cp verification/playwright/test.env.example verification/playwright/test.env

# 2. Python bağımlılıklarını kur
pip install -r orchestrator/requirements.txt

# 3. Secret tarama aracını kur (gitleaks)
#    bkz. README > Güvenlik Araçları

# 4. AC dosyasını kilitle (Şef onayından sonra)
bash scripts/lock_ac.sh specs/features/<feature-adi>/acceptance_criteria.yaml
```

## Klasör Yapısı

```
.github/workflows/     — CI ve verification pipeline'ları
orchestrator/          — router, circuit breaker, ledger, notifier script'leri
verification/          — Codex severity kuralları, Playwright test ortamı
specs/                 — DoD, güvenlik taban çizgisi, feature bazlı AC dosyaları
scripts/               — AC lock, Stripe test-key guard vb. yardımcı script'ler
.verification/         — ledger ve circuit breaker state (git'e committed, .env değil)
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
