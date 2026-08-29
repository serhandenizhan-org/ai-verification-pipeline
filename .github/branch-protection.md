# GitHub Branch Protection — Manuel Kurulum

Bu ayarlar kod ile yapılamaz, repo Settings üzerinden manuel olarak
yapılandırılmalıdır. `main` branch için:

1. Repo → **Settings** → **Branches** → **Add branch protection rule**
2. Branch name pattern: `main`
3. Aşağıdaki kutucukları işaretleyin:
   - [x] **Require a pull request before merging**
     - [x] Require approvals — en az **1**
   - [x] **Require status checks to pass before merging**
     - Zorunlu status check olarak şunları seçin:
       - `Fast CI / secret-scan`
       - `Fast CI / lint-typecheck-unit-build`
       - `Fast CI / e2e-playwright`
   - [x] **Require conversation resolution before merging**
   - [x] **Require linear history**
   - [x] **Do not allow bypassing the above settings**
     (repo admini dahil kimse kuralı atlayamaz)
4. **Save changes**

## Neden bu ayarlar?

- "Require a pull request" → main'e direkt push tamamen kapanır.
- "Require approvals" → Şef onayı olmadan merge butonu aktif olmaz.
- "Require status checks" → CI geçmeden merge edilemez.
- "Do not allow bypassing" → prensip kağıt üzerinde kalmaz, teknik olarak
  da zorlanır.
- "Require linear history" → Verification Ledger'daki audit trail temiz
  ve takip edilebilir kalır.

## Doğrulama

Ayarları yaptıktan sonra test edin: `main`'e doğrudan push denemesi
reddedilmeli, ve CI geçmeyen bir PR'da merge butonu pasif olmalı.
