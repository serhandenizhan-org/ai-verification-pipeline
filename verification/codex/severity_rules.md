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
- **Tedarik zinciri (supply-chain) — açık kötü niyet belirtisi**: paket adı
  bilinen bir popüler paketin typosquatting'i (ör. `reqeusts`, `lodash-es2`
  gibi), `scripts/check_new_dependencies.py` çıktısında maintainer bilgisi
  hiç olmayan + paket birkaç gün önce yayınlanmış + hiçbir tanıdık
  maintainer/organizasyon yok gibi çoklu şüpheli sinyal bir arada

## ADVISORY

Merge'ü bloklamaz. Orchestrator not düşer, Builder isterse uygular:

- Kod kalitesi (isimlendirme, duplication, karmaşıklık)
- Opsiyonel performans iyileştirmesi
- Dokümantasyon eksikliği (kritik olmayan)
- Stil/konvansiyon uyumsuzluğu
- AC-Gap: Codex'in "bu senaryo AC'lerde eksik" tespiti — **AC dosyasını
  Codex değiştiremez**, yalnızca işaret eder, karar Şef'e sunulur.
- **Tedarik zinciri — düşük güven ama kötü niyet kanıtı yok**: paket
  bakımsız (uzun süredir güncellenmemiş) ama yaygın kullanılıyor, tek
  maintainer'lı küçük ama tanınan bir paket, `lookup_failed: true` (registry'e
  erişilemedi, manuel kontrol önerilir)

## Tedarik Zinciri (Supply-Chain) İncelemesi

Her PR'da bir bağımlılık dosyası (`package.json`, `requirements.txt`,
`pyproject.toml` vb.) değiştiyse, CI `scripts/check_new_dependencies.py`
çalıştırır ve **yalnızca yeni eklenen** paketler için npm/PyPI'dan ham
metadata (ilk yayın tarihi, son güncelleme, maintainer) çeker. Bu script
bir güvenlik kararı VERMEZ — Codex, bu JSON çıktısını okuyup şu soruları
kendi yorumuyla yanıtlar:

- Paket adı, yaygın bir paketin typosquatting'i olabilir mi?
- Paket çok yeni mi (`created`/`first_release` birkaç gün/hafta önce) ve
  maintainer bilgisi boş/şüpheli mi?
- Bilinen CVE taraması (`npm audit`/`pip-audit`/osv-scanner, DoD zorunlu)
  bu script'in kapsamı DIŞINDADIR — o ayrı bir CI adımıdır, burada
  tekrarlanmaz.

`lookup_failed: true` alanı olan her paket en az ADVISORY olarak
işaretlenmelidir (registry'e erişilemedi, otomatik değerlendirme
yapılamadı) — Codex bunu sessizce atlayamaz.

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
