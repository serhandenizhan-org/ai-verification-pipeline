# claude.md

Bu dosya, bu repoda çalışan tüm Claude ajanları (Orchestrator ve Builder) için
kalıcı bağlam dosyasıdır. Her önemli değişiklikte güncel tutulmalıdır.

**BU REPO ORCHESTRATOR'IN SABİT ÇALIŞMA ALANIDIR.** Şef, yeni bir proje
fikrini/mimarisini konuşmak istediğinde Claude Code'u HER ZAMAN bu klasörde
açar (`.claude/settings.json` modeli otomatik Opus'a sabitliyor — elle
`/model` yapmaya gerek yok). Burada konuşulan mimari kararlar sonunda
Orchestrator, gerçek projenin kendi `CLAUDE.md`'sini üretip (bkz.
`specs/builder_claude_template.md`) Builder'a ilk prompt'u verir — Builder
o noktadan sonra PROJENİN KENDİ klasöründe, ayrı bir Claude Code sohbetinde
çalışır (bkz. `NEW_PROJECT_SETUP.md`).

## Proje Nedir

Bu repo, AI Verification Pipeline sisteminin kendisidir: Claude'un builder
olarak kod yazdığı, Codex'in reviewer olarak denetlediği, insan (Şef) onayı
olmadan hiçbir şeyin `main`'e gitmediği bir referans mimari + orchestrator
script seti.

Tam spesifikasyon için: `specs/dod.md`, `specs/security-baseline.md` ve
`specs/features/<feature>/acceptance_criteria.yaml` dosyalarına bakın.

## Roller (özet)

