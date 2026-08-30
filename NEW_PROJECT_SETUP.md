# Yeni Proje Kurulum Kılavuzu

Bu dosya, yeni bir projeye AI Verification Pipeline'ı bağlarken **senin elle
yapman gereken** adımların tam listesidir. `scripts/install_pipeline.sh`
dosya kopyalama + GitHub label/branch-protection kısmını otomatikleştiriyor
— geri kalanı (aşağıdaki liste) manuel.

## Ön koşul — Mac mini'de zaten kurulu (proje başına TEKRARLANMAZ)

Bunlar host seviyesinde bir kere kuruldu, her yeni projede tekrar
yapmana gerek yok:

- gitleaks, trufflehog (`brew install gitleaks trufflehog`)
- PostgreSQL 16 (`brew services start postgresql@16`) — Verification Ledger
- Docker Desktop — CI sandbox için
- `codex` CLI, `codex login --device-auth` ile authenticated
- Self-hosted GitHub Actions runner (`mac-mini-runner`), org seviyesinde
  kayıtlı, `~/actions-runner/svc.sh start` ile launchd servisi olarak çalışıyor
- `serhandenizhan-org` GitHub organizasyonu

Bunlardan biri çalışmıyorsa (`brew services list`, `codex login status`,
`gh api orgs/serhandenizhan-org/actions/runners` ile kontrol edilebilir)
önce onu düzelt, sonra devam et.

## Adım adım — HER yeni proje için

### 1. Bootstrap script'i çalıştır

```bash
cd ~/Desktop/Projeler/aiverificationpipeline
bash scripts/install_pipeline.sh /path/to/yeni-proje serhandenizhan-org/yeni-proje-repo-adi
```

`owner/repo` argümanını yalnızca proje **zaten GitHub'a push edilmişse**
verebilirsin (yoksa script bu kısmı atlar, sonra elle çalıştırırsın —
script bunu ekrana yazdırır).

Bu adım şunları yapar (otomatik):
- `orchestrator/`, `scripts/`, `specs/`, `verification/`, `AGENTS.md`,
  `.env.example`, `.github/workflows/verification.yml` kopyalanır
- `.github/workflows/ci.yml` OTOMATİK ÜRETİLİR — `scripts/generate_ci_workflow.py`,
  hedef projenin `package.json`/`requirements.txt`/`pyproject.toml`'una bakıp
  stack'i (Node/Python/monorepo) kendisi tespit eder, `lint`/`typecheck`/`test`/
  `build` script'lerinden GERÇEKTEN var olanları kullanır, Playwright varsa
  E2E job'ı ekler. Elle YAML yazmana gerek yok. Kod ekledikçe/değiştikçe
  tekrar üretmek istersen: `python3 scripts/generate_ci_workflow.py .`
- `CLAUDE.md` (Builder rolü, `specs/builder_claude_template.md`'den) +
  `.claude/settings.json` (`{"model": "sonnet"}`) oluşturulur — bu projede
  Claude Code açtığında **otomatik Builder rolünde ve Sonnet'te** başlar,
  sen "sen builder'sın" demene gerek kalmaz
- `.git/hooks/pre-commit` kurulur (gitleaks)
- `.gitignore`'a pipeline ekleri eklenir
- (owner/repo verildiyse) `needs-codex-review`/`ready-for-human-approval`
  label'ları + solo-friendly branch protection kurulur

### Orchestrator ↔ Builder ayrımı — nasıl çalışıyor

- **Orchestrator**: HER ZAMAN `ai-verification-pipeline` reposunda (bu repo)
  Claude Code açarsın. `.claude/settings.json` orada `{"model": "opus"}` —
  otomatik Opus. Burada mimariyi konuşursun, feature AC'lerini yazarsın.
- **Builder**: HER ZAMAN gerçek projenin kendi klasöründe Claude Code
  açarsın (ayrı bir sohbet/terminal penceresi). O projenin `CLAUDE.md`'si
  otomatik yüklenir, `.claude/settings.json` orada `{"model": "sonnet"}`.
  Burada kod yazdırırsın.
- İkisi TAMAMEN ayrı Claude Code oturumları/pencereleridir — birinden
  diğerine mesaj geçmez, sen (Şef) ikisi arasında köprüsün (Orchestrator'ın
  ürettiği talimatı kopyalayıp Builder'a yapıştırırsın, ya da tam tersi).

### 2. `.env` doldur

```bash
cd /path/to/yeni-proje
cp .env.example .env
```

`.env` içinde:
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — **aynı bot**, Mac mini'de zaten
  var, `aiverificationpipeline/.env`'den kopyalayabilirsin (proje başına
  farklı bot gerekmiyor, aynı bot tüm projelerin bildirimini aynı Telegram
  sohbetine atar)
- `STRIPE_SECRET_KEY` vb. — yalnızca proje ödeme entegrasyonu kullanıyorsa,
  **sk_test_** ile başlayan test key
- `DATABASE_URL` — ledger için, varsayılan zaten Mac mini'deki local Postgres'e
  işaret ediyor, değiştirmene gerek yok

**ÖNEMLİ (Codex review bulgusu — P2): `.env` yalnızca YEREL elle çalıştırma
içindir, CI bunu hiç okumaz.** Telegram bildirimlerinin CI'da (self-hosted
runner'da çalışan `verification.yml`) çalışması için `.env`'e ek olarak
**GitHub Secrets'a da elle eklemen gerekiyor**:

```bash
gh secret set TELEGRAM_BOT_TOKEN --repo owner/yeni-proje-repo-adi
gh secret set TELEGRAM_CHAT_ID --repo owner/yeni-proje-repo-adi
```

Bunu atlarsan CI'da Telegram bildirimleri sessizce (yalnızca stderr
uyarısıyla) atlanır — pipeline'ı bloklamaz ama Şef habersiz kalır.
`.env.example`'daki başlık notu bu üç katmanı (yerel/CI/breaker eşikleri)
ayrıntılı açıklıyor.

