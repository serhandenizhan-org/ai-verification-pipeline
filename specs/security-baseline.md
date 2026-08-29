# Güvenlik ve Gizlilik Taban Çizgisi (Security Baseline)

Her projede istisnasız uygulanır. Builder ve Orchestrator bu kurallara
her zaman uyar; Codex bu kurallara aykırılıkları BLOCKING olarak işaretler.

## Secrets & Credentials

- `.env`, `*.pem`, `*.key`, `secrets.json` — `.gitignore`'da, istisnasız.
- Hiçbir ajan gerçek API key/token/şifre görmez — yalnızca `.env.example`.
- **İki katmanlı secret taraması:**
  1. **gitleaks** — local pre-commit hook + CI'da erken, hızlı, pattern
     bazlı tarama (bkz. `scripts/git-hooks/pre-commit`, `.gitleaks.toml`).
  2. **TruffleHog** — Fast CI'dan sonra, bulunan adayların gerçekten
     aktif olup olmadığını ilgili servisin API'sine sorarak doğrular
     (`--only-verified`). Doğrulanmış bir secret bulunursa Alert +
     Rotate akışı devreye girer ve merge tamamen bloklanır
     (bkz. `verification/trufflehog/README.md`, `orchestrator/alert_and_rotate.py`).
- Sızıntı olursa: secret hemen invalidate edilir, yenisi üretilir —
  "sildim, tamam" yeterli değildir. Rotasyon tamamlanmadan PR ilerleyemez.

## Kimlik Doğrulama & Yetkilendirme

- Şifreler bcrypt/argon2 ile hash'lenir, asla plaintext değil.
- Session/token HttpOnly + Secure cookie'de — localStorage'da değil.
- Her endpoint'te authorization kontrolü yapılır — "giriş yapmış mı"
  yeterli değildir, "bu kaynağa erişebilir mi" sorulur.

## Veri Gizliliği

- PII (isim, email, ödeme bilgisi) log'larda maskelenir
  (`us***@email.com` gibi).
- Kullanıcı silme talebi gerçek hard-delete ile karşılanır, yalnızca
  flag koyup gizlemek yeterli değildir.
- Üçüncü parti servislere (Stripe, analytics vb.) yalnızca gerekli alan
  gönderilir.

## Girdi Doğrulama

- Her kullanıcı girdisi (form, API body, query param) sunucu tarafında
  validate edilir — client-side validation güvenlik sayılmaz.
- SQL injection, XSS, CSRF için framework'ün built-in korumaları
  kullanılır (ORM zorunlu, raw query'den kaçınılır).

## Bağımlılıklar

- `npm audit` / `pip-audit` CI'a entegre; bilinen kritik açık varsa PR
  bloklanır.

## Test Ortamı

- Playwright E2E testleri asla production'a karşı çalışmaz.
- Ödeme testleri yalnızca Stripe **test mode** key'leriyle (`sk_test_...`)
  yürütülür.
- CI'da bir guard-check (`scripts/check_stripe_key_mode.sh`), key
  `sk_live_` ile başlıyorsa pipeline'ı otomatik durdurur.
