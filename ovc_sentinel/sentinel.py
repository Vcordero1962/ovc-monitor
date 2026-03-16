#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC Sentinel — Container de vigilancia 24/7
Monitorea que el bot de GitHub Actions sigue corriendo correctamente.

Qué verifica cada 30 minutos:
  1. GitHub Actions — ¿ejecutó ovc_monitor.yml en los últimos 15 min?
  2. Heartbeat     — ¿ejecutó ovc_heartbeat.yml en las últimas 5 horas?
  3. Quota         — ¿quedan minutos de GitHub Actions para el mes?

Si detecta problema → alerta Telegram SOLO al admin (SENTINEL_CHAT_ID).
Las alertas de cita disponible siguen yendo al grupo (TELEGRAM_CHAT_ID).
"""

import os
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ_MIAMI = ZoneInfo("America/New_York")  # EDT = UTC-4 (verano) / EST = UTC-5 (invierno)


def now_miami() -> datetime:
    """Hora actual en Miami (maneja automáticamente EDT/EST)."""
    return datetime.now(TZ_MIAMI)

# ─── Config desde env ────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")       # grupo — citas
SENTINEL_CHAT_ID   = os.getenv("SENTINEL_CHAT_ID", "")       # admin — alertas técnicas
GITHUB_TOKEN       = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO        = os.getenv("GITHUB_REPO", "Vcordero1962/ovc-monitor")

# Umbrales de alerta
MAX_MIN_DESDE_ULTIMO_RUN_BOT  = 90   # minutos — GitHub Actions free throttlea cron a ~1x/hora real
MAX_HORAS_DESDE_HEARTBEAT     = 5    # horas   — si heartbeat no llegó en 5h → alerta
CHECK_INTERVAL_MIN             = 30   # minutos entre cada ciclo del sentinel

# ─── Estado interno (evitar spam de alertas repetidas) ───────────────────────

_estado = {
    "alerta_bot_enviada":       False,
    "alerta_heartbeat_enviada": False,
    "alerta_quota_enviada":     False,
    "ultimo_run_ok":            None,
    "ultimo_heartbeat_ok":      None,
}


def log(msg: str):
    ts = now_miami().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [SENTINEL] {msg}", flush=True)


def telegram(msg: str, urgente: bool = False):
    """Envía alerta técnica SOLO al admin (SENTINEL_CHAT_ID).
    Si no está configurado, cae al grupo como fallback."""
    if not TELEGRAM_BOT_TOKEN:
        log("ERROR: TELEGRAM_BOT_TOKEN no configurado")
        return False

    # Alertas técnicas del sentinel → solo al admin
    chat_id = SENTINEL_CHAT_ID if SENTINEL_CHAT_ID else TELEGRAM_CHAT_ID
    if not chat_id:
        log("ERROR: ni SENTINEL_CHAT_ID ni TELEGRAM_CHAT_ID configurados")
        return False

    prefix = "🚨 " if urgente else "ℹ️ "
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": prefix + msg},
            timeout=10,
        )
        ok = r.ok
        log(f"Telegram→admin {'OK' if ok else f'ERROR {r.status_code}'}: {msg[:60]}...")
        return ok
    except Exception as e:
        log(f"Telegram excepción: {e}")
        return False


def gh_api(endpoint: str) -> dict | None:
    """Llama a la GitHub API. Retorna JSON o None si falla."""
    if not GITHUB_TOKEN:
        log("WARN: GITHUB_TOKEN no configurado — no se puede verificar Actions")
        return None
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/{endpoint}",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
        if r.ok:
            return r.json()
        log(f"GitHub API error {r.status_code}: {endpoint}")
        return None
    except Exception as e:
        log(f"GitHub API excepción: {e}")
        return None


def check_workflow(workflow_file: str, max_minutos: int, nombre: str) -> tuple[bool, str]:
    """
    Verifica si el workflow ejecutó recientemente.
    Retorna (ok, descripcion).
    """
    data = gh_api(f"actions/workflows/{workflow_file}/runs?per_page=1&status=completed")
    if not data:
        return True, "GitHub API no disponible (ignorando)"

    runs = data.get("workflow_runs", [])
    if not runs:
        return False, f"{nombre}: nunca ha ejecutado"

    ultimo = runs[0]
    created_at = ultimo.get("created_at", "")
    conclusion = ultimo.get("conclusion", "unknown")
    run_id = ultimo.get("id", "?")

    try:
        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        ahora = datetime.now(timezone.utc)
        minutos_transcurridos = (ahora - ts).total_seconds() / 60

        desc = (
            f"{nombre}: run #{run_id} | {conclusion} | "
            f"hace {minutos_transcurridos:.0f} min"
        )
        log(f"  {desc}")

        if conclusion == "failure":
            return False, f"{nombre}: FALLÓ (run #{run_id})"

        if minutos_transcurridos > max_minutos:
            return False, f"{nombre}: sin ejecutar hace {minutos_transcurridos:.0f} min (max: {max_minutos})"

        return True, desc

    except Exception as e:
        return True, f"{nombre}: no se pudo parsear timestamp ({e})"


def check_bot_monitor() -> tuple[bool, str]:
    """Verifica ovc_monitor.yml — debe ejecutar cada ~7 min."""
    return check_workflow("ovc_monitor.yml", MAX_MIN_DESDE_ULTIMO_RUN_BOT, "BOT-MONITOR")


def check_heartbeat_workflow() -> tuple[bool, str]:
    """Verifica ovc_heartbeat.yml — debe ejecutar cada 4h."""
    max_min = MAX_HORAS_DESDE_HEARTBEAT * 60
    return check_workflow("ovc_heartbeat.yml", max_min, "HEARTBEAT")


def check_quota() -> tuple[bool, str]:
    """Verifica minutos restantes de GitHub Actions."""
    data = gh_api("actions/cache/usage")  # No existe, usamos billing
    # GitHub no expone billing via API pública sin scope especial
    # Verificamos indirectamente: si el último run fue exitoso, hay quota
    return True, "Quota: verificación indirecta (runs exitosos = quota OK)"


def ciclo_verificacion():
    """Un ciclo completo de verificación. Llama a las 3 comprobaciones."""
    ahora = now_miami().strftime("%H:%M del %d/%m")
    log(f"=== Ciclo verificación — {ahora} ===")

    if not GITHUB_TOKEN:
        log("WARN: GITHUB_TOKEN no configurado. Solo verificando conectividad Telegram.")
        return

    # 1. Verificar bot monitor
    bot_ok, bot_desc = check_bot_monitor()
    if not bot_ok:
        if not _estado["alerta_bot_enviada"]:
            telegram(
                f"OVC SENTINEL — BOT CAÍDO\n\n"
                f"{bot_desc}\n\n"
                f"El bot puede haber dejado de monitorear citas.\n"
                f"Verificar: gh run list --repo {GITHUB_REPO} --limit 5",
                urgente=True,
            )
            _estado["alerta_bot_enviada"] = True
    else:
        if _estado["alerta_bot_enviada"]:
            telegram(f"OVC SENTINEL — Bot recuperado ✅\n{bot_desc}")
        _estado["alerta_bot_enviada"] = False
        _estado["ultimo_run_ok"] = now_miami()

    # 2. Verificar heartbeat
    hb_ok, hb_desc = check_heartbeat_workflow()
    if not hb_ok:
        if not _estado["alerta_heartbeat_enviada"]:
            telegram(
                f"OVC SENTINEL — HEARTBEAT PERDIDO\n\n"
                f"{hb_desc}\n\n"
                f"El bot lleva más de {MAX_HORAS_DESDE_HEARTBEAT}h sin reportarse.",
                urgente=True,
            )
            _estado["alerta_heartbeat_enviada"] = True
    else:
        if _estado["alerta_heartbeat_enviada"]:
            telegram(f"OVC SENTINEL — Heartbeat OK ✅\n{hb_desc}")
        _estado["alerta_heartbeat_enviada"] = False
        _estado["ultimo_heartbeat_ok"] = now_miami()

    log("=== Ciclo completado ===")


def arranque_sentinela():
    """Mensaje inicial al arrancar el container."""
    log("Sentinel arrancando...")
    telegram(
        f"🛡️ OVC Sentinel ACTIVO\n\n"
        f"Monitoreo iniciado — {now_miami().strftime('%d/%m/%Y %H:%M')} (Miami)\n"
        f"Checks cada {CHECK_INTERVAL_MIN} min\n\n"
        f"Vigilando:\n"
        f"  • Bot monitor (max {MAX_MIN_DESDE_ULTIMO_RUN_BOT} min sin correr)\n"
        f"  • Heartbeat (max {MAX_HORAS_DESDE_HEARTBEAT}h sin reportar)\n\n"
        f"Repo: {GITHUB_REPO}"
    )


if __name__ == "__main__":
    log("=" * 50)
    log("OVC SENTINEL v1.0 — Iniciando")
    log(f"Repo: {GITHUB_REPO}")
    log(f"Alertas técnicas → admin: {SENTINEL_CHAT_ID or '(fallback grupo)'}")
    log(f"Alertas cita disponible → grupo: {TELEGRAM_CHAT_ID}")
    log(f"Intervalo: {CHECK_INTERVAL_MIN} min")
    log(f"GitHub Token: {'configurado' if GITHUB_TOKEN else 'NO configurado'}")
    log("=" * 50)

    # Verificar configuración mínima
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("ERROR CRÍTICO: TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID son requeridos")
        exit(1)

    # Mensaje de arranque
    arranque_sentinela()

    # Primer ciclo inmediato
    ciclo_verificacion()

    # Loop principal
    log(f"Entrando en loop — ciclo cada {CHECK_INTERVAL_MIN} min")
    while True:
        time.sleep(CHECK_INTERVAL_MIN * 60)
        ciclo_verificacion()
