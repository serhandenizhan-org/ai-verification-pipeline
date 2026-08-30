# GitHub Branch Protection — Manuel Kurulum (yalnızca gerekirse)

`install_pipeline.sh`, `owner/repo` argümanı verildiğinde bu ayarları
**otomatik olarak GitHub API üzerinden kurar** (bkz. script içindeki
`gh api .../branches/main/protection` çağrısı). Bu dosya yalnızca:
  - `gh` CLI'a erişiminiz yoksa, veya
  - Otomatik kurulum başarısız olduysa (script artık bunu SESSİZCE
    yutmuyor, açıkça uyarıyor — bkz. Codex review bulgusu, aşağıdaki not)

elle yapmanız gereken adımları gösterir.

**ÖNEMLİ — bu doküman daha önce ÇELİŞKİLİYDİ** (Codex review bulgusu):
Aşağıdaki "1 onay zorunlu" + "adminler dahil kimse atlayamaz" kombinasyonu,
projenin solo-geliştirme kararıyla (bkz. HANDOFF.md 4.1.11 — GitHub zaten
kendi PR'ını onaylamana izin vermiyor, bu yüzden solo projede zorunlu
1-onay kuralı PR'ları KALICI OLARAK kilitler) DOĞRUDAN ÇELİŞİYORDU. Bu
dosya artık `install_pipeline.sh`'in GERÇEKTEN kurduğu ayarlarla eşleşecek
şekilde güncellendi.

`main` branch için:

1. Repo → **Settings** → **Branches** → **Add branch protection rule**
2. Branch name pattern: `main`
3. Aşağıdaki kutucukları işaretleyin:
   - [x] **Require a pull request before merging**
     - [ ] Require approvals — **0** (solo geliştirme; GitHub zaten kendi
       PR'ını onaylamana izin vermiyor, >0 istersen ikinci bir hesap/
       collaborator gerekir)
   - [x] **Require status checks to pass before merging**
     - Zorunlu status check'ler — **GERÇEK isimlerle BİREBİR eşleşmeli**
       (bu, saatlerce debug edilen bir hataydı — bir job'ın GitHub'da
       göründüğü isim `job.name` alanıdır, `workflow adı / job id`
       DEĞİL):
       - `Secret Scan (gitleaks)`
       - `verification-gate` (tek bağlayıcı karar — bkz. verifier.py
         `gate` komutu, verification.yml)
   - [x] **Require conversation resolution before merging**
   - [x] **Require linear history**
   - [ ] **Do not allow bypassing the above settings** — KAPALI (solo
     geliştirmede admin'in kendi PR'ını gerekirse override edebilmesi
     gerekiyor, aksi halde kimse hiçbir PR'ı merge edemez)
4. **Save changes**

## Neden bu ayarlar?

- "Require a pull request" → main'e direkt push tamamen kapanır.
- "0 onay" → solo geliştirmede pratik; onay zorunluluğu GitHub'ın kendi
  kısıtı (kendi PR'ını onaylayamazsın) ile birleşince PR'ları kalıcı
  kilitlerdi.
- "Require status checks" (`Secret Scan (gitleaks)` + `verification-gate`)
  → CI VE Codex review VE circuit breaker VE secret tarama hepsi
  `verification-gate`'e bağlı, bu geçmeden merge edilemez.
- "Require linear history" → Verification Ledger'daki audit trail temiz
  ve takip edilebilir kalır.

## Doğrulama

Ayarları yaptıktan sonra test edin: `main`'e doğrudan push denemesi
reddedilmeli, ve `verification-gate` FAIL veren bir PR'da merge butonu
pasif olmalı.
