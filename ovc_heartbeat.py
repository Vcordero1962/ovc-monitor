#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OVC Heartbeat — Mensaje 'estoy vivo' con estadísticas del día a Telegram.
Estrategia SIN estado externo:
  1. Busca el mensaje PINNEADO en el chat del admin.
  2. Si existe y es del bot → lo EDITA (0 mensajes nuevos).
  3. Si no → envía nuevo y lo PINNEA.
Resultado: siempre hay exactamente 1 mensaje 'Estoy vivo' en el chat del admin.
"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# "Estoy vivo" solo al admin — el grupo recibe SOLO alertas de citas
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", ""))
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO   = "Vcordero1962/ovc-monitor"

RUN_ID      = os.environ.get("GITHUB_RUN_ID", "local")
RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
RUN_NUMBER  = os.environ.get("GITHUB_RUN_NUMBER", "?")

MIN_INTERVALO_HORAS = 2  # No enviar si ya se envió hace menos de 2h

BASE_TG = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

print(f"[HEARTBEAT] RUN_ID={RUN_ID} ATTEMPT={RUN_ATTEMPT}", flush=True)


# ─── Anti-duplicados ──────────────────────────────────────────────────────────

def ya_enviado_recientemente() -> bool:
    if not GITHUB_TOKEN:
        return False
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/ovc_heartbeat.yml/runs",
            params={"per_page": 5, "status": "success"},
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        if not r.ok:
            return False
        for run in r.json().get("workflow_runs", []):
            if str(run.get("id")) == RUN_ID:
                continue
            created = run.get("created_at", "")
            if not created:
                continue
            ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
            hace_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            if hace_min < MIN_INTERVALO_HORAS * 60:
                print(f"[HEARTBEAT] SKIP — ya hubo heartbeat hace {hace_min:.0f} min", flush=True)
                return True
        return False
    except Exception as e:
        print(f"[HEARTBEAT] WARN check: {e}", flush=True)
        return False


# ─── Stats ────────────────────────────────────────────────────────────────────

