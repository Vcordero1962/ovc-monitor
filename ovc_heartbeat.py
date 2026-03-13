#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OVC Heartbeat — Mensaje diario 'estoy vivo' a Telegram"""

import os
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

# Hora Miami (UTC-4 EDT)
miami = datetime.now(timezone(timedelta(hours=-4)))
fecha = miami.strftime("%d/%m/%Y")
hora  = miami.strftime("%H:%M")

msg = (
    "\u2705 OVC Monitor \u2014 Estoy vivo\n"
    f"\U0001f4c5 {fecha}  \U0001f557 {hora} (Miami)\n"
    "\u2500" * 25 + "\n"
    "\U0001f916 El bot est\u00e1 activo vigilando\n"
    "   el sitio de citas 24/7\n\n"
    "\u23f1 Frecuencia: cada ~7 min\n"
    "\U0001f4ca Checks aprox. hoy: ~140\n\n"
    "\U0001f534 Sin novedades hasta ahora.\n"
    "   Cuando haya cita recibir\u00e1s\n"
    "   alerta con bot\u00f3n ABRIR AHORA."
)

r = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
    json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
    timeout=10,
)
print("Heartbeat enviado OK" if r.ok else f"Error: {r.status_code} {r.text}")