| Rol                | Ajan                 | Yapabilir                                                                                                      | Yapamaz                                                                        |
| ------------------ | -------------------- | ---------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Şef               | İnsan               | Onay, merge, mimari karar, secret rotation onayı, maliyet limiti aşımında devam/dur kararı                      | —                                                                                |
| Orchestrator       | Claude Opus 5 High   | Spec/AC üretimi, triage, mimari fix, **adversarial inceleme** ("bu PR'ı nasıl kırarım" — edge case/race condition/eksik test tespiti, Builder'ın sonucuna güvenmeden) | Kod yazamaz, main'e merge edemez                                                   |
| Builder            | Claude Sonnet 5 High | Kod yazma, commit, feature branch push                                                                            | Main'e merge edemez, kendi başına fix kararı veremez                            |
| Reviewer Codex     | Codex                | **Kör (blind)** deep review — Orchestrator'ın adversarial bulgularını görmeden, bağımsız architecture/security/logic/concurrency/database/API/error-handling/performance/test-coverage **ve yeni eklenen bağımlılıkların (tedarik zinciri: yayıncı, bakım durumu, typosquatting riski) incelenmesi**, rapor üretimi | Koda dokunamaz                                                                     |
| Exploratory QA     | (gelecek faz — browser-driven agent) | Scripted E2E'nin yakalayamadığı UX/görsel regresyonları bulmak için değişen ekranı serbestçe gezip test etme | Şu an kurulu değil — Playwright E2E devrede olduğu sürece bu rol boş kalır |

**Bağımsızlık ilkesi:** Hiçbir agent, başka bir agent'ın PASS sonucunu doğru kabul
etmez. PASS = "belirlenen kontroller kapsamında problem bulunamadı" demektir,
kesin doğruluk garantisi değildir. Codex, Orchestrator'ın adversarial bulgularını
görmeden (kör) çalışır ki anchoring bias oluşmasın.

## Builder için kesin kurallar

1. Yalnızca feature branch'lerde çalış (`feature/<isim>`). `main`'e asla
   doğrudan push yapma — GitHub branch protection zaten bunu engeller ama
   bunu varsayma, kuralı bil.
2. Her mantıklı adımda ayrı bir commit at. Bir commit'i sonsuza kadar
   `amend` etme — her iterasyon yeni commit demektir (Circuit Breaker ve
   Ledger audit trail'i buna dayanır).
3. `specs/features/<feature>/acceptance_criteria.yaml` dosyasını lock
   sonrası **asla değiştirme**. Bu dosya sadece Şef onayıyla ve
   `scripts/lock_ac.sh` üzerinden değişebilir.
4. Reviewer Codex bir bulgu raporladığında, kendi başına "haklı/haksız"
   kararı verip fix yapma. Orchestrator'ın triage kararını ve Şef'in
   onayını bekle.
5. `.env`, `*.pem`, `*.key`, secrets içeren hiçbir dosyayı okuma, commit'e
   ekleme veya loglama. Sadece `.env.example` şablonlarını referans al.

## Orchestrator için kesin kurallar

1. Şef ile mimari konuşmayı yürüt, konuşmanın sonunda:
   - `specs/features/<feature>/acceptance_criteria.yaml` taslağını üret
   - Şef onayı sonrası `scripts/lock_ac.sh` ile kilitle
   - Builder'ı tetikle
2. Reviewer Codex raporunu okuduğunda her bulguya `BLOCKING` veya
   `ADVISORY` etiketi ver (bkz. `verification/codex/severity_rules.md`).
3. `BLOCKING` bulgular her zaman Şef onayından geçer. `ADVISORY` bulgular
   Şef'i beklemeden Builder'a not olarak iletilebilir.
4. Mimari nitelikli hataları (yanlış abstraction, yanlış veri modeli,
   yanlış API sözleşmesi) kendin çöz veya spec'i güncelle. Kodsal
   hataları (bug, tip hatası, edge case) Builder'a yönlendir.
5. Circuit breaker tetiklendiğinde (`orchestrator/circuit_breaker.py`),
   döngüyü kendi başına tekrar başlatma — Şef'in kararını bekle.

## Maliyet limiti politikası

Otonom pipeline (self-hosted runner üzerinde her PR'da otomatik Claude/Codex
çağrısı) sabit bir günlük harcama tavanında **otomatik durmaz** — acil/kritik
bir durumda otomasyonun kendi kendine durması istenmiyor. Bunun yerine:

1. Harcama için 2-3 kademeli eşik tanımlanır (örn. günlük kullanım %50 / %80 /
   %100 gibi — kesin sayılar Şef ile birlikte `orchestrator/` içinde
   yapılandırılır).
2. Her eşik aşıldığında Telegram üzerinden Şef'e bildirim gider (bkz.
   `orchestrator/notifier.py`) — pipeline **çalışmaya devam eder**, kendi
   kendine durmaz.
3. Şef, bildirimi aldıktan sonra duruma göre Telegram üzerinden bir komutla
   (`/durdur`, `/devam` gibi — bkz. Telegram bot komutları) pipeline'ı
   durdurabilir veya devam ettirebilir. Karar her zaman Şef'e aittir, sistem
   kendi kararıyla asla tam durmaz.

## Secret leak / rotation politikası

TruffleHog bir secret'ı **aktif (verified)** olarak tespit ettiğinde
(`orchestrator/trufflehog_result.py`, `orchestrator/alert_and_rotate.py`):

- Sistem **hiçbir zaman** otomatik olarak key rotate etmez, servisi durdurmaz
  veya secret'ı kendi başına değiştirmez.
- Tek yapılan şey Telegram üzerinden Şef'e anında bildirim göndermektir.
- Rotation işlemi (BotFather/Stripe/iyzico/R2 vb. üzerinden) her zaman Şef
  tarafından manuel olarak yapılır. Otomatik rotation, yanlışlıkla prod'u
  kırma riski taşıdığı için kesinlikle yasaktır.

## Risk / Denetim özet tablosu

| Risk     | Zorunlu denetim                                            |
| -------- | ---------------------------------------------------------- |
| LOW      | CI                                                         |
| NORMAL   | CI + Reviewer Codex                                        |
| HIGH     | CI + Reviewer Codex + Şef onayı                          |
| CRITICAL | CI + Reviewer Codex + ek güvenlik taraması + Şef onayı |

Risk hesaplanamazsa varsayılan **CRITICAL**'dır (`orchestrator/router.py`).

## Güncel durum

- [ ] İlk feature henüz tanımlanmadı — `specs/features/example-feature/`
  bir şablondur, gerçek feature eklerken kopyalayıp yeniden adlandırın.

## Değişiklik geçmişi

- Bu dosya oluşturuldu (V1 iskeleti).
- V2: Orchestrator'a adversarial inceleme rolü, Codex'e kör (blind) review +
  tedarik zinciri incelemesi eklendi; Exploratory QA rolü gelecek faz olarak
  tanımlandı; maliyet limiti (kademeli bildirim, Şef kararına bağlı durdurma)
  ve secret-leak rotation (her zaman Şef onayı gerekir, hiçbir zaman otomatik
  değil) politikaları eklendi.
