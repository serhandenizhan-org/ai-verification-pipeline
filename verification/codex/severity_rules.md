# Codex Bulgu Şiddeti — BLOCKING vs ADVISORY

Reviewer Codex her bulgusunu bu iki kategoriden birine koyar. Orchestrator,
Şef'e sunmadan önce bu etiketlemeyi doğrular/düzeltir.

## BLOCKING

Şef onayı olmadan merge ilerleyemez. Aşağıdaki kategorilerden biri
BLOCKING'dir:

- **Doğrulanmış (aktif) secret sızıntısı** — TruffleHog `Verified: true`
  raporladığında otomatik olarak BLOCKING'dir, Codex'in ayrıca
  değerlendirmesine gerek yoktur (bkz. `orchestrator/alert_and_rotate.py`).
- Güvenlik açığı (authentication/authorization bypass, injection, secret
  sızıntısı)
- Veri kaybı riski (yanlış silme, geri alınamaz durum değişikliği)
- Mantık hatası (yanlış hesaplama, yanlış state transition)
- Race condition / concurrency hatası
- Idempotency ihlali (webhook, ödeme gibi tekrar-hassas akışlarda)
- Kritik path'te (auth/, payment/) test kapsamı eksikliği

## ADVISORY

Merge'ü bloklamaz. Orchestrator not düşer, Builder isterse uygular:

- Kod kalitesi (isimlendirme, duplication, karmaşıklık)
- Opsiyonel performans iyileştirmesi
- Dokümantasyon eksikliği (kritik olmayan)
- Stil/konvansiyon uyumsuzluğu
- AC-Gap: Codex'in "bu senaryo AC'lerde eksik" tespiti — **AC dosyasını
  Codex değiştiremez**, yalnızca işaret eder, karar Şef'e sunulur.

## Format

Codex raporu şu formatta üretilmelidir (Orchestrator'ın otomatik
parse edebilmesi için):

```
[BLOCKING] <dosya>:<satır>
  <açıklama>
  Kanıt: <nasıl doğrulandığı>

[ADVISORY] <dosya>:<satır>
  <açıklama>

[ADVISORY] AC-Gap
  <hangi senaryo eksik>
```

## Belirsiz durumlar

Bir bulgunun BLOCKING mi ADVISORY mi olduğu net değilse, **BLOCKING**
olarak işaretlenir (fail-closed prensibiyle tutarlı — belirsizlikte
sistem daha temkinli tarafa düşer).
