#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OVC Heartbeat — Mensaje diario 'estoy vivo' a Telegram"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

# ID unico de este run de GitHub Actions — diferente en cada ejecucion
RUN_ID    = os.environ.get("GITHUB_RUN_ID", "local")
RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "1")  # retry numero

print(f"[HEARTBEAT] RUN_ID={RUN_ID} ATTEMPT={RUN_ATTEMPT} PID={os.getpid()}", flush=True)

# Hora Miami (UTC-4 EDT)
miami = datetime.now(timezone(timedelta(hours=-4)))
fecha = miami.strftime("%d/%m/%Y")
hora  = miami.strftime("%H:%M:%S")   # incluye segundos para detectar duplicados

msg = (
    "\u2705 OVC Monitor \u2014 Estoy vivo\n"
    f"\U0001f4c5 {fecha}  \U0001f557 {hora} (Miami)\n"
    f"\U0001f194 Run: {RUN_ID} | Intento: {RUN_ATTEMPT}\n"
    "\u2500" * 25 + "\n"
    "\U0001f916 El bot est\u00e1 activo vigilando\n"
    "   el sitio de citas 24/7\n\n"
    "\u23f1 Frecuencia: cada ~7 min\n"
    "\U0001f4ca Checks aprox. hoy: ~140\n\n"
    "\U0001f534 Sin novedades hasta ahora.\n"
    "   Cuando haya cita recibir\u00e1s\n"
    "   alerta con bot\u00f3n ABRIR AHORA."
)

print(f"[HEARTBEAT] Enviando UNA vez a chat {TELEGRAM_CHAT_ID}...", flush=True)

r = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
    json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
    timeout=10,
)

print(f"[HEARTBEAT] Respuesta: status={r.status_code} ok={r.ok}", flush=True)
if r.ok:
    msg_id = r.json().get("result", {}).get("message_id", "?")
    print(f"[HEARTBEAT] Telegram message_id={msg_id} — LISTO, saliendo.", flush=True)
else:
    print(f"[HEARTBEAT] ERROR: {r.text[:200]}", flush=True)

sys.exit(0)   # salida explicita — sin posibilidad de continuar
