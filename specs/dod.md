# Definition of Done (DoD)

Proje geneli, sabit kalite kapısı. Her PR, hangi feature olursa olsun bu
listeden geçmelidir. Acceptance Criteria (AC) ile karıştırılmamalıdır —
AC her feature'a özeldir, DoD projeye özeldir. Detaylı karşılaştırma için
ekip içi spesifikasyon PDF'ine bakın.

## Zorunlu kontrol listesi

- [ ] Lint hatasız geçiyor
- [ ] Type check hatasız geçiyor
- [ ] Unit test coverage eşiği karşılanmış
- [ ] Integration testler yeşil
- [ ] Playwright E2E testleri yeşil
- [ ] `npm audit` / `pip-audit` bilinen kritik açık göstermiyor
- [ ] gitleaks secret taraması temiz
- [ ] Reviewer Codex PASS (veya Şef onaylı istisna, ledger'da not düşülmüş)
- [ ] Yeni public API/endpoint dökümante edilmiş
- [ ] Hardcoded secret / credential yok
- [ ] İlgili feature'ın tüm AC'leri karşılanmış
- [ ] Verification Ledger'da bu PR için eksiksiz kayıt var

## Bu liste ne zaman değişir?

DoD, proje genelinde nadiren değişir. Değiştirmek isteyen kişi Orchestrator
aracılığıyla Şef'e önerir; Şef onayı olmadan bu dosya güncellenmez.
