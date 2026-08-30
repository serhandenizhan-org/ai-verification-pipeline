#!/usr/bin/env bash
#
# verify_ac_lock.sh — ince wrapper. Gerçek mantık artık scripts/verify_ac_lock.py
# içinde (Postgres'teki bağımsız kilit kaydına bakıyor — bkz. orchestrator/ac_lock.py
# docstring'i, Codex review bulgusu). Bu dosya yalnızca mevcut workflow
# çağrılarının (`bash scripts/verify_ac_lock.sh`) değişmeden çalışmaya
# devam etmesi için var.

set -euo pipefail
exec python3 "$(dirname "${BASH_SOURCE[0]}")/verify_ac_lock.py"