def get_stats_hoy() -> dict:
    if not GITHUB_TOKEN:
        return {}
    try:
        miami_tz  = timezone(timedelta(hours=-4))
        hoy_inicio = datetime.now(miami_tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/ovc_monitor.yml/runs",
            params={"per_page": 100, "created": f">={hoy_inicio}"},
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        if not r.ok:
            return {}
        runs       = r.json().get("workflow_runs", [])
        total_hoy  = len(runs)
        exitosos   = sum(1 for x in runs if x.get("conclusion") == "success")
        fallidos   = sum(1 for x in runs if x.get("conclusion") == "failure")
        ultimo_hace   = "?"
        ultimo_estado = "?"
        if runs:
            ultimo = runs[0]
            ultimo_estado = ultimo.get("conclusion", "en curso")
            created = ultimo.get("created_at", "")
            if created:
                ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                minutos = int((datetime.now(timezone.utc) - ts).total_seconds() / 60)
                ultimo_hace = f"hace {minutos} min"
        return {
            "total_hoy":     total_hoy,
            "exitosos":      exitosos,
            "fallidos":      fallidos,
            "ultimo_hace":   ultimo_hace,
            "ultimo_estado": ultimo_estado,
        }
    except Exception as e:
        print(f"[HEARTBEAT] Stats error: {e}", flush=True)
        return {}


# ─── Telegram helpers ─────────────────────────────────────────────────────────

def get_pinned_msg_id() -> int | None:
    """Obtiene el message_id del mensaje pinneado en el chat del admin."""
    try:
        r = requests.get(f"{BASE_TG}/getChat",
                         params={"chat_id": ADMIN_CHAT_ID}, timeout=10)
        if r.ok:
            pinned = r.json().get("result", {}).get("pinned_message")
            if pinned:
                mid = pinned.get("message_id")
                print(f"[HEARTBEAT] Mensaje pinneado encontrado: id={mid}", flush=True)
                return mid
    except Exception as e:
        print(f"[HEARTBEAT] getChat error: {e}", flush=True)
    return None


def editar_mensaje(msg_id: int, texto: str) -> bool:
    """Edita un mensaje existente. Retorna True si tuvo éxito."""
    r = requests.post(f"{BASE_TG}/editMessageText", json={
        "chat_id":    ADMIN_CHAT_ID,
        "message_id": msg_id,
        "text":       texto,
    }, timeout=10)
    if r.ok:
        print(f"[HEARTBEAT] Mensaje EDITADO — id={msg_id}", flush=True)
        return True
    err = r.json().get("description", r.text[:80])
    print(f"[HEARTBEAT] Edit falló ({r.status_code}): {err}", flush=True)
    return False


def enviar_nuevo(texto: str) -> int | None:
    """Envía un mensaje nuevo. Retorna el message_id."""
    r = requests.post(f"{BASE_TG}/sendMessage", json={
        "chat_id":            ADMIN_CHAT_ID,
        "text":               texto,
        "disable_notification": True,
    }, timeout=10)
    if r.ok:
        mid = r.json().get("result", {}).get("message_id")
        print(f"[HEARTBEAT] Mensaje NUEVO enviado — id={mid}", flush=True)
        return mid
    print(f"[HEARTBEAT] sendMessage ERROR: {r.text[:100]}", flush=True)
    return None


def pinnear(msg_id: int):
    """Pinnea el mensaje en el chat para que sea el 'contenedor' del heartbeat."""
    r = requests.post(f"{BASE_TG}/pinChatMessage", json={
        "chat_id":              ADMIN_CHAT_ID,
        "message_id":           msg_id,
        "disable_notification": True,
    }, timeout=10)
    ok = r.ok
    print(f"[HEARTBEAT] Pin {'OK' if ok else f'falló ({r.status_code}): {r.text[:60]}'}", flush=True)


# ─── Main ─────────────────────────────────────────────────────────────────────

if ya_enviado_recientemente():
    print("[HEARTBEAT] Abortando — duplicado de cron backlog.", flush=True)
    sys.exit(0)

miami = datetime.now(timezone(timedelta(hours=-4)))
stats = get_stats_hoy()
print(f"[HEARTBEAT] Stats: {stats}", flush=True)

if stats:
    emoji_estado = "✅" if stats.get("fallidos", 0) == 0 else "⚠️"
    stats_line = (
        f"\n{emoji_estado} Checks hoy: {stats.get('exitosos','?')}/{stats.get('total_hoy','?')} exitosos"
        f"\n⏱ Ultimo check: {stats.get('ultimo_hace','?')} ({stats.get('ultimo_estado','?')})"
    )
    if stats.get("fallidos", 0) > 0:
        stats_line += f"\n⚠️ Fallidos hoy: {stats['fallidos']}"
else:
    stats_line = "\nStats: no disponibles"

msg = (
    f"✅ OVC Monitor - Estoy vivo  #{RUN_NUMBER}\n"
    f"📅 {miami.strftime('%d/%m/%Y')}  🕗 {miami.strftime('%H:%M:%S')} (Miami)\n"
    f"Run: {RUN_ID}\n"
    "─────────────────────────\n"
    "🤖 Bot activo vigilando citas 24/7"
    + stats_line + "\n\n"
    "⏱ Checks cada ~7 min\n"
    "🕗 Ventana critica: 8am España = 3am Miami\n"
    "🔴 Sin novedades. Alerta cuando haya cita."
)

# Intentar editar el mensaje pinneado existente
pinned_id = get_pinned_msg_id()
if pinned_id and editar_mensaje(pinned_id, msg):
    print("[HEARTBEAT] LISTO — mensaje pinneado actualizado, sin mensajes nuevos.", flush=True)
else:
    # Primera vez o pin perdido — enviar nuevo y pinnearlo
    nuevo_id = enviar_nuevo(msg)
    if nuevo_id:
        pinnear(nuevo_id)
        print("[HEARTBEAT] LISTO — nuevo mensaje enviado y pinneado.", flush=True)

sys.exit(0)
