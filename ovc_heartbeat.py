#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OVC Heartbeat — Mensaje 'estoy vivo' con estadísticas del día a Telegram"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# "Estoy vivo" solo al admin — el grupo recibe SOLO alertas de citas
ADMIN_CHAT_ID      = os.environ.get("ADMIN_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", ""))
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO        = "Vcordero1962/ovc-monitor"

# ID único de este run de GitHub Actions
RUN_ID      = os.environ.get("GITHUB_RUN_ID", "local")
RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "1")

print(f"[HEARTBEAT] RUN_ID={RUN_ID} ATTEMPT={RUN_ATTEMPT} PID={os.getpid()}", flush=True)

MIN_INTERVALO_HORAS = 2  # No enviar si ya se envió hace menos de 2h


def ya_enviado_recientemente() -> bool:
    """Consulta GitHub API — si el heartbeat anterior corrió hace <MIN_INTERVALO_HORAS,
    este run es un duplicado por backlog del cron y debe abortarse."""
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
        runs = r.json().get("workflow_runs", [])
        for run in runs:
            if str(run.get("id")) == RUN_ID:
                continue  # Ignorar este mismo run
            created = run.get("created_at", "")
            if not created:
                continue
            ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
            hace_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            if hace_min < MIN_INTERVALO_HORAS * 60:
                print(f"[HEARTBEAT] SKIP — ya hubo heartbeat hace {hace_min:.0f} min (run {run['id']})", flush=True)
                return True
        return False
    except Exception as e:
        print(f"[HEARTBEAT] WARN rate-limit check: {e}", flush=True)
        return False


def get_stats_hoy() -> dict:
    """Consulta GitHub API para obtener estadísticas del bot del día de hoy."""
    if not GITHUB_TOKEN:
        return {}
    try:
        # Hora Miami (UTC-4)
        miami_tz = timezone(timedelta(hours=-4))
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
            print(f"[HEARTBEAT] GitHub API error {r.status_code}", flush=True)
            return {}

        runs = r.json().get("workflow_runs", [])
        total_hoy  = len(runs)
        exitosos   = sum(1 for x in runs if x.get("conclusion") == "success")
        fallidos   = sum(1 for x in runs if x.get("conclusion") == "failure")

        ultimo_hace = "?"
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
            "total_hoy":    total_hoy,
            "exitosos":     exitosos,
            "fallidos":     fallidos,
            "ultimo_hace":  ultimo_hace,
            "ultimo_estado": ultimo_estado,
        }
    except Exception as e:
        print(f"[HEARTBEAT] Stats error: {e}", flush=True)
        return {}


# Guardia anti-duplicados — abortar si ya hubo heartbeat reciente (cron backlog)
if ya_enviado_recientemente():
    print("[HEARTBEAT] Abortando — run duplicado por backlog del cron de GitHub Actions.", flush=True)
    sys.exit(0)

# Hora Miami (UTC-4 EDT)
miami = datetime.now(timezone(timedelta(hours=-4)))
fecha = miami.strftime("%d/%m/%Y")
hora  = miami.strftime("%H:%M:%S")

# Obtener estadísticas
stats = get_stats_hoy()
print(f"[HEARTBEAT] Stats: {stats}", flush=True)

# Construir línea de estadísticas
if stats:
    emoji_estado = "✅" if stats.get("fallidos", 0) == 0 else "⚠️"
    stats_line = (
        f"\n{emoji_estado} Checks hoy: {stats.get('exitosos', '?')}/{stats.get('total_hoy', '?')} exitosos"
        f"\n⏱ Último check: {stats.get('ultimo_hace', '?')} ({stats.get('ultimo_estado', '?')})"
    )
    if stats.get("fallidos", 0) > 0:
        stats_line += f"\n⚠️ Fallidos hoy: {stats['fallidos']}"
else:
    stats_line = "\n📊 Stats: no disponibles (sin token)"

msg = (
    "✅ OVC Monitor — Estoy vivo\n"
    f"📅 {fecha}  🕗 {hora} (Miami)\n"
    f"🆔 Run: {RUN_ID} | Intento: {RUN_ATTEMPT}\n"
    "─" * 25 + "\n"
    "🤖 El bot está activo vigilando\n"
    "   el sitio de citas 24/7\n"
    + stats_line + "\n\n"
    "⏱ Frecuencia: cada ~7 min\n"
    "🕗 Ventana critica: 8am España = 3am Miami\n\n"
    "🔴 Sin novedades hasta ahora.\n"
    "   Cuando haya cita recibirás\n"
    "   alerta con botón ABRIR AHORA."
)

print(f"[HEARTBEAT] Enviando a admin {ADMIN_CHAT_ID}...", flush=True)

r = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
    json={"chat_id": ADMIN_CHAT_ID, "text": msg, "disable_notification": True},
    timeout=10,
)

print(f"[HEARTBEAT] Respuesta: status={r.status_code} ok={r.ok}", flush=True)
if r.ok:
    msg_id = r.json().get("result", {}).get("message_id", "?")
    print(f"[HEARTBEAT] Telegram message_id={msg_id} — LISTO.", flush=True)
else:
    print(f"[HEARTBEAT] ERROR: {r.text[:200]}", flush=True)

sys.exit(0)
