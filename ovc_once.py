#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ovc_once.py — Orquestador principal OVC (GitHub Actions, un run por ejecución).

Arquitectura modular — este archivo solo coordina:
  core/config.py          → configuración y catálogo de servicios
  core/logger.py          → logging estructurado con niveles
  core/security.py        → validaciones anti-inyección
  core/bookitit.py        → check Bookitit POST (sin Playwright, sin proxy)
  core/playwright_check.py→ check sitio directo con Playwright + stealth
  core/avc.py             → scraping canal AVC Telegram
  core/telegram.py        → envío de alertas y confirmaciones

3 capas de detección (en orden):
  1. Sitio oficial (Playwright) — si SITIO_DIRECTO_ENABLED=1
  2. Bookitit POST directo      — si BOOKITIT_POST_ENABLED=1
  3. Canal AVC                  — siempre
"""

import sys
import random
import time
import os
from datetime import datetime, timedelta, timezone

# ── Core modules ───────────────────────────────────────────────────────────────
from core.config import (
    SITIO_DIRECTO_ENABLED, BOOKITIT_POST_ENABLED, STATUS_CADA_RUN,
    SERVICIOS, get_tramites_activos, get_url_for_tramite,
)
from core.logger  import info, warn, error, critical
from core.security import validate_telegram_creds
import core.bookitit       as bookitit
import core.avc            as avc
import core.telegram       as tg

if SITIO_DIRECTO_ENABLED:
    import core.playwright_check as pw


def hora_miami() -> str:
    """Hora actual en Miami (EDT = UTC-4, válido mar-nov)."""
    miami = datetime.now(timezone.utc) - timedelta(hours=4)
    return miami.strftime("%I:%M %p del %d/%m/%Y (Miami)")


def main():
    # Anti-detección: sleep gaussiano al inicio — rompe el patrón regular del cron
    espera = max(10, min(90, int(random.gauss(45, 20))))
    info(f"Anti-deteccion: esperando {espera}s antes de consultar...")
    time.sleep(espera)

    # Validar credenciales de Telegram al inicio — fallo temprano si faltan
    creds_ok, creds_motivo = validate_telegram_creds()
    if not creds_ok:
        critical(f"Credenciales Telegram inválidas: {creds_motivo}")
        sys.exit(1)

    tramites = get_tramites_activos()
    hora     = hora_miami()
    info(f"=== OVC check — {hora} — tramites: {', '.join(tramites)} ===")

    # Verificar que al menos alguna URL esté configurada
    urls_configuradas = [t for t in tramites if get_url_for_tramite(t)]
    if not urls_configuradas:
        warn("Ninguna URL de widget configurada — solo se verificará el canal AVC")

    hits_sitio: list = []
    hits_bkt:   list = []
    hits_avc:   list = []

    # ── Capa 1: Sitio oficial via Playwright ────────────────────────────────────
    if SITIO_DIRECTO_ENABLED:
        info(f"[CAPA 1] Sitio oficial via Playwright ({len(tramites)} servicios)...")
        hits_sitio = pw.check_all(tramites)
        for tramite, nombre, url, screenshot in hits_sitio:
            info(f"*** CITA DISPONIBLE en sitio oficial: {nombre} ***")
            caption = (
                f"🚨 <b>¡CITA DISPONIBLE AHORA!</b>\n\n"
                f"📋 <b>{nombre}</b>\n"
                f"⏰ {hora}\n\n"
                f"⚡ <b>Tienes ~2 minutos</b> antes de que desaparezca.\n"
                f"Entra YA y completa el captcha."
            )
            foto = screenshot or tg.generar_card("SITIO", nombre, hora)
            if foto:
                tg.send_photo(caption, foto, url_boton=url)
            else:
                tg.send_text(caption, url_boton=url)
            tg.send_admin(
                f"🚨 <b>CITA DISPONIBLE — {nombre}</b>\n⏰ {hora}\n\nEntra YA.",
                url_boton=url, silencioso=False,
            )
        if hits_sitio:
            _send_status(hora, tramites, hits_sitio, hits_bkt, hits_avc)
            sys.exit(0)
        info("[CAPA 1] Sin disponibilidad en sitio oficial")
    else:
        info("[CAPA 1] Omitido (SITIO_DIRECTO_ENABLED=0)")

    # ── Capa 2: Bookitit POST directo ───────────────────────────────────────────
    if BOOKITIT_POST_ENABLED:
        info(f"[CAPA 2] Bookitit POST directo ({len(tramites)} servicios)...")
        hits_bkt = bookitit.check_all(tramites)
        for tramite, nombre, url, data in hits_bkt:
            info(f"*** CITA DISPONIBLE via Bookitit POST: {nombre} ***")
            caption = (
                f"🚨 <b>¡CITA DISPONIBLE AHORA!</b>\n\n"
                f"📋 <b>{nombre}</b>\n"
                f"⏰ {hora}\n\n"
                f"⚡ <b>Tienes ~2 minutos</b> antes de que desaparezca.\n"
                f"Entra YA y completa el captcha."
            )
            foto = tg.generar_card("SITIO", nombre, hora)
            if foto:
                tg.send_photo(caption, foto, url_boton=url)
            else:
                tg.send_text(caption, url_boton=url)
            tg.send_admin(
                f"🚨 <b>CITA DISPONIBLE — {nombre}</b>\n⏰ {hora}\n\nEntra YA.",
                url_boton=url, silencioso=False,
            )
        if hits_bkt:
            _send_status(hora, tramites, hits_sitio, hits_bkt, hits_avc)
            sys.exit(0)
        info("[CAPA 2] Sin disponibilidad via Bookitit POST")
    else:
        info("[CAPA 2] Omitido (BOOKITIT_POST_ENABLED=0)")

    # ── Capa 3: Canal AVC ───────────────────────────────────────────────────────
    info(f"[CAPA 3] Canal AVC ({len(tramites)} servicios)...")
    hits_avc = avc.check_all(tramites)
    for tramite, nombre, detalle in hits_avc:
        info(f"*** Alerta AVC: {nombre} ***")
        url_servicio = get_url_for_tramite(tramite)
        avc_msg = (
            f"⚠️ <b>¡CITAS ABRIENDOSE PRONTO!</b>\n\n"
            f"📋 <b>{nombre}</b>\n"
            f"⏰ {hora}\n\n"
            f"📢 {detalle[:180]}\n\n"
            f"Ten el formulario listo. <b>Actua en cuanto abran.</b>\n\n"
            f"💡 El consulado suele liberar citas a las <b>8:00 AM hora de España</b> "
            f"(3:00 AM Miami / 7:00 AM UTC)."
        )
        card = tg.generar_card("AVC", nombre, hora, detalle)
        if card:
            tg.send_photo(avc_msg, card, url_boton=url_servicio)
        else:
            tg.send_text(avc_msg, url_boton=url_servicio)
        tg.send_admin(
            f"⚠️ <b>Alerta AVC — {nombre}</b>\n⏰ {hora}\nCitas abriendo pronto.",
            url_boton=url_servicio, silencioso=True,
        )

    if not hits_avc:
        info("[CAPA 3] Sin novedad en canal AVC")

    info("=== Check completado ===")
    _send_status(hora, tramites, hits_sitio, hits_bkt, hits_avc)


def _send_status(hora, tramites, hits_sitio, hits_bkt, hits_avc):
    """Confirmación silenciosa de run al admin si STATUS_CADA_RUN=1."""
    if STATUS_CADA_RUN:
        tg.send_status(
            hora=hora,
            tramites=tramites,
            hits_sitio=hits_sitio,
            hits_bkt=hits_bkt,
            hits_avc=hits_avc,
            sitio_enabled=SITIO_DIRECTO_ENABLED,
            bkt_enabled=BOOKITIT_POST_ENABLED,
        )


if __name__ == "__main__":
    main()
