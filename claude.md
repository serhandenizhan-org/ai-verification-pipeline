# claude.md

Bu dosya, bu repoda çalışan tüm Claude ajanları (Orchestrator ve Builder) için
kalıcı bağlam dosyasıdır. Her önemli değişiklikte güncel tutulmalıdır.

## Proje Nedir

Bu repo, AI Verification Pipeline sisteminin kendisidir: Claude'un builder
olarak kod yazdığı, Codex'in reviewer olarak denetlediği, insan (Şef) onayı
olmadan hiçbir şeyin `main`'e gitmediği bir referans mimari + orchestrator
script seti.

Tam spesifikasyon için: `specs/dod.md`, `specs/security-baseline.md` ve
`specs/features/<feature>/acceptance_criteria.yaml` dosyalarına bakın.

## Roller (özet)

| Rol | Ajan | Yapabilir | Yapamaz |
|---|---|---|---|
| Şef | İnsan | Onay, merge, mimari karar | — |
| Orchestrator | Claude Opus 5 High | Spec/AC üretimi, triage, mimari fix | Kod yazamaz, main'e merge edemez |
| Builder | Claude Sonnet 5 High | Kod yazma, commit, feature branch push | Main'e merge edemez, kendi başına fix kararı veremez |
| Reviewer Codex | Codex | Deep review, rapor üretimi | Koda dokunamaz |

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

## Risk / Denetim özet tablosu

| Risk | Zorunlu denetim |
|---|---|
| LOW | CI |
| NORMAL | CI + Reviewer Codex |
| HIGH | CI + Reviewer Codex + Şef onayı |
| CRITICAL | CI + Reviewer Codex + ek güvenlik taraması + Şef onayı |

Risk hesaplanamazsa varsayılan **CRITICAL**'dır (`orchestrator/router.py`).

## Güncel durum

- [ ] İlk feature henüz tanımlanmadı — `specs/features/example-feature/`
      bir şablondur, gerçek feature eklerken kopyalayıp yeniden adlandırın.

## Değişiklik geçmişi

- Bu dosya oluşturuldu (V1 iskeleti).
