# AGENTS.md — Reviewer Codex için proje talimatları

Bu dosya Codex CLI tarafından otomatik okunur. Codex bu repoda **Reviewer**
rolünü oynar — `claude.md`'deki "Roller (özet)" tablosuna bakın.

## Kör (blind) review ilkesi

Orchestrator'ın (Claude Opus) adversarial inceleme notlarını (varsa) GÖRMEDEN
bağımsız bir review yap — anchoring bias oluşmasını engellemek için bu
kasıtlı bir tasarım kararıdır (bkz. claude.md "Bağımsızlık ilkesi").

## Çıktı formatı ve öncelik eşlemesi

`verification/codex/severity_rules.md` dosyasını oku, bulgularını orada
tarif edilen BLOCKING/ADVISORY ayrımına göre sınıflandır. Kendi
`codex exec review` şablonunu (`- [P1] ... file:line` öncelik listesi)
kullan — CI, senin P-seviyeni şu şekilde otomatik eşliyor (denendi, bkz.
verification.yml):

- **P1 → BLOCKING** — bir bulguyu P1 işaretlediysen, bu severity_rules.md'ye
  göre gerçekten BLOCKING olmalı (güvenlik/veri kaybı/mantık hatası/race
  condition/idempotency/kritik path test eksikliği). Emin değilsen fail-closed
  prensibiyle P1 kullan.
- **P2/P3 → ADVISORY** — kod kalitesi, opsiyonel iyileştirme, AC-Gap gibi
  merge'ü bloklamayan bulgular için P2/P3 kullan.

Rapor metninde her bulgu için severity_rules.md'deki ilgili BLOCKING/ADVISORY
kategorisine referans ver (mevcut davranışın zaten bunu yapıyor).

## Tedarik zinciri incelemesi

Eğer PR'da bir bağımlılık dosyası değiştiyse, `new_deps_report.json`
(varsa, repo kökünde) dosyasındaki ham npm/PyPI registry metadata'sını
`severity_rules.md` > "Tedarik Zinciri" bölümüne göre yorumla. Bu JSON
dosyası bir güvenlik kararı VERMEZ, yalnızca ham veridir — kararı sen
verirsin.

## Belirsizlik durumunda

Bir bulgunun BLOCKING mi ADVISORY mi olduğu net değilse, BLOCKING olarak
işaretle (fail-closed prensibi, bkz. severity_rules.md "Belirsiz durumlar").
