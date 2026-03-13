#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vigila cuando citaconsular.es vuelve a estar accesible por HTTPS."""

import os, socket, time, requests
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")
HOST  = "www.citaconsular.es"
INTERVALO = 300  # 5 minutos

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sitio_accesible() -> bool:
    try:
        s = socket.create_connection((HOST, 443), timeout=10)
        s.close()
        return True
    except:
        return False

def telegram(msg):
    if not TOKEN or not CHAT:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT, "text": msg}, timeout=10)
    except:
        pass

log("Vigilando citaconsular.es — HTTPS port 443")
log("Ctrl+C para detener")

while True:
    if sitio_accesible():
        msg = (f"✅ citaconsular.es ACCESIBLE NUEVAMENTE\n"
               f"Hora: {datetime.now().strftime('%H:%M del %d/%m/%Y')}\n\n"
               f"Arranca el monitor OVC ahora.")
        log("SITIO ACCESIBLE — enviando alerta Telegram")
        telegram(msg)
        break
    else:
        log(f"Sitio aun caido — proximo chequeo en {INTERVALO//60} min")
        time.sleep(INTERVALO)

log("Listo. Corre ovc_monitor.py ahora.")
