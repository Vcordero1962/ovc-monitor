#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
avc.py — Scraping del canal público de Telegram AVC (Asesor Virtual Cubano).

Una sola petición HTTP verifica todos los tramites simultáneamente.
Busca mensajes de las últimas 48h con frases que indiquen apertura de citas.

Función pública:
  check_all(tramites: list) → list[(tramite, nombre, fragmento_texto)]
"""

import re
import random
import requests
from datetime import datetime, timedelta, timezone

from core.config import SERVICIOS, USER_AGENTS, AVC_ALERTAS, URL_AVC
from core.logger import info, warn, error
from core.security import sanitize_html_fragment


def check_all(tramites: list) -> list:
    """
    Scraping del canal AVC en una sola petición.

    Retorna lista de (tramite, nombre, fragmento) para cada servicio
    donde se detectó alerta de apertura en las últimas 48h.
    Retorna [] si no hay alertas o si el canal no es accesible.
    """
    try:
        ua = random.choice(USER_AGENTS)
        headers = {
            "User-Agent":                ua,
            "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language":           "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding":           "gzip, deflate, br",
            "Connection":                "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest":            "document",
            "Sec-Fetch-Mode":            "navigate",
            "Sec-Fetch-Site":            "none",
            "Cache-Control":             "max-age=0",
        }

        resp = requests.get(URL_AVC, headers=headers, timeout=15)
        if not resp.ok:
            warn(f"AVC: HTTP {resp.status_code} — canal no accesible")
            return []

        html  = resp.text
        ahora = datetime.now(timezone.utc)
        limite = ahora - timedelta(hours=48)

        # Extraer pares (timestamp, texto_mensaje) de las últimas 48h
        patron = re.findall(
            r'<time[^>]+datetime="([^"]+)"[^>]*>.*?'
            r'<div[^>]+class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL | re.IGNORECASE,
        )

        html_reciente = ""
        mensajes_encontrados = 0
        for ts_str, texto in patron:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= limite:
                    html_reciente += " " + texto
                    mensajes_encontrados += 1
            except Exception:
                pass

        info(f"AVC: {mensajes_encontrados} mensajes en las últimas 48h")

        if not html_reciente.strip():
            info("AVC: sin mensajes recientes")
            return []

        bloque = html_reciente.upper()

        # Verificar si hay alguna frase de alerta en el bloque completo
        frases_encontradas = [a for a in AVC_ALERTAS if a in bloque]
        if not frases_encontradas:
            info("AVC: sin frases de alerta — sin novedad")
            return []

        info(f"AVC: frases de alerta detectadas: {frases_encontradas}")

        # Identificar qué tramites se mencionan junto a las alertas
        hits = []
        for tramite in tramites:
            servicio = SERVICIOS[tramite]
            keywords_encontradas = [kw for kw in servicio["keywords"] if kw in bloque]
            if keywords_encontradas:
                # Sanitizar fragmento antes de incluirlo en mensajes Telegram
                fragmento = sanitize_html_fragment(html_reciente, max_len=300)
                info(f"AVC HIT [{tramite}]: {servicio['nombre']} — keywords: {keywords_encontradas}")
                hits.append((tramite, servicio["nombre"], fragmento))

        return hits

    except Exception as e:
        error(f"AVC error inesperado: {e}", exc=e)
        return []