### 3. `ci.yml`'i gözden geçir (artık elle yazmıyorsun)

Adım 1'de zaten otomatik üretildi. Yapman gereken:

1. `.github/workflows/ci.yml`'i aç, script'in ne tespit ettiğine (hangi
   klasör, hangi komutlar) bir göz gezdir — çıktısında zaten hangi job'ları
   neden eklediğini yazmıştı
2. Beklediğin bir şey (ör. bir lint komutu) eksikse, muhtemelen
   `package.json`'daki `scripts` adı script'in aradığı isimle (lint,
   typecheck, test, build) eşleşmiyordur — ya `package.json`'ı ya da
   `scripts/generate_ci_workflow.py`'deki eşleşmeyi düzelt, tekrar çalıştır
3. Projende Playwright/E2E test yoksa ve script yanlışlıkla E2E job'ı
   eklediyse (devDependencies'te `@playwright/test` var ama gerçekte
   kullanılmıyorsa), `ci.yml`'den o job'ı elle sil
4. `verification.yml`'deki `required_status_checks` ile GitHub branch
   protection'daki context adının GERÇEK job adıyla eşleştiğinden emin ol
   (`install_pipeline.sh` bunu `"Secret Scan (gitleaks)"` olarak zaten doğru
   kuruyor — bu, saatlerce debug edilen bir hataydı, job'un GitHub Actions'ta
   göründüğü isim neyse `contexts` listesinde TAM O İSİM olmalı)

### 4. Push et, gerçek bir PR ile test et

```bash
git add -A && git commit -m "AI Verification Pipeline kuruldu"
git push -u origin main   # veya feature branch + PR
```

İlk PR'ı açtığında:
- Fast CI otomatik tetiklenmeli (self-hosted runner zaten org'a bağlı)
- Risk LOW değilse Codex review otomatik çalışmalı
- Codex BLOCKING bulgu bulursa Telegram'a mesaj gelmeli

Bunlardan biri olmuyorsa `gh run list --repo owner/repo` ile workflow
loglarına bak.

### 5. İlk gerçek feature'ı tanımla

`specs/features/example-feature/` şablonunu kopyala, gerçek feature adıyla
yeniden adlandır, AC'leri yaz, onayladıktan sonra kilitle:

```bash
cp -r specs/features/example-feature specs/features/<feature-adi>
# acceptance_criteria.yaml'ı düzenle
bash scripts/lock_ac.sh specs/features/<feature-adi>/acceptance_criteria.yaml
```

## Bilinen kısıtlar (henüz çözülmedi)

- **Claude (Builder/Orchestrator) CI'dan otomatik çağrılmıyor** — yalnızca
  Codex review otomatik. Kod yazdırmak için hâlâ elle bir Claude Code
  oturumu açman gerekiyor (bkz. HANDOFF.md madde 4.2.3).
- **`generate_ci_workflow.py`'nin tespiti sınırlı** — yalnızca bilinen
  klasör adlarına (`frontend/`, `backend/`, `client/`, `server/`, `web/`,
  `app/`, `api/`, kök dizin) bakıyor. Farklı bir isim kullanıyorsan
  (`services/api/` gibi) script'teki `NODE_SUBDIRS`/`PYTHON_SUBDIRS`
  listesine eklemen gerekir.

## Çözülmüş kısıtlar (referans için)

- ✅ **Ledger repo izolasyonu**: `ledger_entries` tablosuna `repo` kolonu
  eklendi (zorunlu, fail-closed) — artık iki farklı projenin aynı PR
  numarası ledger'da karışmıyor.
- ✅ **`ci.yml` stack tespiti otomatik**: `scripts/generate_ci_workflow.py`,
  `install_pipeline.sh` tarafından otomatik çağrılıyor, elle YAML yazmaya
  gerek yok.
