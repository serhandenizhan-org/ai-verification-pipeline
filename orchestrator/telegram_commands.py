#!/usr/bin/env python3
"""
telegram_commands.py — Codex'in önerdiği özellik 7'nin "yetkili
durdur/devam" yarısı: Telegram üzerinden Şef'in gönderdiği komutları
işler.

NASIL ÇALIŞIR: Bu pipeline event-driven'dır (GitHub Actions workflow_run
tetiklemesiyle çalışır), kalıcı bir arka plan daemon'u yoktur. Bu yüzden
gerçek zamanlı bir Telegram bot'u yerine, `verification-gate` job'u HER
ÇALIŞTIĞINDA (yani her PR event'inde) Telegram'ın `getUpdates` API'sini
BİR KEZ (long-poll değil, kısa timeout'lu tek çağrı) sorgular, bekleyen
komutları işler. Bu, "her PR tetiklemesinde komutlar da kontrol edilir"
anlamına gelir — PR trafiği yoksa komutlar bir sonraki PR event'ine kadar
bekler (kabul edilebilir bir gecikme, claude.md'nin gerektirdiği "Şef
kararı" mekanizmasını gerçek bir daemon kurmadan sağlar).

YETKİLENDİRME: Yalnızca `.env`/GitHub Secrets'taki TELEGRAM_CHAT_ID'den
gelen mesajlar işlenir — başka hiçbir chat_id'den gelen komut çalıştırılmaz
(fail-closed: bilinmeyen gönderen = yok say, hata da verme, sessizce atla
ama LOGLA).

DESTEKLENEN KOMUTLAR (bkz. claude.md "Telegram bot komutları"):
  /durdur <owner/repo> <sebep...>
  /devam <owner/repo>
  /kabul <owner/repo> <fingerprint> <saat|kalici> <sebep...>
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
import json as _json

import finding_triage
import pipeline_control
from ledger import _connect  # type: ignore

_SCHEMA_INIT_LOCK_ID = 847_291_015

_SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_offset (
    id INT PRIMARY KEY DEFAULT 1,
    last_update_id BIGINT NOT NULL DEFAULT 0,
    CONSTRAINT single_row CHECK (id = 1)
);
"""

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


def _ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_INIT_LOCK_ID,))
        cur.execute(_SCHEMA)
    conn.commit()


def _get_offset() -> int:
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT last_update_id FROM telegram_offset WHERE id = 1")
            row = cur.fetchone()
            return row["last_update_id"] if row else 0
    finally:
        conn.close()


def _set_offset(update_id: int) -> None:
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telegram_offset (id, last_update_id) VALUES (1, %s)
                ON CONFLICT (id) DO UPDATE SET last_update_id = %s
                """,
                (update_id, update_id),
            )
        conn.commit()
    finally:
        conn.close()


def _api_call(method: str, token: str, params: dict) -> dict:
    url = f"{TELEGRAM_API_BASE.format(token=token)}/{method}"
    data = _json.dumps(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return _json.loads(resp.read())


def _reply(token: str, chat_id: str, text: str) -> None:
    try:
        _api_call("sendMessage", token, {"chat_id": chat_id, "text": text})
    except (urllib.error.URLError, OSError):
        pass


def _handle_command(token: str, chat_id: str, text: str) -> None:
    parts = text.strip().split()
    if not parts:
        return
    cmd = parts[0].lower()

    try:
        if cmd == "/durdur" and len(parts) >= 2:
            repo, reason = parts[1], " ".join(parts[2:]) or "sebep belirtilmedi"
            pipeline_control.set_stopped(repo, "telegram:sef", reason)
            _reply(token, chat_id, f"✅ Durduruldu: {repo}\nSebep: {reason}")

        elif cmd == "/devam" and len(parts) >= 2:
            repo = parts[1]
            ok = pipeline_control.clear_stopped(repo, "telegram:sef")
            _reply(token, chat_id, f"✅ Devam ettirildi: {repo}" if ok else f"ℹ️ Zaten durdurulmamıştı: {repo}")

        elif cmd == "/kabul" and len(parts) >= 4:
            repo, fingerprint, duration = parts[1], parts[2], parts[3]
            reason = " ".join(parts[4:]) or "sebep belirtilmedi"
            hours = None if duration.lower() in ("kalici", "kalıcı") else float(duration)
            ok = finding_triage.accept_finding(repo, fingerprint, "telegram:sef", reason, hours)
            if ok:
                scope = "kalıcı" if hours is None else f"{hours} saat"
                _reply(token, chat_id, f"✅ Kabul edildi ({scope}): {repo} / {fingerprint}\nSebep: {reason}")
            else:
                _reply(token, chat_id, f"⚠️ Bulunamadı: {repo} / {fingerprint}")

        else:
            _reply(token, chat_id, f"Bilinmeyen komut ya da eksik parametre: {text}\n"
                                    "Kullanım: /durdur <repo> <sebep> | /devam <repo> | "
                                    "/kabul <repo> <fingerprint> <saat|kalici> <sebep>")
    except ValueError as e:
        _reply(token, chat_id, f"⚠️ Hata: {e}")


def poll_once() -> int:
    """
    Bekleyen Telegram mesajlarını bir kez sorgular, yetkili chat_id'den
    gelenleri işler. `verification-gate` job'unun her çalışmasında
    çağrılması amaçlanır. Token/chat_id tanımlı değilse sessizce no-op.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    authorized_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not authorized_chat_id:
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID tanımlı değil, komut kontrolü atlanıyor.")
        return 0

    offset = _get_offset()
    try:
        result = _api_call("getUpdates", token, {"offset": offset + 1, "timeout": 0, "limit": 20})
    except (urllib.error.URLError, OSError) as e:
        print(f"Telegram getUpdates başarısız: {e}")
        return 0

    updates = result.get("result", [])
    processed = 0
    max_update_id = offset
    for update in updates:
        update_id = update["update_id"]
        max_update_id = max(max_update_id, update_id)
        message = update.get("message") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")

        if chat_id != str(authorized_chat_id):
            print(f"Yetkisiz chat_id'den mesaj yok sayıldı: {chat_id}")
            continue
        if text.startswith("/"):
            _handle_command(token, chat_id, text)
            processed += 1

    if max_update_id > offset:
        _set_offset(max_update_id)

    print(f"{len(updates)} güncelleme alındı, {processed} komut işlendi.")
    return 0


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("poll-once", help="Bekleyen Telegram komutlarını bir kez işle")
    parser.parse_args()
    return poll_once()


if __name__ == "__main__":
    sys.exit(_cli())
