#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bookitit.py — Verificación directa de disponibilidad via Bookitit POST token.

No requiere Playwright ni proxy residencial.

Flujo por URL:
  1. validate_widget_url()  → rechaza URLs fuera de citaconsular.es
  2. GET widget_url         → página con Imperva captcha gate
  3. Extraer token oculto   → campo <input name="token">
  4. validate_imperva_token()→ rechaza tokens malformados o con payloads JS
  5. POST widget_url        → Imperva deja pasar, devuelve widget real
  6. Parsear bkt_init_widget → contar dates[] con fechas YYYY-MM-DD

Función pública:
  check_all(tramites: list) → list[(tramite, nombre, url, info_dict)]
"""

import re
import random
import time
import requests

from core.config import SERVICIOS, USER_AGENTS, get_url_for_tramite
from core.logger import info, warn, error
from core.security import validate_widget_url, validate_imperva_token, SecurityError


# ── Helpers internos ───────────────────────────────────────────────────────────

def _human_sleep(min_s: float, max_s: float):
    """Sleep con distribución normal — más natural que uniforme."""
    media = (min_s + max_s) / 2
    std   = (max_s - min_s) / 4
    t = max(min_s, min(max_s, random.gauss(media, std)))
    time.sleep(t)


def _parse_bkt_widget(text: str) -> dict:
    """
    Extrae agendas[], dates[] y hours[] del objeto JS bkt_init_widget.

    Soporta claves con y sin comillas (JS estándar vs JSON).
    Busca fechas YYYY-MM-DD en todo el bloque (no solo en dates[]) porque
    Bookitit puede anidar las fechas dentro de agendas[].dates o agendas[].hours.
    """
    # --- agendas: contar objetos { en el bloque agendas (regex simple, no anidada)
    m_ag = re.search(r"(?:['\"]agendas['\"]|agendas)\s*:\s*\[", text, re.DOTALL)
    agendas_raw = ""
    if m_ag:
        # Extraer hasta 4000 chars del bloque agendas para cubrir estructuras grandes
        agendas_raw = text[m_ag.end(): m_ag.end() + 4000]

    # --- dates top-level (puede estar vacío si Bookitit anida fechas en agendas)
    m2 = re.search(r"(?:['\"]dates['\"]|dates)\s*:\s*(\[[^\]]*\])", text, re.DOTALL)
    dates_raw = m2.group(1) if m2 else "[]"

    # --- búsqueda amplia: cualquier YYYY-MM-DD en TODO el bloque del widget
    all_dates = re.findall(r'\d{4}-\d{2}-\d{2}', text)

    # --- hours: indicador alternativo de disponibilidad (slots de hora HH:MM)
    m_hours = re.search(r"(?:['\"]hours['\"]|hours)\s*:\s*\[([^\]]*)\]", text, re.DOTALL)
    hours_raw = m_hours.group(1) if m_hours else ""
    hours_count = len(re.findall(r'\d{1,2}:\d{2}', hours_raw))

    dates_count = len(all_dates)

    return {
        "agendas_count": len(re.findall(r'\{', agendas_raw)),
        "dates_count":   dates_count,
        "hours_count":   hours_count,
        "dates_raw":     str(all_dates[:5]),   # primeras 5 fechas encontradas
    }


def _base_headers(ua: str) -> dict:
    return {
        "User-Agent":                ua,
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":           "es-ES,es;q=0.9",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none",
        "Cache-Control":             "max-age=0",
    }


# ── Función principal ──────────────────────────────────────────────────────────

def check_url(widget_url: str) -> tuple:
    """
    Verifica disponibilidad en un widget de citaconsular.es.

    Retorna (disponible: bool, info: dict).
      disponible=True  → dates[] tiene fechas → CITA DISPONIBLE
      disponible=False → sin citas o error
    """
    # Paso 0 — Validar URL (anti-inyección de dominio)
    try:
        widget_url = validate_widget_url(widget_url)
    except SecurityError as e:
        error(f"BKT: URL rechazada — {e}")
        return False, {}

    ua      = random.choice(USER_AGENTS)
    session = requests.Session()
    headers = _base_headers(ua)

    try:
        # Paso 1 — GET: obtener captcha gate + token oculto
        r_get = session.get(widget_url, headers=headers, timeout=20, allow_redirects=True)
        if not r_get.ok:
            warn(f"BKT GET: HTTP {r_get.status_code}")
            return False, {}

        html_get = r_get.text
        info(f"BKT GET: {r_get.status_code} — {len(html_get)} chars")

        # Extraer token Imperva del HTML
        m = re.search(r'name=["\']token["\'][^>]*value=["\']([^"\']+)["\']', html_get)
        if not m:
            m = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']token["\']', html_get)

        if not m:
            warn("BKT token: campo <input name='token'> NO encontrado en GET response")
            return False, {}

        raw_token = m.group(1)

        # Paso 2 — Validar token antes de enviarlo (anti-inyección)
        try:
            token = validate_imperva_token(raw_token, source_url=widget_url)
            info(f"BKT token: {token[:20]}... ({len(token)} chars) — validado ✓")
        except SecurityError as se:
            error(f"BKT token RECHAZADO por seguridad: {se}")
            return False, {}

        # Paso 3 — POST: enviar token → Imperva deja pasar al widget real
        _human_sleep(0.8, 2.0)
        post_headers = dict(headers)
        post_headers.update({
            "Content-Type":   "application/x-www-form-urlencoded",
            "Referer":        widget_url,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        })

        r_post = session.post(
            widget_url,
            data={"token": token},
            headers=post_headers,
            timeout=20,
            allow_redirects=True,
        )
        if not r_post.ok:
            warn(f"BKT POST: HTTP {r_post.status_code}")
            return False, {}

        post_text = r_post.text
        info(f"BKT POST: {r_post.status_code} — {len(post_text)} chars")

        # Debug: primeros 800 chars del POST response (clave para diagnosticar)
        info(f"BKT POST preview: {post_text[:800].replace(chr(10), ' | ')}")

        # Paso 4 — Parsear bkt_init_widget
        bkt_pos = post_text.find("bkt_init_widget")
        if bkt_pos < 0:
            warn("BKT: bkt_init_widget NO encontrado en POST response (Imperva bloqueó?)")
            return False, {}

        bkt_block = post_text[bkt_pos: bkt_pos + 8000]
        # Debug: primeros 600 chars del bloque bkt_init_widget
        info(f"BKT widget block: {bkt_block[:600].replace(chr(10), ' | ')}")

        data = _parse_bkt_widget(bkt_block)
        info(
            f"BKT: agendas={data['agendas_count']} "
            f"dates={data['dates_count']} "
            f"hours={data['hours_count']} "
            f"raw={data['dates_raw']}"
        )

        if data["dates_count"] > 0 or data["hours_count"] > 0:
            info("BKT: *** DISPONIBILIDAD DETECTADA (fechas o slots) ***")
            return True, data

        if data["agendas_count"] > 0:
            info("BKT: agendas presentes pero sin fechas ni horas — sin citas hoy")
        else:
            info("BKT: agendas[], dates[] y hours[] vacíos — sin disponibilidad")

        return False, data

    except Exception as e:
        error(f"BKT error inesperado: {e}", exc=e)
        return False, {}


def check_all(tramites: list) -> list:
    """
    Verifica Bookitit para todos los tramites activos que tengan URL configurada.

    Retorna lista de (tramite, nombre, url, info_dict) donde hay disponibilidad.
    """
    hits = []
    for i, tramite in enumerate(tramites):
        servicio = SERVICIOS[tramite]
        url = get_url_for_tramite(tramite)

        if not url:
            info(f"BKT [{tramite}]: sin URL configurada ({servicio['url_env']} vacío) — omitiendo")
            continue

        info(f"BKT verificando [{tramite}] {servicio['nombre']}...")
        disponible, data = check_url(url)

        if disponible:
            hits.append((tramite, servicio["nombre"], url, data))

        if i < len(tramites) - 1:
            _human_sleep(1.5, 3.5)

    return hits
