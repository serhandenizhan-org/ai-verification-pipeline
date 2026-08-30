-- schema.sql
--
-- Verification Ledger — PostgreSQL şeması.
--
-- JSON dosya bazlı ledger'dan (.verification/ledger/pr-<no>.jsonl) taşındı
-- (bkz. HANDOFF.md 3.3) — çoklu PR eşzamanlılığında sorgulanabilirlik için.
--
-- Append-only prensip korunuyor: satırlar hiçbir zaman UPDATE/DELETE
-- edilmez, yalnızca INSERT yapılır (ledger.py bunu zorunlu kılar, ama
-- ekstra güvence için bu tabloya UPDATE/DELETE yetkisi veren bir rol
-- oluşturmayın).
--
-- `repo` kolonu: tüm projeler AYNI Postgres veritabanını paylaşıyor (tek
-- Mac mini, tek DB) — bu kolon olmadan iki farklı projenin aynı PR numarası
-- ledger'da karışırdı. ledger.py bunu her zaman zorunlu kılar (fail-closed).
--
-- Kullanım:
--   psql "$DATABASE_URL" -f orchestrator/schema.sql
--
-- Not: ledger.py bu tabloyu ilk bağlantıda "CREATE TABLE IF NOT EXISTS" ile
-- zaten kendisi oluşturur (ve eski repo'suz şemadan otomatik migrate eder)
-- — bu dosya asıl olarak dokümantasyon/manuel kurulum ve şema geçmişini
-- takip etmek içindir.

CREATE TABLE IF NOT EXISTS ledger_entries (
    id          BIGSERIAL PRIMARY KEY,
    repo        TEXT NOT NULL,
    pr          INTEGER NOT NULL,
    event       TEXT NOT NULL,
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    "timestamp" TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ledger_entries_repo_pr ON ledger_entries (repo, pr);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_repo_pr_id ON ledger_entries (repo, pr, id);

COMMENT ON TABLE ledger_entries IS
    'Append-only Verification Ledger. Yalnızca orchestrator/ledger.py bu tabloya yazar; agent''lar (Builder, Codex) doğrudan erişemez. repo kolonu ("owner/repo") çoklu proje izolasyonu için zorunludur.';
