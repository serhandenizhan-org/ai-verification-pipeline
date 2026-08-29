# TruffleHog — Secret Discovery + Verification

Bu katman gitleaks'ten SONRA, CI (Fast CI) geçtikten sonra çalışır.
gitleaks'ten farkı: TruffleHog bulduğu secret'ların gerçekten **aktif/geçerli**
olup olmadığını ilgili servisin API'sine sorarak doğrular (`--only-verified`).

## Neden iki katman?

- **gitleaks** (erken, hızlı, local + CI): regex/pattern bazlı, secret
  formatına benzeyen her şeyi yakalar. Hızlı ama yanlış pozitif oranı
  daha yüksek olabilir.
- **TruffleHog** (CI sonrası, derin): yakaladığı her adayı gerçek bir API
  çağrısıyla doğrular. "Verified: true" demesi, o secret'ın gerçekten
  o an aktif ve kullanılabilir olduğu anlamına gelir — yani gerçek bir
  sızıntı, yanlış pozitif değil.

## Akış

```
Fast CI PASS
     │
     ▼
TruffleHog taraması (--only-verified)
     │
 ┌───┴───┐
 │       │
Verified   Verified
bulundu    bulunamadı
 │           │
 ▼           ▼
ALERT      Risk Routing
+ ROTATE   (normal akışa devam)
+ BLOCK
```

## "Verified" çıkarsa ne olur?

1. `orchestrator/alert_and_rotate.py` tetiklenir.
2. Ledger'a `secret_leak_verified` (BLOCKING) event'i yazılır.
3. Şef'e Telegram üzerinden **acil** bildirim gider — bulunan secret'ın
   değeri değil, yalnızca hangi servise ait olduğu ve dosya/satır bilgisi
   paylaşılır (redakte edilmiş).
4. PR'a bir rotasyon kontrol listesi yorumu bırakılır.
5. Merge tamamen bloklanır — bu BLOCKING bulgu, Codex review'a bile
   gerek kalmadan pipeline'ı durdurur (secret sızıntısı her zaman en
   yüksek öncelik).
6. Rotasyon tamamlandığında Şef, aşağıdaki komutla onayı ledger'a işler:
   ```
   python3 orchestrator/verifier.py record-secret-rotated \
     --pr <pr-no> --confirmed-by "Şef"
   ```
   Bu onay olmadan PR yeniden ilerleyemez.

## "Verified" bulunamazsa ne olur?

Normal akışa devam edilir — Risk Routing çalışır, risk seviyesine göre
Codex review tetiklenir.

## Kurulum notu

TruffleHog OSS, GitHub Actions'ta resmi `trufflesecurity/trufflehog`
action'ı ile ek bir hesap/API key gerektirmeden çalışır. Doğrulama
(`--only-verified`) adımı, bulunan secret'ın ait olduğu servise (ör.
Stripe, AWS, GitHub) göre o servisin kendi API'sine bir kontrol isteği
atar — bunun için TruffleHog'un kendisine ayrı bir hesap açmanıza gerek
yoktur.
