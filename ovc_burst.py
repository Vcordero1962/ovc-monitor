#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ovc_burst.py — Modo Ráfaga para la ventana crítica de apertura de citas.

Corre un loop continuo durante MAX_MIN minutos, sondeando Bookitit cada
POLL_INTERVAL ±JITTER segundos. Alerta Telegram con sonido en cuanto
dates[] sea no-vacío.

No usa Playwright ni proxy residencial — solo requests puro (rápido y gratis).
Toda la lógica de detección y seguridad viene de core/bookitit.py.

Variables de entorno:
  MAX_MIN:       minutos de vigilancia continua (default 35)
  POLL_INTERVAL: segundos base entre polls (default 45)
  POLL_JITTER:   ±variación aleatoria en segundos (default 10)
  AVC_TRAMITE:   "ALL" o "LMD,LEGA" — tramites a vigilar
"""

import os
import sys
import time
import random
from datetime import datetime, timezone, timedelta

from core.config  import get_tramites_activos, get_url_for_tramite, SERVICIOS
from core.logger  import info, warn, error
from core.security import validate_telegram_creds
import core.bookitit  as bookitit
import core.telegram  as tg

MAX_MIN       = int(os.getenv("MAX_MIN",       "35"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "45"))
POLL_JITTER   = int(os.getenv("POLL_JITTER",   "10"))


def hora_miami() -> str:
    miami = datetime.now(timezone.utc) - timedelta(hours=4)
    return miami.strftime("%I:%M %p del %d/%m/%Y (Miami)")


def main():
    # Validar credenciales antes de empezar
    creds_ok, motivo = validate_telegram_creds()
    if not creds_ok:
        error(f"Credenciales Telegram inválidas: {motivo}")
        sys.exit(1)

    tramites = get_tramites_activos()
    urls = {t: get_url_for_tramite(t) for t in tramites if get_url_for_tramite(t)}

    if not urls:
        error("Sin URLs de widget configuradas — no hay nada que verificar")
        sys.exit(1)

    info("=" * 65)
    info(f"OVC BURST — {MAX_MIN} min | poll {POLL_INTERVAL}±{POLL_JITTER}s | {len(urls)} servicio(s)")
    info(f"Servicios: {', '.join(urls.keys())}")
    info("=" * 65)

    inicio    = time.time()
    fin       = inicio + MAX_MIN * 60
    iteracion = 0

    while time.time() < fin:
        iteracion += 1
        restante = int((fin - time.time()) / 60)
        hora     = hora_miami()
        info(f"\n── Iteracion #{iteracion} | {restante} min restantes | {hora} ──")

        for tramite, url in urls.items():
            nombre = SERVICIOS[tramite]["nombre"]
            info(f"  [{tramite}] {nombre}")
            disponible, data = bookitit.check_url(url)

            if disponible:
                hora_alerta = hora_miami()
                caption = (
                    f"🚨 <b>¡CITA DISPONIBLE AHORA!</b>\n\n"
                    f"📋 <b>{nombre}</b>\n"
                    f"⏰ {hora_alerta}\n\n"
                    f"⚡ <b>Tienes ~2 minutos.</b> Entra YA y completa el captcha."
                )
                card = tg.generar_card("SITIO", nombre, hora_alerta)
                if card:
                    tg.send_photo(caption, card, url_boton=url)
                else:
                    tg.send_text(caption, url_boton=url)

                tg.send_admin(
                    f"🚨 <b>CITA DISPONIBLE — {nombre}</b>\n⏰ {hora_alerta}\n\nEntra YA.",
                    url_boton=url, silencioso=False,
                )
                info("*** CITA ENCONTRADA — saliendo del burst loop ***")
                sys.exit(0)

        # Espera con jitter entre iteraciones
        if time.time() < fin:
            wait = POLL_INTERVAL + random.randint(-POLL_JITTER, POLL_JITTER)
            wait = max(15, wait)
            info(f"  Próximo check en {wait}s...")
            time.sleep(wait)

    info(f"\nBurst completado — {iteracion} iteraciones en {MAX_MIN} min — sin disponibilidad")


if __name__ == "__main__":
    main()
