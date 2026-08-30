# HANDOFF — AI Verification Pipeline projesi, tam bağlam

Bu dosya, bu proje hakkında şimdiye kadar konuşulan HER ŞEYİ eksiksiz özetler.
Yeni bir Claude Code oturumu (örn. Mac mini'de) bu dosyayı okuyunca, önceki
konuşmayı sıfırdan tekrar etmeye gerek kalmadan aynı noktadan devam edebilmeli.

Bu dosya `claude.md`'nin YERİNE geçmez — `claude.md` ajanlar için kalıcı,
kısa kural/rol dosyasıdır ve okunmalıdır. Bu dosya ise "nasıl buraya geldik,
ne karar verdik, sırada ne var" anlatısıdır — bir kere okunup sonra
silinebilir/arşivlenebilir.

## 1. Projenin asıl amacı (en son ve en önemli karar)

Bu repo başlangıçta tek bir referans mimari + script seti olarak kuruldu.
AMA gerçek hedef bu değil: **Şef (Serhan), bu pipeline'ı kendi Mac mini'sinde
7/24 çalışan, TÜM GitHub projelerine otomatik bağlanabilen, insan tetiklemesi
olmadan her PR'da kendiliğinden çalışan bir otomasyon/agent sistemine
dönüştürmek istiyor.**

Hedef döngü (Şef'in kendi tarifiyle):
> "PR açıldı → Mac Mini otomatik algıladı → tüm verification pipeline'ı
> çalıştırdı → sonucu Telegram'a gönderdi"

Şef nerede olursa olsun (iş, okul, dışarı) — GitHub'a bir PR açtığı an, bu
sistem kendiliğinden çalışmalı, sonucu Telegram'dan bildirmeli.

## 2. Bugüne kadar ne yapıldı (kronolojik özet)

### 2.1 Temel kurulum
- `gitleaks` ve `trufflehog` kuruldu (Homebrew, `/opt/homebrew/bin`), PATH'e
  kalıcı olarak eklendi (`~/.zprofile`'a `brew shellenv`).
- Bu repo git reposu olarak başlatıldı, pre-commit hook (`scripts/git-hooks/pre-commit`)
  kuruldu — ama hook'un PATH sorunu vardı (login shell olmadığı için Homebrew
  PATH'i görmüyordu), düzeltildi.
- `.env` dosyası dolduruldu: gerçek Telegram bot token + chat ID, gerçek
  Stripe TEST MODE key'leri, Stripe webhook secret (Stripe CLI ile alındı).
- Telegram bot testi başarıyla yapıldı (`orchestrator/notifier.py test`),
  mesaj gerçekten ulaştı.
- ÖNEMLİ OLAY: TruffleHog taraması sırasında gerçek Telegram bot token'ı
  terminal çıktısında düz metin göründü (aktif/verified secret olarak
  tespit edildi — bu pipeline'ın doğru çalıştığının kanıtıydı). Şef,
  token'ı BotFather üzerinden revoke edip yeni token aldı, `.env`
  güncellendi. **Ders: secret'lar loglara/terminale asla düz metin
  basılmamalı, TruffleHog gibi araçlar bunu yakaladığında hemen rotate
  edilmeli.**

### 2.2 İlk gerçek feature — pilot proje olarak kuyumcukent-project kullanıldı
Şef'in gerçek bir projesi var: `github.com/serhandenizhan/kuyumcukent-project`
("Vitrin AI" — kuyumcular için AI destekli ürün fotoğrafı arka plan kaldırma
aracı; Next.js + TypeScript frontend, Python + FastAPI backend, PostgreSQL,
Cloudflare R2, ödeme sağlayıcısı **iyzico** — Stripe DEĞİL).

Bu pipeline'ı gerçekten test etmek için o repoda uçtan uca bir döngü koşuldu:

1. **AC yazıldı ve kilitlendi**: `admin-background-delete` feature'ı
   (`DELETE /api/admin/backgrounds/{id}` endpoint'i, 6 AC). Bu AC dosyası
   SONRADAN bu genel pipeline reposundan temizlendi çünkü proje-özeldi —
   sadece `kuyumcukent-project/specs/features/admin-background-delete/`
   içinde kalmalı, buradaki genel şablon (`specs/features/example-feature/`)
   generic kalmalı.
2. **Builder rolü oynandı**: `kuyumcukent-project`'te `feature/admin-background-delete`
   branch'i açıldı, endpoint + 5 yeni test yazıldı, tüm AC'ler karşılandı,
   16/16 test geçti, gitleaks temiz, PR #10 açıldı.
3. **CI altyapısı o projeye taşındı**: `chore/verification-pipeline-ci`
   branch'inde `.github/workflows/ci.yml` + `verification.yml`,
   `orchestrator/*.py`, `scripts/lock_ac.sh` + `verify_ac_lock.sh`,
   `specs/dod.md`, `specs/security-baseline.md` o repoya kopyalandı ve
   **o projenin gerçek stack'ine göre uyarlandı** (Node-only şablon değil,
   Next.js + FastAPI monorepo'ya özel iki ayrı job: backend/frontend).
   PR #11 açıldı, CI'da bulunan gerçek bug'lar düzeltildi (aşağıda), yeşile
   çekildi, **main'e merge edildi**.
4. **Branch protection GitHub API üzerinden kuruldu ve doğrulandı**
   (`gh api repos/.../branches/main/protection`) — main'e direkt push
   fiilen test edilip reddedildiği görüldü.
5. **PR #10, main ile güncellenip yeniden test edildi** — Fast CI 4/4 yeşil,
   ardından `Verification` workflow'u (risk routing → Codex tetikleme)
   gerçekten çalıştı, PR'a otomatik yorum + `needs-codex-review` etiketi
   düştü (etiketler `gh label create` ile önceden oluşturulmalıydı, bu da
   bulunan bir eksiklikti).

**Bu süreçte bulunup düzeltilen gerçek altyapı bug'ları** (hem bu repoda hem
`kuyumcukent-project`'te uygulandı):
- `scripts/lock_ac.sh`: hash, `status` alanı güncellenmeden ÖNCE
  hesaplanıyordu, bu yüzden `verify_ac_lock.sh` kilitten hemen sonra HER
  ZAMAN hata veriyordu. Hash artık nihai içerik üzerinden hesaplanıyor.
- Pre-commit hook: Homebrew PATH'i login-shell olmayan git hook'larında
  görünmüyordu, `/opt/homebrew/bin` PATH'e elle eklendi.
- `gitleaks/gitleaks-action@v2`: PR taramaları için artık açıkça
  `GITHUB_TOKEN` env'i istiyor (vermezsen sessizce/açıkça fail ediyor).
- Aynı action, repo'nun varsayılan salt-okunur token izinleri yüzünden
  "Resource not accessible by integration" hatası veriyordu — workflow'a
  `permissions: { contents: read, pull-requests: read }` eklenerek çözüldü.
- Backend testleri CI'da `ModuleNotFoundError: No module named 'app'`
  veriyordu çünkü `pytest tests/` (çıplak binary) cwd'yi `sys.path`'e
  eklemiyor; `python -m pytest tests/` kullanılınca (locale ile aynı
  davranış) düzeldi.
- GitHub label'ları (`needs-codex-review`, `ready-for-human-approval`)
  workflow'larda referans veriliyordu ama repoda hiç oluşturulmamıştı.

**Sonuç:** Bu pilot, tüm pipeline'ın (AC-lock, Fast CI, risk routing,
Reviewer Codex tetikleme, Telegram bildirim, branch protection) gerçekten
uçtan uca çalıştığını KANITLADI — ama şu ana kadar HER ADIM Şef tarafından
elle tetiklendi (Claude Code'a "devam et" denerek). Otomatikleştirilmesi
gereken kısım tam olarak bu.

## 3. "Her projede otomatik çalışsın" hedefi için alınan mimari kararlar

Şef'in asıl isteği netleşince (bkz. madde 1), şu kararlar birlikte alındı:

### 3.1 Tetikleme mekanizması: **Self-hosted GitHub Actions runner**
- Mac mini'ye GitHub'ın runner ajanı kurulacak, launchd ile arka planda
  sürekli açık kalacak.
- Runner GitHub'a KENDİSİ bağlanır (outbound) — ev ağında port yönlendirme,
  public IP, ngrok/Cloudflare Tunnel GEREKMİYOR.
- `ci.yml`/`verification.yml` içinde sadece `runs-on: ubuntu-latest` yerine
  `runs-on: self-hosted` yazılacak — geri kalan her şey (PR açılınca otomatik
  tetiklenme, workflow_run zinciri, risk routing) zaten bugün kurduğumuz
  haliyle çalışır, değişmesi gerekmez.
- ALTERNATİF OLARAK ChatGPT, kendi webhook sunucusu + job queue + Postgres
  kurmayı önerdi — bu REDDEDİLDİ çünkü Mac mini'yi internete açmayı (tunnel)
  gerektirir ve GitHub'ın zaten native olarak çözdüğü queue/webhook
  mekanizmasını yeniden yazmak anlamsız. **Karar: self-hosted runner.**

### 3.2 GitHub hesabı: **Organization'a geçiş — ONAYLANDI**
- Kişisel hesap yerine bir GitHub Organization'a geçilecek (repo transfer ile,
  geçmiş korunur, ÜCRETSİZ).
- Sebep: runner'ı org seviyesinde kaydedince, yeni eklenen HER proje runner'a
  otomatik erişir — repo başına ayrı runner kaydına gerek kalmaz.
- Self-hosted runner kullanmak zaten Actions dakika faturalandırmasına hiç
  girmiyor (sadece cloud runner'lar 2000 dk/ay sınırına tabi).

### 3.3 Verification Ledger: **PostgreSQL — ONAYLANDI**
- Şu an `.verification/ledger/` altında düz JSON dosyaları var
  (`orchestrator/ledger.py`).
- Çoklu PR eşzamanlılığında sorgulanabilirlik/güvenilirlik için PostgreSQL'e
  geçilecek. Mac mini zaten sürekli açık olacağı için DB'yi orada barındırmak
  sorun değil.
- **HENÜZ YAPILMADI** — `orchestrator/ledger.py`'nin Postgres'e taşınması
  gerekiyor (şema tasarımı dahil).

### 3.4 Docker sandbox: **Baştan dahil edilecek — ONAYLANDI**
- PR kodu (özellikle testler) izole bir container'da çalışmalı — self-hosted
  runner'da untrusted kod çalıştırmanın güvenlik riskini azaltır.
- **HENÜZ YAPILMADI** — Docker kurulumu + CI job'larının container içinde
  çalışacak şekilde yeniden yazılması gerekiyor.

### 3.5 Rol modeli: **Hibrit — ChatGPT'nin önerisiyle bizimki birleştirildi**
ChatGPT ayrı bir pipeline önerisi getirdi (Claude #1 = analiz, Claude #2 =
adversarial, Codex = bağımsız review, hiçbiri kod yazmıyor — saf doğrulama
pipeline'ı). Şef ile karşılaştırıldı, şu KARAR verildi:

- **Builder (Claude Sonnet) kod yazmaya devam eder** (ChatGPT'nin "kod yazan
  yok" modeli reddedildi — biz otonom feature geliştirme istiyoruz, sadece
  doğrulama değil).
- **Orchestrator (Claude Opus)** artık ek olarak **adversarial inceleme**
  yapar: "bu PR'ı nasıl kırarım" bakış açısıyla edge case/race
  condition/eksik test arar, Builder'ın sonucuna güvenmez. (Ayrı bir "Claude
  #2" agent'ı eklemek yerine bu görev Orchestrator'a verildi — daha basit.)
- **Reviewer Codex artık KÖR (blind) çalışır** — Orchestrator'ın adversarial
  bulgularını görmeden bağımsız review yapar (anchoring bias'ı önlemek için).
- Codex'in inceleme kapsamına **tedarik zinciri/dependency incelemesi**
  eklendi (yeni paket: yayıncı kim, bakım durumu, typosquatting riski) —
  bu daha önce hiçbir agent'ın sorumluluğunda değildi, boşluk olarak
  tespit edildi ve eklendi.
- **Exploratory QA (browser-driven agent)** gelecek faz olarak role
  tablosuna eklendi — scripted Playwright E2E'nin yakalayamadığı UX/görsel
  regresyonları bulmak için. ŞU AN KURULU DEĞİL, sadece planlandı.
- Tüm bunlar `claude.md`'ye işlendi (bkz. "Roller (özet)" tablosu ve
  "Bağımsızlık ilkesi" paragrafı).

### 3.6 Maliyet limiti politikası — ONAYLANDI, henüz kod olarak YAZILMADI
Şef'in özel isteği: sabit bir günlük harcama tavanında sistem **otomatik
durmamalı** (acil/kritik durumda otomasyonun kendi kendine durması
istenmiyor). Bunun yerine:
1. 2-3 kademeli harcama eşiği tanımlanacak (örn. %50/%80/%100 gibi — kesin
   sayılar henüz belirlenmedi).
2. Her eşik aşıldığında Telegram'dan Şef'e bildirim gider, pipeline
   ÇALIŞMAYA DEVAM EDER.
3. Şef, Telegram üzerinden bir komutla (`/durdur`, `/devam` gibi) pipeline'ı
   durdurabilir/devam ettirebilir. Karar HER ZAMAN Şef'e ait.
- **HENÜZ YAPILMADI**: eşik sayıları netleştirilmedi, Telegram bot'un
  komut dinleyen (`getUpdates` polling) bir tarafı yok — şu an
  `notifier.py` sadece TEK YÖNLÜ mesaj gönderiyor, komut alamıyor. Bunun
  kurulması gerekiyor.

### 3.7 Secret leak / rotation politikası — ONAYLANDI, `claude.md`'ye yazıldı
TruffleHog aktif bir secret bulduğunda sistem HİÇBİR ZAMAN otomatik rotate
etmez/durdurmaz — sadece Telegram'dan Şef'e bildirir, rotation her zaman
Şef tarafından manuel yapılır. (Madde 2.1'deki gerçek olaydan sonra netleşti.)

## 4. Henüz YAPILMAYAN, sırada olan işler (Mac mini'de)

Bunlar fiziksel Mac mini erişimi gerektirdiği için henüz uygulanmadı:

1. **Bu oturumun gerçekten Mac mini'de çalıştığını doğrula** (`hostname`,
   `uname -a` ile kontrol edilebilir).
2. GitHub kişisel hesabı → Organization'a geçiş (repo transfer).
3. Self-hosted GitHub Actions runner kurulumu (org seviyesinde kayıt),
   launchd ile her zaman açık servis olarak ayarlanması.
4. Docker kurulumu, CI job'larının container içinde izole çalışacak şekilde
   güncellenmesi.
5. PostgreSQL kurulumu, `orchestrator/ledger.py`'nin JSON'dan Postgres'e
   taşınması (şema tasarımı dahil).
6. Telegram bot'a komut dinleme (`getUpdates` polling) eklenmesi —
   `/durdur`, `/devam` gibi komutlar için.
7. Maliyet eşiklerinin (2-3 kademe) Şef ile birlikte netleştirilip
   `orchestrator/`'a yapılandırma olarak eklenmesi.
8. Claude Code CLI'ın (`claude -p ...` headless) ve Codex CLI'ın Mac
   mini'de kendi hesap/abonelik girişleriyle login edilip, CI job'larından
   otomatik (insan tetiklemesi olmadan) çağrılacak şekilde workflow'lara
   entegre edilmesi — şu an Builder/Orchestrator/Codex hâlâ Şef'in elle
   başlattığı Claude Code sohbetleri üzerinden çalışıyor, bu adım
   otomasyonun asıl can damarı.
9. `install_pipeline.sh` gibi bir bootstrap script yazılması — yeni bir
   projeye bu pipeline'ı tek komutla (workflow dosyaları + AC klasörü +
   pre-commit hook + gerekli label'lar + branch protection) bağlamak için.
10. Bu repodaki (`ai-verification-pipeline`) `ci.yml`/`verification.yml`
    hâlâ eski Node-only şablon — `kuyumcukent-project`'te yaptığımız
    stack-özel uyarlamanın genel bir "şablon" versiyonunun buraya geri
    taşınması (backport) gerekebilir, ya da bu repo tamamen "genel kural +
    script" deposu olarak kalıp CI şablonlarının stack'e göre
    uyarlanacağı açıkça dokümante edilebilir.

## 5. Önemli dosyalar / nereye bakılır

- `claude.md` — ajan rolleri, kesin kurallar, politikalar (BUNU HER
  OTURUM OKUMALI, kalıcı kaynak burasıdır).
- `specs/dod.md` — proje geneli Definition of Done.
- `specs/security-baseline.md` — güvenlik taban çizgisi.
- `specs/features/example-feature/` — AC şablonu (generic, kopyalanıp
  yeniden adlandırılmalı).
- `orchestrator/*.py` — router (risk hesaplama), verifier, ledger,
  circuit_breaker, notifier (Telegram), alert_and_rotate, trufflehog_result.
- `scripts/lock_ac.sh`, `scripts/verify_ac_lock.sh` — AC kilitleme/doğrulama.
- `scripts/git-hooks/pre-commit` — gitleaks pre-commit hook'u.
- `.github/workflows/ci.yml`, `verification.yml` — CI/CD şablonları (bu
  repoda hâlâ Node-only örnek; gerçek stack-özel versiyonu görmek için
  `kuyumcukent-project` reposundaki `main` branch'ine bakılabilir).
- `.github/branch-protection.md` — branch protection manuel/API kurulum
  talimatları (bugün `kuyumcukent-project`'te API ile uygulandı ve
  doğrulandı, bu repoda henüz uygulanmadı çünkü henüz bir GitHub remote'u
  yok).
- `.env.example` — hangi secret'ların gerekli olduğu (gerçek `.env` asla
  git'e girmez, bu handoff zip'inde de yoktu — Mac mini'de elle
  oluşturulmalı).

## 6. Şef'in iletişim/karar tarzı hakkında notlar

- Riskli/geri döndürülemez veya GitHub'da görünür olacak her eylem
  (commit, push, PR açma, merge, branch protection, label oluşturma) için
  ÖNCE onay isteniyor, sonra yapılıyor — bu disiplin korunmalı.
- Şef, mimari kararları kendisi veriyor (Organization geçişi, ledger
  storage, sandbox zamanlaması gibi) — Orchestrator/Claude bunları
  kendi başına seçmemeli, seçenek sunup sormalı.
- Şef, gereksiz açıklama/uzun yazı istemiyor — net, aksiyona dönük,
  Türkçe iletişim tercih ediyor.
