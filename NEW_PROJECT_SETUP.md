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
- `.github/workflows/ci.yml.example` kopyalanır (DİKKAT: `.example` uzantılı,
  aktif değil — bkz. madde 3)
- `.git/hooks/pre-commit` kurulur (gitleaks)
- `.gitignore`'a pipeline ekleri eklenir
- (owner/repo verildiyse) `needs-codex-review`/`ready-for-human-approval`
  label'ları + solo-friendly branch protection kurulur

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
  işaret ediyor, değiştirmene gerek yok (tüm projeler AYNI ledger DB'sini
  paylaşıyor, `pr` alanı repo bazlı ayrım yapmıyor — bkz. "Bilinen kısıt" altı)

### 3. `ci.yml.example`'ı proje stack'ine göre uyarla

Bu adım **tamamen elle** — script bunu otomatik yapamıyor çünkü her proje
farklı bir stack kullanıyor (Node, Python, monorepo, vb.). Yapman gerekenler:

1. `.github/workflows/ci.yml.example` dosyasını oku
2. Projenin gerçek build/test/lint komutlarına göre `secret-scan` job'ı
   HARİÇ her şeyi yeniden yaz (secret-scan zaten stack-agnostic, olduğu gibi
   bırak)
3. `docker run` ile sandbox mantığını koru (macOS runner'da native
   `container:` çalışmıyor — bkz. `aiverificationpipeline` HANDOFF.md)
4. Dosyayı `ci.yml` olarak kaydet (`.example` uzantısını at)
5. `verification.yml`'deki `required_status_checks` ile GitHub branch
   protection'daki context adının GERÇEK job adıyla eşleştiğinden emin ol
   (bu, saatlerce debug edilen bir hataydı — job'un GitHub Actions'ta
   göründüğü isim neyse `contexts` listesinde TAM O İSİM olmalı, workflow
   adı + job id kombinasyonu DEĞİL)

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

- **Ledger tüm projeler arasında paylaşılıyor** — `verification_pipeline`
  Postgres DB'si tek, `pr` alanı yalnızca PR numarasıdır, repo adı içermez.
  İki farklı projede aynı PR numarası varsa (olası, her repo kendi
  numaralandırmasını yapıyor) ledger karışabilir. Şu an tek proje aktif
  olduğu için sorun değil — birden fazla proje eş zamanlı gerçek kullanıma
  geçtiğinde `ledger_entries` tablosuna bir `repo` kolonu eklenmesi gerekecek.
- **Claude (Builder/Orchestrator) CI'dan otomatik çağrılmıyor** — yalnızca
  Codex review otomatik. Kod yazdırmak için hâlâ elle bir Claude Code
  oturumu açman gerekiyor (bkz. HANDOFF.md madde 4.2.3).
- **`ci.yml` stack tespiti otomatik değil** — madde 3'teki uyarlama her
  proje için tekrar elle yapılmalı.
