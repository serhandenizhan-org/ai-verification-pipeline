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

## 4. Durum (2026-08-30 Mac mini oturumu sonrası)

### 4.1 TAMAMLANDI bu oturumda

1. ✅ Mac mini doğrulandı (`Mac16,10`, hostname `192.168.1.115`).
2. ✅ `serhandenizhan-org` organizasyonu oluşturuldu (kişisel hesap
   dönüştürülmedi — ayrı yeni org, login korunuyor).
3. ✅ Repo `serhandenizhan-org/ai-verification-pipeline`'a taşındı — **public**
   (GitHub Free plan'da private repo'larda org branch protection + self-hosted
   runner'ın public repo erişimi çakışıyordu, ikisi arasında public seçildi,
   gitleaks ile tüm geçmiş temiz olduğu doğrulandıktan sonra).
4. ✅ Self-hosted runner (`mac-mini-runner`) org seviyesinde kayıtlı, launchd
   LaunchAgent olarak çalışıyor (`~/actions-runner`, `./svc.sh start`).
   Runner grubunda `allows_public_repositories: true` (elle GitHub UI'dan
   açıldı, Claude Code klasik API üzerinden değiştiremedi).
5. ✅ Docker Desktop zaten kuruluydu, çalışır durumda. **ÖNEMLİ**: macOS
   self-hosted runner'da GitHub Actions'ın native `container:` job anahtarı
   ÇALIŞMIYOR (yalnızca Linux runner'da destekleniyor) — bunun yerine
   `ci.yml`'de untrusted adımlar `docker run --rm -v $PWD:/workspace ...`
   ile elle sandbox'lanıyor.
6. ✅ PostgreSQL 16 kuruldu (`brew services start postgresql@16`),
   `verification_pipeline` DB + `pipeline_app` rolü. `orchestrator/ledger.py`
   JSON dosyalarından Postgres'e taşındı (bkz. `orchestrator/schema.sql`),
   aynı public API korunarak. Codex review bir concurrency bug'ı buldu
   (advisory unlock commit'ten önce çağrılıyordu) — `pg_advisory_xact_lock`
   ile düzeltildi, 8 eşzamanlı bağlantıyla test edildi.
7. ✅ Codex CLI kuruldu, `codex login --device-auth` ile ChatGPT hesabıyla
   authenticated. `verification.yml`'deki yer tutucu gerçek
   `codex exec review` çağrısıyla değiştirildi. Dogfooding sırasında Codex
   4 gerçek bulgu buldu (fork PR checkout bug'ı, grep double-zero bug'ı, VE
   İKİ CİDDİ GÜVENLİK AÇIĞI: PR-controlled `orchestrator/*.py`/`AGENTS.md`'nin
   PR'ın kendi checkout'undan authenticated çalıştırılması). Hepsi düzeltildi
   — bkz. `scripts/pin_trusted_files.sh` (orchestrator script'leri, AGENTS.md,
   severity_rules.md HER ZAMAN `git show origin/main:...` ile main'den
   sabitlenir, PR ne değiştirirse değiştirsin).
8. ✅ Telegram bildirimleri uçtan uca test edildi (`notifier.py test` +
   gerçek `record-codex` çağrısı ile). Eksik olan tek şey
   `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`'nin GitHub Secrets'a eklenip
   `codex-review` job'una bağlanmasıydı — yapıldı. Ayrıca Mac mini'nin eski
   SSL sertifika paketi (`Install Certificates.command`) güncellendi.
9. ✅ `scripts/install_pipeline.sh` yazıldı ve test edildi — yeni bir projeye
   tek komutla (dosya kopyalama + pre-commit hook + GitHub label/branch
   protection) bu pipeline'ı bağlıyor. `ci.yml` bilinçli olarak
   `ci.yml.example` olarak kopyalanıyor (stack-özel, elle uyarlanmalı).
10. ✅ Branch protection dersi: `required_status_checks.contexts` GERÇEK
    check run adıyla eşleşmeli (`"Secret Scan (gitleaks)"`, workflow/job
    display name'i — `branch-protection.md`'deki `"Fast CI / secret-scan"`
    ÖNERİSİ YANLIŞTI, hiç eşleşmiyordu, saatlerce merge'ü sessizce blokladı).
    `install_pipeline.sh` artık doğru context adını kullanıyor.
11. ✅ Solo geliştirme kararı: branch protection artık `required_approving_review_count: 0`,
    `enforce_admins: false` — GitHub zaten kendi PR'ını onaylamana izin
    vermiyor, bu yüzden solo projelerde review zorunluluğu pratik değil.

### 4.2 TAMAMLANDI — ikinci oturum bölümü (aynı gün, devamı)

1. ✅ **Orchestrator/Builder ayrımı, Şef'in isteğiyle netleştirildi**: Şef
   sabit, ayrı iki Claude Code sohbet penceresi istedi (sürekli "sen
   builder'sın" dememek için). Çözüm: `.claude/settings.json` (`{"model":
   "opus"}`) bu repoya eklendi — bu repo artık Orchestrator'ın SABİT
   çalışma alanı, buraya her Claude Code açılışında otomatik Opus. Yeni
   projeler için `specs/builder_claude_template.md` (Builder-only kurallar,
   Orchestrator içeriği YOK) yazıldı — `install_pipeline.sh` artık bunu
   hedef projenin `CLAUDE.md`'si olarak kopyalıyor + `.claude/settings.json`
   (`{"model": "sonnet"}`) oluşturuyor. Test edildi (dosya içerikleri doğru
   üretiliyor), ama **model pinning'in gerçekten çalıştığı Şef tarafından
   henüz canlı doğrulanmadı** (yeni bir oturum açıp sağ altta Opus/Sonnet
   yazdığını görmesi gerekiyor — bu oturumun kendisi ayarı oluşturmadan
   önce başladığı için hâlâ Sonnet gösteriyordu).
2. ✅ **`NEW_PROJECT_SETUP.md` yazıldı** — `install_pipeline.sh`'in
   otomatikleştirmediği HER ŞEYİN (`.env` doldurma, `ci.yml.example`
   uyarlama, ilk PR testi, ilk feature AC'si, Orchestrator↔Builder akışı)
   adım adım kılavuzu. Bilinen kısıtlar da (paylaşımlı ledger, Claude'un
   CI'dan otomatik çağrılmaması) orada belgelendi.
3. ✅ **Codex mobil/Desktop app takibi çözüldü — GERÇEKTEN test edildi**:
   Şef'in "Codex'i ChatGPT masaüstü/mobil uygulamasından izlemek istiyorum"
   sorusuna cevap. Önce yanlış varsayım: GitHub'da "Installed GitHub Apps"
   altında ayrı bir "repo bağlama/configure" adımı olduğu düşünüldü — ama
   Şef kontrol edince "ChatGPT Codex Connector" yalnızca "Authorized GitHub
   Apps" (OAuth, sadece revoke edilebilir) altında çıktı, "Installed"da HİÇ
   yok. Gerçek mekanizma çok daha basitmiş: **PR'a `@codex review` yorumu
   atmak yeterli** — bu, hesap seviyesinde (repo bazlı bağlama YOK) ChatGPT/
   Codex Desktop + mobil app'in "Pull request'ler" sekmesinde PR'ı otomatik
   gösteriyor (checks, yorumlar, aktivite akışıyla birlikte). Gerçek bir
   test PR'ı (#9) açılıp yorum atılıp Desktop app'te (computer-use ile
   ekran görüntüsü alınarak) görünürlüğü doğrulandıktan sonra PR kapatıldı,
   `verification.yml`'e kalıcı olarak eklendi (`codex-review` job'unda,
   asıl CLI review'dan önce bir adım). Bu, gating kararını DEĞİŞTİRMİYOR
   — yalnızca görünürlük içindir, asıl karar hâlâ CLI review + ledger'da.
4. ✅ `.codex/` (Codex Desktop app'in yerel proje ortam config'i,
   `.codex/environments/environment.toml`) `.gitignore`'a eklendi — Ortamlar
   sayfasında bu repoyu "+" ile eklerken kendiliğinden oluşmuştu, commit'e
   girmemesi gerekiyordu.
5. ⚠️ **ÖNEMLİ BULUNAN AMA HENÜZ ÇÖZÜLMEMİŞ GERÇEK SORUN**: `verification.yml`
   içindeki `risk-routing` job'ı `if: github.event.workflow_run.conclusion
   == 'success'` koşuluyla çalışıyor — yani Fast CI BAŞARISIZ olursa
   (bu repoda HER ZAMAN başarısız oluyor, çünkü `ci.yml` hâlâ Node-only
   şablon ve gerçek bir proje yok) `risk-routing` VE ONA BAĞLI
   `codex-review` job'u HİÇ ÇALIŞMIYOR. Yani şu ana kadarki tüm Codex
   review testleri (dogfooding, `@codex review` mobil takip testi)
   `codex exec review`'in DOĞRUDAN elle (CLI'dan) çalıştırılmasıyla ya da
   `gh pr comment` ile manuel tetiklenerek yapıldı — **gerçek bir
   `workflow_run` tetiklemesiyle uçtan uca hiç test edilmedi**. Gerçek bir
   proje eklenip `ci.yml` uyarlanıp Fast CI gerçekten yeşile çekilmeden bu
   asla doğrulanamaz. Bu, bir sonraki gerçek projede MUTLAKA ilk test
   edilmesi gereken şey.

### 4.3 TAMAMLANDI — üçüncü oturum bölümü (aynı gün, devamı)

Şef, HANDOFF'ta "bilinen kısıt" olarak işaretlenmiş iki maddeyi doğrudan
çözülmesini istedi (madde 4.3'te önceden "henüz çözülmedi" olarak
işaretliydi):

1. ✅ **Ledger'a `repo` kolonu eklendi — çoklu proje izolasyonu**.
   `orchestrator/schema.sql` + `ledger.py` + `verifier.py` +
   `alert_and_rotate.py` + `trufflehog_result.py` hepsi güncellendi.
   `repo` artık zorunlu ("owner/repo" formatında), verilmezse fail-closed
   hata fırlatıyor. CI'da `$GITHUB_REPOSITORY`'den otomatik geliyor (GitHub
   Actions bunu zaten sağlıyor), workflow dosyalarında ekstra değişikliğe
   gerek kalmadı. Test sırasında gerçek bir bug bulundu: index oluşturma
   satırları `repo` kolonuna referans veriyordu ama migration (kolonu
   ekleme) ondan SONRA çalışıyordu — sıra düzeltildi (önce tablo, sonra
   migration, sonra index). İki farklı projede aynı PR numarasıyla (#7)
   test edildi, karışmadı.
2. ✅ **`ci.yml` artık tamamen otomatik üretiliyor**. Şef, önceki
   "ci.yml.example'ı elle uyarla" adımını hiç anlamadığını, bunu tamamen
   otomatikleştirmek istediğini söyledi. `scripts/generate_ci_workflow.py`
   yazıldı: hedef projenin `package.json`/`requirements.txt`/`pyproject.toml`'una
   bakıp Node/Python/monorepo tespiti yapıyor, yalnızca GERÇEKTEN var olan
   `lint`/`typecheck`/`test`/`build` script'lerini kullanıyor (var olmayan
   bir script'i çağırıp CI'ı anlamsız kırmıyor), Playwright varsa E2E job'ı
   ekliyor. `install_pipeline.sh` artık `ci.yml.example` kopyalamıyor,
   doğrudan bunu çağırıp gerçek `ci.yml`'i üretiyor. 4 senaryoda test
   edildi (monorepo, Node-only, Python-only, boş proje) — hepsi geçerli
   YAML ve doğru tespit üretti. `NEW_PROJECT_SETUP.md`'deki "madde 3"
   tamamen yeniden yazıldı (artık "elle uyarla" değil "üretileni gözden
   geçir").

### 4.4 TAMAMLANDI — Codex'in dış review'ı sonrası kritik düzeltmeler

Şef, bu pipeline'ı Codex'e (ayrı bir ChatGPT sohbetinde) derin incelettirdi.
Codex 10 P1 (BLOCKING) + 4 P2 (ADVISORY) bulgu buldu — genel tespiti:
**"denetleyen bileşenler var ama sonuçları bağlayıcı bir merge kararına
dönüştüren mekanizma yok."** Şef, en kritik 3 maddeyi seçip düzeltilmesini
istedi (kalan 7 P1 + 4 P2 bulgu HENÜZ YAPILMADI, aşağıda madde 4.4'te).

1. ✅ **Tek bağlayıcı `verification-gate`**. Doğrulandı: `cmd_record_codex`
   BLOCKING bulgu olsa bile her zaman `0` dönüyordu VE branch protection
   yalnızca `Secret Scan (gitleaks)`'ı zorunlu tutuyordu — yani Codex
   "BLOCKING" dese bile merge butonu aktif kalıyordu. `verifier.py gate`
   komutu eklendi: `ledger.summarize_for_gate()` + circuit breaker
   durumuna bakıp TEK bir PASS/FAIL kararı üretiyor, `verification.yml`'in
   yeni `verification-gate` job'ı bunu PR'ın GERÇEK head_sha'sına (workflow_run
   olayının varsayılan SHA'sı base branch'e ait olduğu için `github.event.workflow_run.head_sha`
   açıkça kullanıldı — bu da bir Codex bulgusuydu) bir commit status olarak
   yazıyor. `install_pipeline.sh` artık branch protection'da hem
   `Secret Scan (gitleaks)` hem `verification-gate`'i zorunlu tutuyor.
   6 senaryo test edildi (LOW/HIGH risk, blocking var/yok, breaker tripped,
   secret leak blocking, VE en kritik olanı: **eski bir commit'in PASS
   sonucu yeni commit'in gate kararını etkilemiyor**).
   Ayrıca gerçek bir `bash -e` bug'ı bulunup düzeltildi: `X=$(grep -c ...)`
   grep eşleşme bulamayınca (exit 1) GitHub Actions'ın varsayılan shell'i
   altında satırı anında öldürüyordu, `${X:-0}` fallback'ine hiç
   ulaşılmıyordu — `bash -e` ile yerel olarak test edilip doğrulandı.
2. ✅ **Gerçek izolasyon** — `pin_trusted_files.sh`'in eski yaklaşımı
   (orchestrator/*.py'yi PR checkout'u İÇİNDE ezmek) yetersizdi: Python,
   çalıştırılan script'in kendi dizinini sys.path'in başına koyduğundan,
   PR yeni bir sibling modül (ör. `orchestrator/argparse.py`) ekleyip
   ezilmiş dosyaların import'larını gölgeleyebilirdi. Bu GERÇEK bir
   saldırıyla yerel olarak simüle edildi ve doğrulandı: aynı dizinden
   çalıştırıldığında zararlı kod çalıştı, izole `$RUNNER_TEMP` dizininden
   çalıştırıldığında (PR'ın kendi checkout'unda aynı zararlı dosya dursa
   bile) hiç etkilenmedi. `scripts/stage_trusted_orchestrator.sh` artık
   güvenilir kodu PR ağacının tamamen dışına kopyalıyor, Python HER ZAMAN
   oradan çalıştırılıyor. `pin_trusted_files.sh` yalnızca AGENTS.md/
   severity_rules.md'ye daraltıldı (Codex'in okuduğu, çalıştırmadığı
   dosyalar — prompt injection riski farklı, in-place ezme yeterli).
3. ✅ **Ledger commit kimliği + Postgres circuit breaker**. `ledger_entries`'e
   `head_sha` + `run_id` eklendi. `summarize_for_gate(repo, pr, head_sha)`
   yalnızca belirli bir commit'e ait olayları döndürüyor — eski (geç
   biten) bir çalışmanın PASS sonucu artık yeni bir commit için
   kullanılamıyor (test edildi: eski commit codex=PASS, yeni commit'in
   gate-summary'si codex=null döndü). `circuit_breaker.py` JSON dosyasından
   (PR checkout dizininde duruyordu, checkout temizliğinde silinebilirdi,
   kilitsiz yazım) Postgres'e taşındı, `SELECT ... FOR UPDATE` ile atomik
   güncelleme — 20 eşzamanlı `record_attempt()` çağrısıyla test edildi,
   sıfır kayıp güncelleme.

**NOT**: Bu repo (`ai-verification-pipeline`) kendisi gerçek bir proje
olmadığı için (Fast CI hep fail veriyor, gerçek kod yok) kendi branch
protection'ına `verification-gate`'i zorunlu YAPMADIK — bu yalnızca
`install_pipeline.sh` ile kurulan GERÇEK hedef projelere uygulanıyor.

### 4.5 HENÜZ YAPILMADI

1. Telegram bot'a komut dinleme (`getUpdates` polling) eklenmesi —
   `/durdur`, `/devam` gibi komutlar için. **Şef bu turda bunu ERTELEDİ**
   ("zor diyorsan yapmayalım") — cost/usage guard'ın interaktif STOP/CONTINUE
   kısmı da bu yüzden yapılmadı, yalnızca dependency/supply-chain güvenliği
   (madde 1) uygulandı.
2. Maliyet eşiklerinin (2-3 kademe) netleştirilmesi — yukarıdaki madde 1 ile
   birlikte ertelendi.
3. Claude Code CLI'ın headless (`claude -p ...`) CI job'larından otomatik
   çağrılması — Codex CLI tarafı yapıldı (madde 4.1.7), Claude/Builder tarafı
   HÂLÂ Şef'in elle başlattığı sohbetler üzerinden çalışıyor. Bu, tam otonom
   "PR açıldı → Mac mini otomatik algıladı → hiç insan müdahalesi olmadan"
   döngüsünün eksik kalan son parçası.
4. ~~`ci.yml` hâlâ Node-only şablon~~ — ÇÖZÜLDÜ, bkz. madde 4.3
   (`scripts/generate_ci_workflow.py`).
5. Circuit breaker, CI (Fast CI) taraflı hatalar için HİÇ tetiklenmiyor —
   yalnızca `record-codex`/`record-ci` CLI komutları çağrıldığında devreye
   giriyor, ama `ci.yml` şu an `verifier.py record-ci`'yi hiç çağırmıyor.
   Yalnızca Codex tarafı (risk-routing → codex-review) tam bağlı.
   (Not: bu artık `verification-gate`'in "risk hesaplanmamışsa FAIL"
   mantığıyla DOLAYLI olarak kapanıyor — Fast CI fail olursa risk hiç
   hesaplanmaz, gate zaten FAIL verir. Ama circuit breaker'ın kendisi
   CI-taraflı tekrarlı hataları hâlâ saymıyor, yalnızca Codex-taraflı.)

### 4.6 TAMAMLANDI — Codex'in dış review'ından KALAN 7 P1 + 4 P2

Şef "kalan bulguları da sırayla düzeltelim" dedi — hepsi bu oturumda
gerçek testlerle (çoğu gerçek saldırı/bypass simülasyonuyla) tamamlandı.

**P1'ler (hepsi BLOCKING, hepsi düzeltildi):**
1. ✅ **AC kilidi bypass'ı** — `orchestrator/ac_lock.py` yazıldı: kilit
   hash'i artık dosyanın İÇİNDE değil Postgres'te (bağımsız, yalnızca
   `lock_ac.sh`'in yazabildiği bir kayıt). 3 gerçek bypass senaryosu
   (hash+içerik birlikte değiştirme, `status`'u `draft`'a çevirme, dosyayı
   silme) test edildi, üçü de engellendi.
2. ✅ **Router risk sınıflandırması** — allowlist mantığına çevrildi:
   yalnızca açıkça izin verilen dosyalar (docs, LICENSE) LOW alıyor, geri
   kalan HER ŞEY en az NORMAL. Pipeline'ın kendi kontrol yüzeyine
   (`.github/workflows/`, `orchestrator/`, `scripts/`) özel HIGH/CRITICAL
   kuralları eklendi. Bağımlılık dosyası tespiti artık alt dizinleri de
   yakalıyor (`os.path.basename`).
3. ✅ **TruffleHog wiring** — gerçekten `ci.yml`'e eklendi, sonuç
   `trufflehog_result.py` ile işleniyor (ERROR/OK ayrımı net). `verifier.py
   gate`, bu event'in `OK` olmasını ZORUNLU KILIYOR — TruffleHog
   çalışmazsa/hata verirse gate FAIL verir, "sessizce atlama" artık
   yapısal olarak imkansız.
4. ✅ **Stripe key guard** — allowlist'e çevrildi (`sk_test_` DIŞINDAKİ
   her şey reddediliyor), ve E2E job şablonu artık guard'ı HOST'ta,
   secret container'a hiç verilmeden önce çalıştırıyor.
5. ✅ **Dependency detection** — regex tabanlı diff-satırı parse'ı yerine
   gerçek manifest parse'ı (`json`, `tomllib`) geldi — PEP 621, npm script
   anahtarı karışıklığı, ve git hatasının "temiz" sayılması hepsi düzeldi.
6. ✅ **install_pipeline.sh yedekleme** — var olan her dosya ezilmeden
   önce `.pipeline-install-backup-<zaman>/` altına yedekleniyor, script
   sonunda özetleniyor. Gerçek özelleştirilmiş içerikle test edildi.
7. ✅ Ledger repo/commit ayrımı zaten madde 4.2/4.4'te çözülmüştü.

**P2'ler (hepsi ADVISORY, hepsi düzeltildi):**
- ✅ `.env.example`/`NEW_PROJECT_SETUP.md`: yerel/.env vs CI/GitHub
  Secrets vs MAX_ITERATIONS'ın CI'ı hiç etkilememesi artık açıkça
  belgelendi (üç ayrı katman, üç ayrı mekanizma).
- ✅ **Pipeline'ın kendi test takımı** — `orchestrator/tests/` eklendi,
  bu oturumda elle doğrulanan senaryolar (stale-commit koruması, breaker
  tripping, risk sınıflandırma) artık 16 gerçek pytest testi (gerçek
  Postgres'e karşı, mock değil) — hepsi geçiyor.
- ✅ Telegram: dinamik metin artık Markdown-kaçışlı, 3 denemeli retry
  eklendi (gerçek testle doğrulandı, ~6sn backoff). PR etiketleri
  (`needs-codex-review`/`ready-for-human-approval`) artık gate'in GERÇEK
  kararını yansıtıyor, önceden sadece LOW-risk yolunda ekleniyordu.
- ✅ Kurulum hataları artık `|| true` ile yutulmuyor — gerçek bir
  auth/API hatası "KISMEN BAŞARISIZ" olarak açıkça raporlanıyor.
  `branch-protection.md` solo-geliştirme kararıyla artık ÇELİŞMİYOR
  (eskiden "1 onay zorunlu" yazıyordu, bu solo projede PR'ları kalıcı
  kilitlerdi).

**Şef "yeni özellikleri de değerlendirelim" dedi, sonra "1'den 7'ye hepsini
yapalım" dedi** — aşağıda bu özelliklerin durumu (bkz. 4.7).

**DİKKAT — bu oturumda tekrarlanan bir ders**: `install_pipeline.sh`'i
gerçek `serhandenizhan-org/ai-verification-pipeline` reposuna karşı test
ederken (owner/repo argümanıyla), bu reponun KENDİ branch protection'ını
da gerçekten değiştirdi (`verification-gate`'i zorunlu status check
yaptı) — bu repo gerçek bir proje olmadığı için `verification-gate` asla
postlanmaz, PR'lar kalıcı "pending" kalırdı. Fark edilip hemen geri
alındı. **install_pipeline.sh'in owner/repo argümanını test ederken
GERÇEK org repo'suna karşı değil, ayrı bir scratch/test repo'suna karşı
çalıştırılmalı.**

### 4.7 TAMAMLANDI — Codex'in önerdiği 8 yeni özellikten 1-2-3-4-5 (Şef: "1'den 7'ye hepsini yapalım")

1. ✅ **Tek güncellenen PR yorumu**: `verifier.py`'ye `cmd_render_comment` +
   paylaşılan `_evaluate_gate` helper'ı eklendi. `codex-review` job'u artık
   kendi PR yorumunu atmıyor; tüm rapor metni + tedarik zinciri raporu
   `record-codex --report-file/--deps-report-file` ile ledger'a yazılıyor,
   `verification-gate` job'u BUNLARI okuyup TEK bir Markdown yorumu
   oluşturuyor/günceliyor (`<!-- ai-verification-pipeline:status -->`
   marker'ıyla bulunuyor, `gh api ... --jq` + PATCH-veya-create). PR #29.
2. ✅ **AC-test izlenebilirliği**: `scripts/check_ac_traceability.py` — her
   feature'ın AC ID'lerini kilitli `acceptance_criteria.yaml`'dan, kanıtı
   ise AYRI (kilitlenmeyen) `specs/features/<feature>/evidence.yaml`'dan
   okuyup eksik kanıtları raporlar. **ADVISORY'dir, gate'i bloklamaz** —
   `ac-lock-check` job'una eklendi. PR #30.
3. ✅ **Sürüm takibi + kurulum doğrulayıcısı**: `PIPELINE_VERSION` +
   `.pipeline-meta.json` (version/source_commit/installed_at) her hedef
   projeye yazılıyor; `scripts/check_pipeline_version.sh` sürüm sapmasını
   tespit ediyor (otomatik upgrade YAPMIYOR — `install_pipeline.sh`'i
   tekrar çalıştırmak, zaten yedekleme-güvenli olduğu için upgrade
   yoludur). PR #28.
4. ✅ **Kurulum sağlık kontrolü**: `scripts/doctor.py` — host araçları
   (gitleaks/trufflehog/docker/codex/gh), Docker daemon, Postgres
   bağlantısı, proje-yerel dosyalar, ve (`--repo` ile) GitHub tarafı
   (runner online sayısı, GitHub Secrets varlığı, branch protection'ın
   GERÇEKTEN `verification-gate`'i zorunlu kılıp kılmadığı). Gerçek org
   repo'suna karşı test edildi. PR #28.
5. ✅ **Bulgulara kalıcı kimlik + triage geçmişi**:
   `orchestrator/finding_triage.py` — her Codex bulgusuna
   `severity+title+file:line`'dan türetilen stabil bir sha256 fingerprint,
   Postgres'te (`finding_history` tablosu) ilk/son görülme + tekrar sayısı
   izleniyor. Bir P1, `finding_triage.py accept <repo> <fingerprint>
   <accepted_by> <reason>` ile (yalnızca bir insan ismiyle, boş
   `accepted_by` reddediliyor) 'accepted' işaretlenirse, gate artık O
   SPESİFİK bulguyu bloklamıyor — kabul edilmemiş diğer BLOCKING bulgular
   bloklamaya devam ediyor (`unaccepted_blocking_count`, eski ledger
   kayıtlarında bu alan yoksa fail-closed olarak ham `blocking` sayısına
   geri dönüyor). 6 yeni pytest testi (gerçek Postgres'e karşı). PR #30.

**Hâlâ yapılmadı (Şef'in listesinde 6 ve 7)**:
- Feature 6 — Maliyet/kullanım görünürlüğü (kademeli Telegram eşikleri).
- Feature 7 — Yetkili durdur/devam + süreli istisna (Telegram komut
  dinleme). Bunlar önceden ERTELENMİŞTİ ("zor diyorsan yapmayalım"), Şef
  bu turda "1'den 7'ye hepsini yapalım" diyerek yeniden onayladı — sıradaki
  iş bu ikisi.

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
