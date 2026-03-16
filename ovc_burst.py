#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OVC Burst — Modo Ráfaga para ventana crítica de apertura de citas.

Corre un loop continuo durante MAX_MIN minutos, sondeando Bookitit
cada POLL_INTERVAL ±JITTER segundos. No usa Playwright ni proxy residencial.
Alerta Telegram con sonido en cuanto dates[] sea no-vacío.

Variables de entorno (mismas que ovc_once.py):
  TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID, TELEGRAM_CHAT_ID
  URL_SISTEMA, URL_LEGA, URL_LMD  (widget URLs de citaconsular.es)
  AVC_TRAMITE: "ALL", "LMD,LEGA", etc.
  MAX_MIN:          minutos de vigilancia continua (default 35)
  POLL_INTERVAL:    segundos entre checks (default 45)
  POLL_JITTER:      ±variación aleatoria en segundos (default 10)
"""

import os
import re
import sys
import time
import random
import requests
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ── Configuración ────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
ADMIN_CHAT_ID      = os.getenv("ADMIN_CHAT_ID", "")
URL_SISTEMA        = os.getenv("URL_SISTEMA", "")
AVC_TRAMITE        = os.getenv("AVC_TRAMITE", "ALL").upper()

MAX_MIN       = int(os.getenv("MAX_MIN",       "35"))   # duración máxima del loop
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "45"))   # segundos base entre polls
POLL_JITTER   = int(os.getenv("POLL_JITTER",   "10"))   # ±segundos de variación

# Catálogo mínimo — solo los tramites más urgentes para el burst
SERVICIOS = {
    "LEGA": {"nombre": "Legalizaciones (LEGA)",         "url_env": "URL_LEGA"},
    "LMD":  {"nombre": "Ley Memoria Democratica (LMD)", "url_env": "URL_LMD"},
    "PASAPORTE":  {"nombre": "Pasaporte / DNI",          "url_env": "URL_PASAPORTE"},
    "VISADO":     {"nombre": "Visados",                  "url_env": "URL_VISADO"},
    "MATRIMONIO": {"nombre": "Matrimonio / Reg. Civil",  "url_env": "URL_MATRIMONIO"},
    "NACIMIENTO": {"nombre": "Nacimiento / Fe de Vida",  "url_env": "URL_NACIMIENTO"},
    "NOTARIAL":   {"nombre": "Tramites Notariales",      "url_env": "URL_NOTARIAL"},
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _tramites_activos() -> list:
    if AVC_TRAMITE == "ALL":
        return list(SERVICIOS.keys())
    return [t.strip() for t in AVC_TRAMITE.split(",") if t.strip() in SERVICIOS] or list(SERVICIOS.keys())


def _parse_bkt(text: str) -> dict:
    """Extrae agendas[] y dates[] del objeto JS bkt_init_widget (claves sin comillas)."""
    m  = re.search(r"(?:['\"]agendas['\"]|agendas)\s*:\s*(\[[^\]]*\])", text, re.DOTALL)
    m2 = re.search(r"(?:['\"]dates['\"]|dates)\s*:\s*(\[[^\]]*\])",   text, re.DOTALL)
    return {
        "agendas": len(re.findall(r'\{',            m.group(1)  if m  else "[]")),
        "dates":   len(re.findall(r'\d{4}-\d{2}-\d{2}', m2.group(1) if m2 else "[]")),
        "raw":     (m2.group(1) if m2 else "[]")[:120],
    }


def check_bkt(widget_url: str) -> tuple:
    """
    GET captcha gate → extrae token → POST → parsea bkt_init_widget.
    Retorna (disponible: bool, info: dict).
    """
    ua = random.choice(USER_AGENTS)
    sess = requests.Session()
    hdrs = {
        "User-Agent":                ua,
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":           "es-ES,es;q=0.9",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control":             "max-age=0",
    }
    try:
        r = sess.get(widget_url, headers=hdrs, timeout=25, allow_redirects=True)
        if not r.ok:
            log(f"      GET {r.status_code}")
            return False, {}
        html = r.text
        log(f"      GET {r.status_code} {len(html)}ch")

        tok = None
        m = re.search(r'name=["\']token["\'][^>]*value=["\']([^"\']+)["\']', html)
        if not m:
            m = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']token["\']', html)
        if m:
            tok = m.group(1)
        else:
            log("      token: NO encontrado")
            return False, {}

        time.sleep(random.uniform(0.5, 1.5))
        ph = dict(hdrs)
        ph.update({
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer":      widget_url,
            "Sec-Fetch-Site": "same-origin",
        })
        rp = sess.post(widget_url, data={"token": tok}, headers=ph, timeout=25, allow_redirects=True)
        if not rp.ok:
            log(f"      POST {rp.status_code}")
            return False, {}
        pt = rp.text
        log(f"      POST {rp.status_code} {len(pt)}ch")

        pos = pt.find("bkt_init_widget")
        if pos < 0:
            log("      bkt_init_widget NO encontrado (Imperva bloqueó POST?)")
            return False, {}
        info = _parse_bkt(pt[pos:pos + 1500])
        log(f"      agendas={info['agendas']} dates={info['dates']} raw={info['raw'][:60]}")
        return info["dates"] > 0, info

    except Exception as e:
        log(f"      ERROR: {e}")
        return False, {}


def _tg_post(endpoint: str, payload: dict):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{endpoint}",
            json=payload, timeout=12,
        )
        return r.ok
    except Exception:
        return False


def alerta_cita(tramite: str, nombre: str, url: str, hora: str):
    """Envía alerta con sonido al admin y al grupo."""
    msg = (
        f"🚨 <b>¡CITA DISPONIBLE AHORA!</b>\n\n"
        f"📋 <b>{nombre}</b>\n"
        f"⏰ {hora}\n\n"
        f"⚡ <b>Tienes ~2 minutos.</b> Entra YA y completa el captcha."
    )
    kb = {"inline_keyboard": [[{"text": "🔴🔴  RESERVAR CITA — ENTRA YA  🔴🔴", "url": url}]]}
    if ADMIN_CHAT_ID:
        _tg_post("sendMessage", {
            "chat_id": ADMIN_CHAT_ID, "text": msg, "parse_mode": "HTML",
            "disable_notification": False, "reply_markup": kb,
        })
    if TELEGRAM_CHAT_ID:
        _tg_post("sendMessage", {
            "chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML",
            "disable_notification": False, "reply_markup": kb,
        })
    log(f"*** ALERTA ENVIADA: {nombre} ***")


def main():
    tramites = _tramites_activos()
    urls = {}
    for t in tramites:
        u = os.getenv(SERVICIOS[t]["url_env"], "")
        if not u and t == "LEGA" and URL_SISTEMA:
            u = URL_SISTEMA
        if u:
            urls[t] = u

    if not urls:
        log("ERROR: sin URLs de widget configuradas (URL_LEGA, URL_LMD, URL_SISTEMA...)")
        sys.exit(1)

    log("=" * 65)
    log(f"OVC BURST — {MAX_MIN} min | poll {POLL_INTERVAL}±{POLL_JITTER}s | {len(urls)} servicio(s)")
    log(f"Servicios: {', '.join(urls.keys())}")
    log("=" * 65)

    inicio    = time.time()
    fin       = inicio + MAX_MIN * 60
    iteracion = 0

    while time.time() < fin:
        iteracion += 1
        restante = int((fin - time.time()) / 60)
        log(f"\n── Iteracion #{iteracion} | {restante} min restantes ──")

        for tramite, url in urls.items():
            nombre = SERVICIOS[tramite]["nombre"]
            log(f"  [{tramite}] {nombre}")
            disponible, info = check_bkt(url)
            if disponible:
                hora = datetime.now().strftime("%H:%M del %d/%m/%Y")
                alerta_cita(tramite, nombre, url, hora)
                log("*** CITA ENCONTRADA — saliendo del burst loop ***")
                sys.exit(0)

        # Espera con jitter entre iteraciones
        if time.time() < fin:
            wait = POLL_INTERVAL + random.randint(-POLL_JITTER, POLL_JITTER)
            wait = max(15, wait)  # mínimo 15s siempre
            log(f"  Próximo check en {wait}s...")
            time.sleep(wait)

    log(f"\nBurst completado — {iteracion} iteraciones en {MAX_MIN} min — sin disponibilidad")


if __name__ == "__main__":
    main()
